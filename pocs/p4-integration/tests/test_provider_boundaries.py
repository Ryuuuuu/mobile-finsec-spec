"""Device-free adapter RPC boundaries, sequential admission and retry policy."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from integration.contracts import Item, Plan
from integration.providers import FakeProvider
from integration.supervisor import Supervisor


class ProviderBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def run_fault(self, phase, role):
        calls = []

        class Stalled(FakeProvider):
            async def start_job(self, context, catalog):
                calls.append(('start', context['role']))
                if phase == 'start' and context['role'] == role:
                    await asyncio.Event().wait()
                return await super().start_job(context, catalog)

            async def get_result(self, job_id):
                job = self.jobs[job_id]
                calls.append(('result', job.role))
                if phase == 'result' and job.role == role:
                    await asyncio.Event().wait()
                return await super().get_result(job_id)

        with tempfile.TemporaryDirectory() as folder:
            manager = Supervisor(folder, provider_factory=Stalled)
            try:
                plan = Plan('rpc-boundary', items=(Item('first'), Item('later')),
                            tool_timeout=0.5, cancel_grace=0.02)
                h = manager.start(plan)
                await asyncio.wait_for(asyncio.shield(h.task), 5)
                self.assertEqual(h.state, 'failed')
                self.assertEqual(h.result['reason_code'], f'{role.upper()}_{phase.upper()}_TIMEOUT')
                self.assertEqual(h.result['recovery_required'], phase == 'start')
                self.assertEqual(h.rows[0]['execution_status'], 'not_run' if role == 'main' else 'timed_out')
                self.assertEqual(h.rows[1]['execution_status'], 'not_run')
                self.assertTrue(all(f.done() for f in h.resources))
                self.assertEqual(calls.count((phase, role)), 1)
                self.assertIs(manager.start(plan), h)  # no hidden retry on duplicate command
                self.assertEqual(calls.count((phase, role)), 1)
                events = [json.loads(line) for line in (h.output/'events.jsonl').read_text(encoding='utf-8').splitlines()]
                self.assertEqual([e['seq'] for e in events], list(range(1, len(events)+1)))
                self.assertTrue(any(e['type']=='provider_call_stopped' and e['payload']['phase']==phase for e in events))
                self.assertFalse(any(e['type']=='tool_started' for e in events))
                if phase == 'start':
                    retry = manager.start(Plan('explicit-new-command'))
                    await asyncio.wait_for(retry.task, 5)
                    self.assertEqual(retry.result['reason_code'], 'DEVICE_BUSY_OR_RECOVERY_REQUIRED')
            finally:
                await manager.close()

    async def test_main_start_timeout(self):
        await self.run_fault('start', 'main')

    async def test_item_start_timeout(self):
        await self.run_fault('start', 'item')

    async def test_main_result_timeout(self):
        await self.run_fault('result', 'main')

    async def test_item_result_timeout(self):
        await self.run_fault('result', 'item')

    async def test_both_fake_names_execute_main_then_items_and_persist_rpc_logs(self):
        for name in ('fake-a', 'fake-b'):
            with self.subTest(provider=name), tempfile.TemporaryDirectory() as folder:
                manager = Supervisor(folder)
                try:
                    h = manager.start(Plan('sequence', provider_name=name, items=(Item('one'),Item('two'))))
                    await asyncio.wait_for(h.task, 8)
                    self.assertEqual(h.state, 'completed')
                    calls = [(e['payload']['role'],e['payload']['phase'],e['type']) for e in h.events
                             if e['type'] in ('provider_call_started','provider_call_finished')]
                    expected = [(role,phase,kind) for role in ('main','item','item')
                                for phase in ('start','result')
                                for kind in ('provider_call_started','provider_call_finished')]
                    self.assertEqual(calls, expected)
                    disk = [json.loads(line) for line in (h.output/'events.jsonl').read_text(encoding='utf-8').splitlines()]
                    self.assertEqual(disk, h.events)
                    self.assertEqual(len(manager.history.list()), 1)
                finally:
                    await manager.close()
