"""P4 integration acceptance: real loopback P2/P3 with fake providers only."""

import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from integration.contracts import ContractError, Item, Plan
from integration.history import History
from integration.lease import LeaseError
from integration.p2_adapter import P2Adapter
from integration.p3_adapter import run_check
from integration.providers import FakeProvider
from integration.supervisor import Supervisor


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.managers = []
        self.supervisor = self.manager()

    def manager(self, **kwargs):
        manager = Supervisor(self.root, **kwargs)
        self.managers.append(manager)
        return manager

    async def asyncTearDown(self):
        for manager in self.managers:
            await manager.close()
        self.temporary.cleanup()

    async def finish(self, handle):
        await asyncio.wait_for(asyncio.shield(handle.task), 8)
        self.assertNotEqual(handle.state, "finalizing_failed", handle.events[-3:])
        self.assertIsNotNone(handle.result)
        return handle.result

    async def run_plan(self, plan, supervisor=None):
        handle = (supervisor or self.supervisor).start(plan)
        await self.finish(handle)
        return handle

    async def until(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("Expected lifecycle boundary did not occur")
            await asyncio.sleep(0.002)

    def assert_blocked_rows(self, handle, code, current_status=None):
        self.assertEqual(handle.result["reason_code"], code)
        for index, row in enumerate(handle.result["items"]):
            self.assertEqual(row["verdict"], "inconclusive")
            self.assertTrue(row["reason"])
            self.assertTrue(row["reason_code"])
            self.assertEqual(row["execution_status"], current_status if index == 0 and current_status else "not_run")

    async def test_three_verdicts_execute_sequentially_using_actual_adapters(self):
        plan = Plan("three", items=(Item("check-pass"), Item("check-fail", "fail"), Item("check-unknown", "inconclusive")))
        h = await self.run_plan(plan)
        self.assertEqual(h.state, "completed")
        self.assertEqual(h.result["verdict_counts"], {"pass": 1, "fail": 1, "inconclusive": 1})
        self.assertEqual([r["execution_status"] for r in h.rows], ["completed"] * 3)
        self.assertEqual([r["verdict_label"] for r in h.rows], ["양호", "취약", "판단 불가능"])
        self.assertEqual(h.p2_report["source"], "real_p2_loopback")
        self.assertEqual(h.p2_report["persisted_packets"], 1)
        self.assertTrue(all(r["p3"]["source"] == "real_p3_synthetic" for r in h.rows))
        self.assertEqual(len({r["attempt_id"] for r in h.rows}), 3)
        lifecycle = [(e["type"], e["item_id"]) for e in h.events if e["type"] in {"item_running", "item_cleaning", "item_terminal"}]
        self.assertEqual(lifecycle, [(kind, item.item_id) for item in plan.items for kind in ("item_running", "item_cleaning", "item_terminal")])
        self.assertEqual(self.supervisor.lease.inspect()["lifecycle"], "free")
        snapshot = json.loads((h.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["route"]["reason"], "P1_NOT_INTEGRATED")
        self.assertEqual(snapshot["contract_snapshot"], h.contract)

    async def test_ten_simultaneous_starts_have_one_owner_and_nine_final_busy_results(self):
        handles = [self.supervisor.start(Plan(f"compete-{i}")) for i in range(10)]
        peak = 0
        while not all(h.task.done() for h in handles):
            active = sum(h.state in {"preparing", "running"} for h in handles)
            peak = max(peak, active)
            self.assertLessEqual(active, 1)
            await asyncio.sleep(0.002)
        for h in handles:
            await self.finish(h)
        self.assertEqual(peak, 1)
        self.assertEqual(sum(h.state == "completed" for h in handles), 1)
        busy = [h for h in handles if h.state != "completed"]
        self.assertEqual(len(busy), 9)
        for h in busy:
            self.assert_blocked_rows(h, "DEVICE_BUSY_OR_RECOVERY_REQUIRED")
        self.assertEqual(len(self.supervisor.history.list()), 10)

    async def test_independent_supervisors_share_durable_exclusion(self):
        other = self.manager()
        first = self.supervisor.start(Plan("owner", main_behavior="hang"))
        await self.until(lambda: first.state == "running")
        second = await self.run_plan(Plan("contender"), other)
        self.assert_blocked_rows(second, "DEVICE_BUSY_OR_RECOVERY_REQUIRED")
        self.assertEqual(other.lease.inspect()["run_id"], first.run_id)
        self.supervisor.cancel(first.run_id)
        await self.finish(first)

    async def test_duplicate_start_is_same_handle_and_changed_payload_conflicts(self):
        plan = Plan("same")
        first = self.supervisor.start(plan)
        self.assertIs(self.supervisor.start(plan), first)
        with self.assertRaisesRegex(ContractError, "COMMAND_CONFLICT"):
            self.supervisor.start(replace(plan, proxy_on=False))
        await self.finish(first)
        self.assertIs(self.supervisor.start(plan), first)
        self.assertEqual(len(self.supervisor.history.list()), 1)

    async def test_duplicate_cancel_emits_one_cancelling_transition(self):
        h = self.supervisor.start(Plan("cancel-twice", items=(Item("current", provider_behavior="hang"), Item("later"))))
        await self.until(lambda: any(e["type"] == "provider_started" and e["item_id"] == "current" for e in h.events))
        a = self.supervisor.cancel(h.run_id)
        b = self.supervisor.cancel(h.run_id)
        self.assertEqual(a, b)
        await self.finish(h)
        self.assertEqual(h.state, "cancelled")
        self.assertEqual([r["execution_status"] for r in h.rows], ["cancelled", "not_run"])
        self.assertEqual(sum(e["type"] == "run_state" and e["payload"]["state"] == "cancelling" for e in h.events), 1)
        self.assertTrue(all(f.done() for f in h.resources))

    async def test_cancel_before_preflight_keeps_all_selected_rows(self):
        h = self.supervisor.start(Plan("cancel-early", items=(Item("one"), Item("two"))))
        self.supervisor.cancel(h.run_id)
        await self.finish(h)
        self.assertEqual(h.state, "cancelled")
        self.assertTrue(all(r["reason_code"] == "RUN_CANCELLED_BEFORE_START" for r in h.rows))
        self.assertTrue(all(r["execution_status"] == "not_run" for r in h.rows))
        self.assertEqual(self.supervisor.lease.inspect()["generation"], 0)

    async def test_missing_cancel_capability_blocks_before_lease_and_tools(self):
        h = await self.run_plan(Plan("no-cancel-capability", cancellation_supported=False))
        self.assert_blocked_rows(h, "PROVIDER_CAPABILITY_UNAVAILABLE")
        self.assertIsNone(h.p2)
        self.assertEqual(self.supervisor.lease.inspect()["generation"], 0)

    async def test_preflight_missing_contract_is_final_history_with_all_rows_not_run(self):
        with patch("integration.supervisor.snapshot", side_effect=FileNotFoundError("synthetic-missing-skill")):
            h = await self.run_plan(Plan("missing-contract", items=(Item("one"), Item("two"))))
        self.assert_blocked_rows(h, "PREFLIGHT_CONTRACT_ERROR")
        self.assertIsNone(h.p2)
        self.assertEqual(self.supervisor.lease.inspect()["generation"], 0)
        self.assertEqual([r["run_id"] for r in self.supervisor.history.list()], [h.run_id])
        self.assertIsNone(json.loads((h.output / "run.json").read_text(encoding="utf-8"))["contract_snapshot"])

    async def test_invalid_target_platform_selection_and_version_create_no_run(self):
        invalid = [Plan("device", device_id="actual-device"), Plan("ios", platform="ios"),
                   Plan("version", schema_version="9"), Plan("empty", items=()),
                   Plan("duplicate", items=(Item("same"), Item("same")))]
        for plan in invalid:
            with self.subTest(command=plan.command_id), self.assertRaises(ContractError):
                self.supervisor.start(plan)
        self.assertEqual(self.supervisor.handles, {})
        self.assertEqual(self.supervisor.history.list(), [])

    async def test_quiet_main_and_item_are_not_mistaken_for_hang(self):
        h = await self.run_plan(Plan("quiet", main_behavior="quiet", items=(Item("quiet-item", provider_behavior="quiet"),)))
        self.assertEqual(h.state, "completed")
        self.assertEqual(h.rows[0]["verdict"], "pass")
        self.assertFalse(any(e["type"] == "provider_event" for e in h.events))

    async def test_main_error_stops_all_items(self):
        h = await self.run_plan(Plan("main-error", main_behavior="error"))
        self.assert_blocked_rows(h, "MAIN_ERROR")

    async def test_main_exit_is_not_a_successful_plan(self):
        h = await self.run_plan(Plan("main-exit", main_behavior="exit"))
        self.assert_blocked_rows(h, "MAIN_EXIT")

    async def test_main_hang_with_heartbeat_is_progress_failure(self):
        h = await self.run_plan(Plan("main-hang", main_behavior="hang", progress_timeout=0.06))
        self.assert_blocked_rows(h, "MAIN_HANG")
        self.assertGreater(h.providers[0][1].heartbeat, h.providers[0][1].created_at)

    async def test_main_heartbeat_loss_has_distinct_code(self):
        h = await self.run_plan(Plan("main-heartbeat", main_behavior="heartbeat_lost", heartbeat_timeout=0.06))
        self.assert_blocked_rows(h, "MAIN_HEARTBEAT_LOST")

    async def test_item_error_marks_current_failed_and_later_not_run(self):
        h = await self.run_plan(Plan("item-error", items=(Item("current", provider_behavior="error"), Item("later"))))
        self.assert_blocked_rows(h, "ITEM_ERROR", "failed")

    async def test_item_exit_is_not_tool_success(self):
        h = await self.run_plan(Plan("item-exit", items=(Item("current", provider_behavior="exit"),)))
        self.assert_blocked_rows(h, "ITEM_EXIT", "failed")

    async def test_item_hang_marks_current_timed_out(self):
        h = await self.run_plan(Plan("item-hang", items=(Item("current", provider_behavior="hang"), Item("later")), progress_timeout=0.06))
        self.assert_blocked_rows(h, "ITEM_HANG", "timed_out")

    async def test_item_heartbeat_loss_is_separate_from_hang(self):
        h = await self.run_plan(Plan("item-heartbeat", items=(Item("current", provider_behavior="heartbeat_lost"),), heartbeat_timeout=0.06))
        self.assert_blocked_rows(h, "ITEM_HEARTBEAT_LOST", "timed_out")

    async def test_main_scope_expansion_is_rejected_and_quarantined(self):
        h = await self.run_plan(Plan("main-scope", main_behavior="out_of_scope"))
        self.assert_blocked_rows(h, "MAIN_SCOPE_VIOLATION")
        self.assertTrue(h.result["recovery_required"])

    async def test_item_unavailable_operation_is_rejected_before_tool(self):
        h = await self.run_plan(Plan("item-scope", items=(Item("current", provider_behavior="out_of_scope"),)))
        self.assert_blocked_rows(h, "ITEM_SCOPE_VIOLATION", "failed")
        self.assertFalse(any(e["type"] == "tool_started" for e in h.events))

    async def test_run_deadline_is_distinct_from_main_hang(self):
        h = await self.run_plan(Plan("run-deadline", main_behavior="hang", run_timeout=0.1))
        self.assert_blocked_rows(h, "RUN_TIMEOUT")

    async def test_item_deadline_is_distinct_from_provider_hang(self):
        h = await self.run_plan(Plan("item-deadline", items=(Item("current", provider_behavior="hang"),), item_timeout=0.06))
        self.assert_blocked_rows(h, "ITEM_TIMEOUT", "timed_out")

    async def test_tool_deadline_stops_current_and_all_followups(self):
        h = await self.run_plan(Plan("tool-deadline", items=(Item("current", tool_fault="timeout"), Item("later")), tool_timeout=0.5, cancel_grace=0.02))
        self.assert_blocked_rows(h, "TOOL_TIMEOUT", "timed_out")
        self.assertTrue(all(f.done() for f in h.resources))
        self.assertEqual(self.supervisor.lease.inspect()["lifecycle"], "free")

    async def test_completed_fail_is_preserved_when_later_tool_errors(self):
        h = await self.run_plan(Plan("partial", items=(Item("proved", "fail"), Item("broken", tool_fault="error"), Item("later"))))
        self.assertEqual(h.result["reason_code"], "TOOL_ERROR")
        self.assertEqual([r["execution_status"] for r in h.rows], ["completed", "failed", "not_run"])
        self.assertEqual([r["verdict"] for r in h.rows], ["fail", "inconclusive", "inconclusive"])
        self.assertTrue(h.rows[0]["evidence_refs"])

    async def test_fake_disconnect_requires_recovery_and_blocks_new_start(self):
        h = await self.run_plan(Plan("disconnect", items=(Item("current", tool_fault="disconnect"), Item("later"))))
        self.assert_blocked_rows(h, "DEVICE_DISCONNECTED", "failed")
        self.assertEqual(self.supervisor.lease.inspect()["lifecycle"], "recovery_required")
        later = await self.run_plan(Plan("after-disconnect"))
        self.assert_blocked_rows(later, "DEVICE_BUSY_OR_RECOVERY_REQUIRED")

    async def test_cleanup_failed_preserves_proved_vulnerability_and_blocks(self):
        h = await self.run_plan(Plan("cleanup-failed", items=(Item("proved", "fail", cleanup_fault="failed"), Item("later"))))
        self.assertEqual(h.result["reason_code"], "CLEANUP_FAILED")
        self.assertEqual(h.rows[0]["verdict"], "fail")
        self.assertEqual(h.rows[0]["execution_status"], "failed")
        self.assertEqual(h.rows[1]["execution_status"], "not_run")
        self.assertEqual(self.supervisor.lease.inspect()["lifecycle"], "recovery_required")

    async def test_cleanup_unknown_is_durable_after_supervisor_restart(self):
        h = await self.run_plan(Plan("cleanup-unknown", items=(Item("proved", "fail", cleanup_fault="unknown"),)))
        self.assertEqual(h.result["reason_code"], "CLEANUP_UNKNOWN")
        self.assertEqual(h.rows[0]["verdict"], "fail")
        restarted = self.manager()
        blocked = await self.run_plan(Plan("after-restart"), restarted)
        self.assert_blocked_rows(blocked, "DEVICE_BUSY_OR_RECOVERY_REQUIRED")

    async def test_cancel_ignoring_worker_keeps_quarantine_after_late_completion(self):
        h = self.supervisor.start(Plan("ignore-cancel", items=(Item("current", provider_behavior="ignores_cancel"), Item("later")), cancel_grace=0.02))
        await self.until(lambda: len(h.providers) == 2)
        await asyncio.sleep(0.01)
        self.supervisor.cancel(h.run_id)
        await self.finish(h)
        self.assertEqual(h.state, "cancelled")
        self.assertFalse(h.providers[-1][1].task.done())
        self.assertEqual(h.result["cleanup_status"], "unknown")
        self.assertEqual(self.supervisor.lease.inspect()["lifecycle"], "recovery_required")
        frozen = deepcopy(h.result)
        events = deepcopy(h.events)
        blocked = await self.run_plan(Plan("after-ignored-cancel"))
        self.assert_blocked_rows(blocked, "DEVICE_BUSY_OR_RECOVERY_REQUIRED")
        await h.providers[-1][1].task
        self.assertEqual(h.result, frozen)
        self.assertEqual(h.events, events)
        self.assertEqual(self.supervisor.lease.inspect()["lifecycle"], "recovery_required")

    async def test_safe_cancel_releases_only_after_termination_and_new_run_gets_new_fence(self):
        h = self.supervisor.start(Plan("safe-cancel", items=(Item("current", provider_behavior="hang"),)))
        await self.until(lambda: len(h.providers) == 2)
        old = h.token
        self.supervisor.cancel(h.run_id)
        self.assertEqual(self.supervisor.lease.inspect()["lifecycle"], "cleaning")
        with self.assertRaises(LeaseError):
            self.supervisor.lease.authorize(old, "p3.check")
        blocked = self.supervisor.start(Plan("during-cleanup"))
        await self.finish(blocked)
        self.assert_blocked_rows(blocked, "DEVICE_BUSY_OR_RECOVERY_REQUIRED")
        await self.finish(h)
        next_run = await self.run_plan(Plan("after-safe-cancel"))
        self.assertEqual(next_run.state, "completed")
        self.assertGreater(next_run.token.generation, old.generation)
        with self.assertRaises(LeaseError):
            self.supervisor.lease.authorize(old, "p3.check")

    async def test_safe_timeout_allows_new_run_after_cleanup(self):
        h = await self.run_plan(Plan("safe-timeout", main_behavior="hang", progress_timeout=0.06))
        self.assertEqual(h.result["reason_code"], "MAIN_HANG")
        self.assertEqual(h.result["cleanup_status"], "completed")
        next_run = await self.run_plan(Plan("after-safe-timeout"))
        self.assertEqual(next_run.state, "completed")

    async def test_proxy_off_has_no_packet_coverage_but_p3_still_runs(self):
        h = await self.run_plan(Plan("proxy-off", proxy_on=False))
        self.assertEqual(h.state, "completed")
        self.assertEqual(h.p2_report["network_coverage"], "none")
        self.assertEqual(h.p2_report["persisted_packets"], 0)
        self.assertEqual(h.rows[0]["verdict"], "pass")
        self.assertFalse(h.p2_report["causal_for_chk07"])

    async def test_proxy_error_is_separate_from_item_failure(self):
        class BrokenProxy(P2Adapter):
            async def capture(self, proxy_on=True):
                raise RuntimeError("SYNTHETIC_PROXY_FAULT")

        manager = self.manager(p2_factory=BrokenProxy)
        h = await self.run_plan(Plan("proxy-error"), manager)
        self.assert_blocked_rows(h, "PROXY_ERROR")
        self.assertTrue(any(e["type"] == "proxy_error" for e in h.events))
        self.assertEqual(manager.lease.inspect()["lifecycle"], "free")

    async def test_proxy_cleanup_failure_blocks_despite_completed_item(self):
        class FailedCleanup(P2Adapter):
            async def cleanup(self):
                await super().cleanup()
                return {"status": "failed", "reason_code": "SYNTHETIC_CLEANUP_FAILURE"}

        manager = self.manager(p2_factory=FailedCleanup)
        h = await self.run_plan(Plan("proxy-cleanup-failure"), manager)
        self.assertEqual(h.state, "failed")
        self.assertEqual(h.rows[0]["verdict"], "pass")
        self.assertEqual(h.result["cleanup_status"], "failed")
        self.assertEqual(manager.lease.inspect()["lifecycle"], "recovery_required")

    async def test_proxy_cleanup_timeout_retains_quarantine_after_cleanup_later_finishes(self):
        release_cleanup = asyncio.Event()

        class SlowCleanup(P2Adapter):
            async def cleanup(self):
                result = await super().cleanup()
                await release_cleanup.wait()
                return result

        manager = self.manager(p2_factory=SlowCleanup)
        h = manager.start(Plan("cleanup-timeout", cleanup_timeout=0.04))
        try:
            await self.finish(h)
            self.assertEqual(h.state, "failed")
            self.assertEqual(h.result["cleanup_status"], "unknown")
            self.assertFalse(h.result["cleanup"]["terminated"])
            self.assertTrue(any(not future.done() for future in h.resources))
            self.assertEqual(manager.lease.inspect()["lifecycle"], "recovery_required")
            frozen = deepcopy(h.result)
        finally:
            release_cleanup.set()
            await asyncio.gather(*h.resources, return_exceptions=True)
        self.assertEqual(h.result, frozen)
        blocked = await self.run_plan(Plan("after-slow-cleanup"), manager)
        self.assert_blocked_rows(blocked, "DEVICE_BUSY_OR_RECOVERY_REQUIRED")
        self.assertEqual(manager.lease.inspect()["lifecycle"], "recovery_required")

    async def test_live_events_are_run_scoped_and_history_is_terminal_only(self):
        prior = await self.run_plan(Plan("prior"))
        active = self.supervisor.start(Plan("active", main_behavior="hang"))
        await self.until(lambda: active.state == "running")
        self.assertEqual([r["run_id"] for r in self.supervisor.history.list()], [prior.run_id])
        events = self.supervisor.events_after(active.run_id)
        self.assertTrue(all(e["run_id"] == active.run_id and e["verdict"] is None for e in events))
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(self.supervisor.events_after(active.run_id, events[-1]["seq"]), [])
        events[0]["payload"]["tampered"] = True
        self.assertNotIn("tampered", self.supervisor.events_after(active.run_id)[0]["payload"])
        self.supervisor.cancel(active.run_id)
        await self.finish(active)
        self.assertEqual(len(self.supervisor.history.list()), 2)
        self.assertFalse(any("events" in result or "heartbeat" in result for result in self.supervisor.history.list()))

    async def test_finalization_storage_failure_is_not_published_or_completed(self):
        class BrokenHistory(History):
            def finalize(self, *args):
                raise OSError("SYNTHETIC_DISK_FULL")

        manager = self.manager(history_factory=BrokenHistory)
        h = manager.start(Plan("finalization-fault"))
        await asyncio.wait_for(h.task, 8)
        self.assertEqual(h.state, "finalizing_failed")
        self.assertIsNone(h.result)
        self.assertEqual(h.error_code, "FINALIZATION_FAILED")
        self.assertEqual(manager.history.list(), [])
        self.assertEqual(manager.lease.inspect()["lifecycle"], "free")

    async def test_running_sync_tool_is_not_cancelled_or_declared_terminated(self):
        entered = threading.Event()
        release = threading.Event()

        def slow_runner(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("TEST_RELEASE_TIMEOUT")
            return run_check(*args, **kwargs)

        manager = self.manager(p3_runner=slow_runner)
        h = manager.start(Plan("slow-p3", cancel_grace=0.02))
        try:
            await self.until(entered.is_set)
            manager.cancel(h.run_id)
            await self.finish(h)
            self.assertFalse(h.uncancellable[0].done())
            self.assertFalse(h.uncancellable[0].cancelled())
            self.assertFalse(h.result["cleanup"]["terminated"])
            self.assertEqual(manager.lease.inspect()["lifecycle"], "recovery_required")
            self.assertEqual(h.rows[0]["verdict"], "inconclusive")
            frozen = deepcopy(h.result)
        finally:
            release.set()
            if h.uncancellable:
                await asyncio.wait_for(asyncio.shield(h.uncancellable[0]), 4)
        self.assertEqual(h.result, frozen)
        self.assertEqual(manager.lease.inspect()["lifecycle"], "recovery_required")


if __name__ == "__main__":
    unittest.main()
