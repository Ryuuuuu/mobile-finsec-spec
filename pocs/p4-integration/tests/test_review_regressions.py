"""Regression evidence from the independent ownership/finalization review."""

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration.contracts import Item, Plan
from integration.providers import FakeProvider
from integration.supervisor import Supervisor


async def wait_event(handle, predicate):
    async def poll():
        while True:
            for event in handle.events:
                if predicate(event):
                    return event
            if handle.task.done():
                raise AssertionError(f"run ended before expected event: {handle.state}")
            await asyncio.sleep(0.005)
    return await asyncio.wait_for(poll(), timeout=5)


class ReviewRegressions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def manager(self, **kwargs):
        manager = Supervisor(Path(self.temp.name), **kwargs)
        self.addAsyncCleanup(manager.close)
        return manager

    async def test_cancel_rpc_hang_is_bounded_and_workers_are_joined(self):
        class SlowCancel(FakeProvider):
            async def cancel(self, job_id):
                await asyncio.Event().wait()

        manager = self.manager(provider_factory=SlowCancel)
        handle = manager.start(Plan('cancel-rpc-hang', items=(Item('first', provider_behavior='hang'),),
                                    progress_timeout=10, cancel_grace=0.02))
        await wait_event(handle, lambda e: e['type'] == 'provider_started' and e['item_id'] == 'first')
        manager.cancel(handle.run_id)
        await asyncio.wait_for(handle.task, timeout=2)
        self.assertEqual(handle.state, 'cancelled')
        self.assertTrue(handle.result['cleanup']['terminated'])
        self.assertTrue(all(f.done() for f in handle.resources))
        self.assertEqual(manager.lease.inspect()['lifecycle'], 'free')

    async def test_cancel_rpc_error_preserves_quarantine_after_forced_stop(self):
        class BrokenCancel(FakeProvider):
            async def cancel(self, job_id):
                raise RuntimeError('synthetic cancel error')

        manager = self.manager(provider_factory=BrokenCancel)
        handle = manager.start(Plan('cancel-rpc-error', items=(Item('first', provider_behavior='hang'),),
                                    progress_timeout=10, cancel_grace=0.02))
        await wait_event(handle, lambda e: e['type'] == 'provider_started' and e['item_id'] == 'first')
        manager.cancel(handle.run_id)
        await asyncio.wait_for(handle.task, timeout=2)
        self.assertEqual(handle.state, 'cancelled')
        self.assertEqual(handle.result['cleanup']['reason_code'], 'PROVIDER_CANCEL_ERROR')
        self.assertTrue(handle.result['recovery_required'])
        self.assertEqual(manager.lease.inspect()['lifecycle'], 'recovery_required')

    async def test_direct_supervisor_task_cancel_never_publishes_completed(self):
        manager = self.manager()
        handle = manager.start(Plan("task-cancel", items=(
            Item("first", provider_behavior="hang"), Item("never-started")),
            progress_timeout=10))
        await wait_event(handle, lambda e: e["type"] == "provider_started"
                         and e["payload"]["role"] == "item")
        handle.task.cancel()
        await handle.task
        self.assertEqual(handle.state, "cancelled")
        self.assertEqual(handle.result["execution_status"], "cancelled")
        self.assertEqual(handle.result["reason_code"], "SUPERVISOR_CANCELLED")
        self.assertEqual([row["execution_status"] for row in handle.result["items"]],
                         ["cancelled", "not_run"])
        self.assertTrue(handle.result["cleanup"]["terminated"])
        self.assertEqual(manager.lease.inspect()["lifecycle"], "free")
        self.assertEqual(manager.history.list()[0]["execution_status"], "cancelled")
        following = manager.start(Plan("after-task-cancel"))
        await following.task
        self.assertEqual(following.state, "completed")

    async def test_prior_item_delayed_event_cannot_borrow_current_generation(self):
        release_event = asyncio.Event()
        delivered = asyncio.Event()

        class DelayedEventsProvider(FakeProvider):
            async def start_job(self, context, tool_catalog):
                self.item_id = context.get("item_id")
                return await super().start_job(context, tool_catalog)

            async def stream_events(self, job_id):
                async for event in super().stream_events(job_id):
                    if self.item_id == "first" and event["type"] == "finished":
                        await release_event.wait()
                        yield event
                        delivered.set()
                    else:
                        yield event

        manager = self.manager(provider_factory=DelayedEventsProvider)
        handle = manager.start(Plan("late-event", items=(Item("first"),
            Item("second", provider_behavior="hang")), progress_timeout=10))
        second = await wait_event(handle, lambda e: e["type"] == "item_running"
                                  and e["item_id"] == "second")
        release_event.set()
        await asyncio.wait_for(delivered.wait(), timeout=1)
        stale_events = [event for event in handle.events
                        if event["seq"] > second["seq"]
                        and event["item_id"] == "first"
                        and event["type"] == "provider_event"]
        self.assertEqual(stale_events, [])
        manager.cancel(handle.run_id)
        await handle.task
        self.assertEqual(handle.result["items"][0]["verdict"], "pass")
        self.assertEqual(handle.result["items"][1]["execution_status"], "cancelled")

    async def test_unexpected_cleanup_storage_error_retains_ownership_and_history(self):
        manager = self.manager()
        original = manager.lease.begin_cleanup
        injected = False

        def fail_once_at_run_cleanup(token):
            nonlocal injected
            # Per-item cleanup succeeds; the final run cleanup loses storage once.
            if not token.attempt_id and not injected:
                injected = True
                raise OSError("SYNTHETIC_LEASE_WRITE_FAILURE")
            return original(token)

        with patch.object(manager.lease, "begin_cleanup", side_effect=fail_once_at_run_cleanup):
            handle = manager.start(Plan("cleanup-exception"))
            await handle.task
        self.addAsyncCleanup(handle.p2.cleanup)
        self.assertTrue(injected)
        self.assertEqual(handle.state, "failed")
        self.assertEqual(handle.result["cleanup"]["reason_code"], "CLEANUP_EXCEPTION")
        self.assertEqual(handle.result["cleanup_status"], "unknown")
        self.assertTrue(handle.result["recovery_required"])
        self.assertEqual(handle.result["items"][0]["verdict"], "pass")
        self.assertEqual(manager.lease.inspect()["lifecycle"], "recovery_required")
        self.assertEqual(manager.history.list()[0]["run_id"], handle.run_id)
        following = manager.start(Plan("blocked-after-cleanup-exception"))
        await following.task
        self.assertEqual(following.result["reason_code"], "DEVICE_BUSY_OR_RECOVERY_REQUIRED")
        self.assertEqual(following.result["items"][0]["execution_status"], "not_run")


if __name__ == "__main__":
    unittest.main()
