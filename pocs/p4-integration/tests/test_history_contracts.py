"""User-visible final history invariants against real synthetic P2/P3 outputs."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from integration.contracts import ContractError, Item, Plan
from integration.history import History, validate_final
from integration.supervisor import Supervisor


class PlanContractTests(unittest.TestCase):
    def test_only_versioned_synthetic_aos_plans_and_known_fake_behaviors(self):
        invalid = [
            {"schema_version": "2.0"}, {"synthetic": False}, {"synthetic": 1},
            {"device_id": "usb-device"}, {"app_id": "com.bank.real"},
            {"platform": "ios"}, {"main_behavior": "unknown"},
            {"provider_name": "real-model"},
            {"items": (Item("one", provider_behavior="unknown"),)},
            {"items": (Item("one", check_id="CHK-99"),)},
        ]
        for fields in invalid:
            with self.subTest(fields=fields):
                with self.assertRaises(ContractError):
                    replace(Plan("synthetic-command"), **fields).validate()

    def test_selection_must_be_nonempty_and_unambiguous(self):
        for items in ((), (Item("same"), Item("same")), [Item("one")]):
            with self.subTest(items=items):
                with self.assertRaises(ContractError):
                    Plan("synthetic-command", items=items).validate()

    def test_every_deadline_is_finite_positive_and_bounded(self):
        for field in ("heartbeat_timeout", "progress_timeout", "tool_timeout",
                      "item_timeout", "run_timeout", "cancel_grace", "cleanup_timeout"):
            for value in (0, -1, float("inf"), float("nan"), 121, True, None):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ContractError):
                        replace(Plan("synthetic-command"), **{field: value}).validate()


class FinalHistoryContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-p4-history-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.supervisor = self.manager("runs")

    def manager(self, name, **kwargs):
        manager = Supervisor(self.root / name, **kwargs)
        self.addAsyncCleanup(manager.close)
        return manager

    async def completed(self, items=None):
        items = (Item("synthetic-item", "pass"),) if items is None else items
        handle = self.supervisor.start(Plan("synthetic-command", items=items))
        result = await asyncio.wait_for(handle.task, 10)
        self.assertIsNotNone(result, handle.error_code)
        self.assertEqual(handle.state, "completed")
        return handle, result

    def validate(self, handle, result):
        return validate_final(result, root=handle.output, snapshot=handle.contract)

    async def test_completed_inconclusive_is_a_valid_final_judgment_with_reason(self):
        handle, result = await self.completed((Item("synthetic-unknown", "inconclusive"),))
        self.assertEqual(self.validate(handle, result), result)
        row = result["items"][0]
        self.assertEqual(row["execution_status"], "completed")
        self.assertEqual(row["verdict"], "inconclusive")
        self.assertEqual(row["verdict_label"], "판단 불가능")
        self.assertTrue(row["reason"].strip())
        self.assertTrue(row["reason_code"].strip())
        self.assertEqual(self.supervisor.history.list(), [result])

    async def test_invalid_plan_does_not_create_run_or_history(self):
        with self.assertRaises(ContractError):
            self.supervisor.start(Plan("invalid-command", items=()))
        self.assertFalse(self.supervisor.handles)
        self.assertEqual(self.supervisor.history.list(), [])
        self.assertFalse(list(self.supervisor.root.glob("synthetic-run-*")))

    async def test_live_events_and_pending_runs_are_absent_from_history(self):
        handle = self.supervisor.start(Plan("pending-command", main_behavior="hang",
                                           heartbeat_timeout=1, progress_timeout=1))
        for _ in range(200):
            if any(e["type"] == "provider_started" for e in handle.events):
                break
            await asyncio.sleep(0.005)
        else:
            self.fail("Fake provider did not start")
        self.assertIsNone(handle.result)
        self.assertFalse((handle.output / "final.json").exists())
        self.assertEqual(self.supervisor.history.list(), [])
        events = self.supervisor.events_after(handle.run_id)
        self.assertTrue(events)
        self.assertTrue(all(event["verdict"] is None for event in events))
        self.supervisor.cancel(handle.run_id)
        result = await asyncio.wait_for(handle.task, 10)
        self.assertEqual(result["execution_status"], "cancelled")
        self.assertEqual(self.supervisor.history.list(), [result])
        self.assertNotIn("events", self.supervisor.history.list()[0])

    async def test_finalization_storage_failure_is_not_successful_history(self):
        class FailingHistory(History):
            def finalize(self, result, output, snapshot):
                raise OSError("synthetic finalization storage failure")

        manager = self.manager("failed-finalization", history_factory=FailingHistory)
        handle = manager.start(Plan("failure-command"))
        self.assertIsNone(await asyncio.wait_for(handle.task, 10))
        self.assertEqual(handle.state, "finalizing_failed")
        self.assertEqual(handle.error_code, "FINALIZATION_FAILED")
        self.assertIsNone(handle.result)
        self.assertEqual(manager.history.list(), [])
        self.assertFalse((handle.output / "final.json").exists())

    async def test_repeated_finalize_is_immutable_and_history_has_one_entry(self):
        handle, result = await self.completed()
        path = handle.output / "final.json"
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.supervisor.history.finalize(deepcopy(result), handle.output, handle.contract)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual(self.supervisor.history.list(), [result])
        modified = deepcopy(result)
        modified["reason_code"] = "SYNTHETIC_CHANGED_FINAL"
        with self.assertRaises(ContractError):
            self.supervisor.history.finalize(modified, handle.output, handle.contract)
        self.assertEqual(path.read_bytes(), before[0])

    async def test_reason_cannot_be_absent_empty_or_whitespace(self):
        handle, result = await self.completed((Item("synthetic-unknown", "inconclusive"),))
        for field in ("reason", "reason_code"):
            for value in (None, "", " \t\n"):
                with self.subTest(field=field, value=value):
                    modified = deepcopy(result)
                    modified["items"][0][field] = value
                    with self.assertRaises(ValueError):
                        self.validate(handle, modified)

    async def test_evidence_free_pass_and_dropped_namespaced_evidence_are_rejected(self):
        handle, result = await self.completed()
        modified = deepcopy(result)
        modified["items"][0]["p3"] = None
        modified["items"][0]["evidence_refs"] = []
        with self.assertRaises(ContractError):
            self.validate(handle, modified)
        modified = deepcopy(result)
        modified["items"][0]["evidence_refs"] = []
        with self.assertRaises(ContractError):
            self.validate(handle, modified)

    async def test_final_marker_and_visible_scope_status_match_verified_result(self):
        handle, result = await self.completed()
        for field, value in (("execution_status", "not_run"), ("tested_scope", []),
                             ("cleanup_status", "failed"), ("verdict_label", "취약")):
            with self.subTest(field=field):
                modified = deepcopy(result)
                modified["items"][0][field] = value
                with self.assertRaises(ValueError):
                    self.validate(handle, modified)
        modified = deepcopy(result)
        modified["finalized"] = False
        with self.assertRaises(ContractError):
            self.validate(handle, modified)

    async def test_completed_inconclusive_requires_its_actual_verified_p3_bundle(self):
        handle, result = await self.completed((Item("synthetic-unknown", "inconclusive"),))
        modified = deepcopy(result)
        modified["items"][0]["p3"] = None
        modified["items"][0]["evidence_refs"] = []
        with self.assertRaises(ContractError):
            self.validate(handle, modified)

    async def test_verified_bundles_cannot_be_swapped_between_selected_items(self):
        handle, result = await self.completed((Item("synthetic-pass", "pass"),
                                              Item("synthetic-fail", "fail")))
        modified = deepcopy(result)
        modified["items"].reverse()
        for item_id, row in zip(modified["selected_item_ids"], modified["items"]):
            row["item_id"] = item_id
        with self.assertRaises(ContractError):
            self.validate(handle, modified)

    async def test_foreign_run_and_session_cannot_be_grafted_into_final_result(self):
        handle, result = await self.completed()
        for field in ("run_id", "session_id"):
            for level in ("row", "p2", "p3"):
                with self.subTest(field=field, level=level):
                    modified = deepcopy(result)
                    target = (modified["items"][0] if level == "row" else modified["p2"]
                              if level == "p2" else modified["items"][0]["p3"])
                    target[field] = "synthetic-foreign-reference"
                    with self.assertRaises(ValueError):
                        self.validate(handle, modified)

    async def test_selection_and_verdict_counts_match_the_immutable_run(self):
        handle, result = await self.completed((Item("synthetic-pass", "pass"),
                                              Item("synthetic-fail", "fail")))
        alterations = []
        changed = deepcopy(result)
        changed["selected_item_ids"].reverse()
        alterations.append(changed)
        changed = deepcopy(result)
        changed["verdict_counts"]["pass"] += 1
        alterations.append(changed)
        changed = deepcopy(result)
        changed["items"] = changed["items"][:1]
        changed["selected_item_ids"] = changed["selected_item_ids"][:1]
        changed["verdict_counts"] = {"pass": 1, "fail": 0, "inconclusive": 0}
        alterations.append(changed)
        changed = deepcopy(result)
        changed["items"] = []
        changed["selected_item_ids"] = []
        changed["verdict_counts"] = {"pass": 0, "fail": 0, "inconclusive": 0}
        alterations.append(changed)
        for index, modified in enumerate(alterations):
            with self.subTest(alteration=index):
                with self.assertRaises(ContractError):
                    self.validate(handle, modified)

    async def test_valid_p3_bundle_outside_run_and_symlink_escape_are_rejected(self):
        handle, result = await self.completed()
        original = Path(result["items"][0]["p3"]["bundle"])
        outside = self.root / "outside-p3"
        shutil.copytree(original, outside)
        link = handle.output / "synthetic-external-bundle"
        link.symlink_to(outside, target_is_directory=True)
        for path in (outside, link):
            with self.subTest(path=path.name):
                modified = deepcopy(result)
                row = modified["items"][0]
                report = row["p3"]
                report["bundle"] = str(path)
                report["evidence_refs"] = [
                    f"{report['attempt_id']}:{path}#{ref}" for ref in report["result"]["evidence_refs"]]
                row["evidence_refs"] = list(report["evidence_refs"])
                with self.assertRaisesRegex(ContractError, "EVIDENCE_OUTSIDE_RUN"):
                    self.validate(handle, modified)

    async def test_valid_p2_database_outside_run_is_rejected(self):
        handle, result = await self.completed()
        outside = self.root / "outside-packets"
        outside.mkdir()
        copied = outside / "p2.sqlite"
        shutil.copy2(result["p2"]["db"], copied)
        modified = deepcopy(result)
        modified["p2"]["db"] = str(copied)
        with self.assertRaisesRegex(ContractError, "PACKETS_OUTSIDE_RUN"):
            self.validate(handle, modified)

    async def test_missing_p3_blob_invalidates_final_and_history(self):
        handle, result = await self.completed()
        bundle = Path(result["items"][0]["p3"]["bundle"])
        next((bundle / "blobs").iterdir()).unlink()
        with self.assertRaises(ValueError):
            self.validate(handle, result)
        with self.assertRaises(ValueError):
            self.supervisor.history.list()

    async def test_disk_final_tampering_is_rejected_by_history(self):
        handle, result = await self.completed()
        modified = deepcopy(result)
        modified["reason_code"] = "SYNTHETIC_DISK_TAMPERING"
        (handle.output / "final.json").write_text(json.dumps(modified), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "FINAL_INTEGRITY_ERROR"):
            self.supervisor.history.list()


if __name__ == "__main__":
    unittest.main()
