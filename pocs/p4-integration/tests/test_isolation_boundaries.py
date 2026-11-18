"""Cooperative simulations only: no remote cancellation claim."""
import asyncio
from pathlib import Path
import tempfile
import unittest

from integration.contracts import Item, Plan
from integration.providers import FakeProvider
from integration.supervisor import Supervisor


class IsolationBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_ignoring_cancel_is_bounded_and_blocks_restart(self):
        release = asyncio.Event()

        class StubbornStream(FakeProvider):
            async def stream_events(self, job_id):
                while not release.is_set():
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        pass
                if False:
                    yield {}

        with tempfile.TemporaryDirectory() as folder:
            manager = Supervisor(folder, provider_factory=StubbornStream)
            successor = None
            try:
                h = manager.start(Plan('stubborn-stream', cancel_grace=0.02))
                await asyncio.wait_for(asyncio.shield(h.task), 5)
                self.assertEqual(h.state, 'failed')
                self.assertFalse(h.result['cleanup']['terminated'])
                self.assertTrue(h.result['recovery_required'])
                before = (h.output/'final.json').read_bytes()
                successor = Supervisor(folder)
                retry = successor.start(Plan('new-process-retry'))
                await asyncio.wait_for(retry.task, 5)
                self.assertEqual(retry.result['reason_code'], 'DEVICE_BUSY_OR_RECOVERY_REQUIRED')
                release.set()
                await asyncio.gather(*h.streams)
                self.assertEqual((h.output/'final.json').read_bytes(), before)
                self.assertEqual(manager.lease.inspect()['lifecycle'], 'recovery_required')
            finally:
                release.set()
                await manager.close()
                if successor:
                    await successor.close()

    async def test_stream_exception_is_not_silently_successful_or_logged_raw(self):
        class BrokenStream(FakeProvider):
            async def stream_events(self, job_id):
                raise RuntimeError('PRIVATE_MODEL_TEXT_SENTINEL')
                yield {}

        with tempfile.TemporaryDirectory() as folder:
            manager = Supervisor(folder, provider_factory=BrokenStream)
            try:
                h = manager.start(Plan('broken-stream'))
                await asyncio.wait_for(h.task, 5)
                self.assertEqual(h.state, 'failed')
                self.assertEqual(h.result['cleanup']['reason_code'], 'PROVIDER_STREAM_ERROR')
                self.assertFalse(any(e['type'] == 'tool_started' for e in h.events))
                self.assertTrue(h.result['recovery_required'])
                self.assertNotIn('PRIVATE_MODEL_TEXT_SENTINEL', (h.output/'events.jsonl').read_text(encoding='utf-8'))
            finally:
                await manager.close()

    async def test_mismatched_cancel_ack_cannot_release_lease(self):
        class WrongAck(FakeProvider):
            async def cancel(self, job_id):
                await super().cancel(job_id)
                return {'job_id': 'another-job', 'cancel_requested': True}

        with tempfile.TemporaryDirectory() as folder:
            manager = Supervisor(folder, provider_factory=WrongAck)
            try:
                h = manager.start(Plan('wrong-ack', items=(Item('first', provider_behavior='hang'),), progress_timeout=10))
                async with asyncio.timeout(5):
                    while not any(e['type']=='provider_started' and e['item_id']=='first' for e in h.events):
                        await asyncio.sleep(0.005)
                manager.cancel(h.run_id)
                await asyncio.wait_for(h.task, 5)
                self.assertTrue(h.result['cleanup']['terminated'])
                self.assertEqual(h.result['cleanup']['provider_cancel_status'], 'failed')
                self.assertEqual(h.result['cleanup']['cancellation_scope'], 'local_cooperative_only')
                self.assertEqual(manager.lease.inspect()['lifecycle'], 'recovery_required')
            finally:
                await manager.close()
