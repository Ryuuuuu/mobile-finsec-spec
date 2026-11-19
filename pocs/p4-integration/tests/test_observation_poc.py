import asyncio
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration.observation_poc import (Checkpoint, FakeReview, ObservationPOC,
    Plan, Route, Scene, Snapshot, SyntheticDeviceSlot)


def fixture():
    routes = (Route('route-a','v1',0,('tap',)), Route('route-b','v1',0,('tap',)))
    cps = tuple(Checkpoint('observe','check-one',r.recording_id,r.version,r.content_hash,
                          r.occurrence,'tap','after_postcondition','QA_SENT') for r in routes)
    return Plan(routes,cps), {(r.recording_id,0,'tap'):Scene() for r in routes}


class ObservationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan, self.scenes = fixture()
        self.slot = SyntheticDeviceSlot()

    def owner(self, plan=None, review=FakeReview()):
        plan = plan or self.plan
        return ObservationPOC(self.root,plan,plan.content_hash,self.slot,review)

    async def test_two_routes_separate_immutable_evidence_and_sequential_input(self):
        owner=self.owner(); result=await owner.run(self.scenes)
        self.assertEqual(result['checks']['check-one']['routes_with_evidence'],2)
        self.assertEqual(result['checks']['check-one']['routes_expected'],2)
        inputs=[e for e in owner.events if e['event']=='synthetic_input']
        self.assertEqual([e['recording_id'] for e in inputs],['route-a','route-b'])
        self.assertEqual(len(set(r['evidence_ref'] for r in result['rows'])),2)
        self.assertTrue(all(r['verdict']=='inconclusive' and not r['enforcement_verified'] for r in result['rows']))
        self.assertEqual(json.loads((owner.root/'result.json').read_text()),result)
        with self.assertRaises(FrozenInstanceError):
            next(iter(owner.snapshots.values())).observed_state='QA_OTHER'

    async def test_duplicate_event_vs_new_attempt_and_late_result(self):
        owner=self.owner(); result=await owner.run(self.scenes)
        before={p:p.read_bytes() for p in (owner.root/'evidence').iterdir()}
        snapshot=next(iter(owner.snapshots.values()))
        self.assertFalse(owner.seal(snapshot.key,snapshot.observed_state))
        with self.assertRaisesRegex(ValueError,'CONFLICT'):
            owner.seal(snapshot.key,'QA_OTHER')
        with self.assertRaisesRegex(ValueError,'SCOPE'):
            owner.accept_review(Snapshot('foreign','QA_SENT','hash'),'OBSERVATION_ONLY')
        finalbytes=(owner.root/'result.json').read_bytes()
        self.assertFalse(owner.accept_review(snapshot,'OBSERVATION_ONLY'))
        self.assertEqual((owner.root/'result.json').read_bytes(),finalbytes)
        retry=self.owner(); await retry.run(self.scenes)
        self.assertNotEqual(owner.attempt_id,retry.attempt_id)
        self.assertTrue(set(owner.snapshots).isdisjoint(retry.snapshots))
        self.assertTrue(all(p.read_bytes()==data for p,data in before.items()))

    async def test_repeat_same_route_keeps_content_hash_but_distinct_occurrence(self):
        first=self.plan.routes[0]; second=replace(first,occurrence=1)
        self.assertEqual(first.content_hash,second.content_hash)
        cp=self.plan.checkpoints[0]
        plan=replace(self.plan,routes=(first,second),checkpoints=(cp,replace(cp,occurrence=1)))
        scenes={('route-a',n,'tap'):Scene() for n in (0,1)}
        owner=self.owner(plan); result=await owner.run(scenes)
        self.assertEqual(len(owner.snapshots),2)
        self.assertEqual(result['checks']['check-one']['routes_expected'],2)
        self.assertEqual([e['occurrence'] for e in owner.events if e['event']=='route_started'],[0,1])

    async def test_missing_evidence_keeps_one_of_two_coverage(self):
        self.scenes['route-b',0,'tap']=Scene(missing=True)
        result=await self.owner().run(self.scenes)
        self.assertEqual(result['checks']['check-one']['routes_with_evidence'],1)
        self.assertEqual(result['checks']['check-one']['routes_expected'],2)
        self.assertEqual(result['rows'][1]['reason'],'EVIDENCE_INSUFFICIENT')
        self.assertEqual(result['replay_status'],'completed')

    async def test_repeat_missing_second_occurrence_and_redelivery(self):
        first=self.plan.routes[0]; cp=self.plan.checkpoints[0]
        plan=replace(self.plan,routes=(first,replace(first,occurrence=1)),
                     checkpoints=(cp,replace(cp,occurrence=1)))
        owner=self.owner(plan)
        result=await owner.run({('route-a',0,'tap'):Scene(),
                                ('route-a',1,'tap'):Scene(missing=True)})
        self.assertEqual(result['checks']['check-one']['routes_with_evidence'],1)
        self.assertEqual(result['checks']['check-one']['routes_expected'],2)
        self.assertEqual([r['collection'] for r in result['rows']],
                         ['SEALED','EVIDENCE_INSUFFICIENT'])
        snapshot=next(iter(owner.snapshots.values()))
        saved=(owner.root/'result.json').read_bytes()
        self.assertFalse(owner.seal(snapshot.key,snapshot.observed_state))
        self.assertEqual(len(owner.snapshots),1)
        self.assertEqual((owner.root/'result.json').read_bytes(),saved)

    async def test_mismatch_not_reached_and_input_failure_are_distinct(self):
        self.scenes['route-a',0,'tap']=Scene(after='QA_OTHER')
        result=await self.owner().run(self.scenes)
        self.assertEqual(result['rows'][0]['collection'],'STATE_MISMATCH')
        self.assertEqual(result['rows'][1]['collection'],'SEALED')
        self.scenes['route-a',0,'tap']=Scene(input_failed=True)
        owner=self.owner(); result=await owner.run(self.scenes)
        self.assertEqual(result['replay_status'],'failed')
        self.assertTrue(all(r['collection']=='STEP_NOT_REACHED' for r in result['rows']))
        self.assertEqual(len([e for e in owner.events if e['event']=='synthetic_input']),1)

    async def test_review_delay_never_blocks_second_input_or_holds_device(self):
        plan=replace(self.plan,review_timeout=0.15)
        owner=self.owner(plan,FakeReview(delay=1))
        task=asyncio.create_task(owner.run(self.scenes))
        for _ in range(200):
            if owner.phase=='review_pending':break
            await asyncio.sleep(0.001)
        self.assertEqual(owner.phase,'review_pending')
        self.assertFalse(task.done()); self.assertIsNone(owner.final)
        self.assertFalse((owner.root/'result.json').exists())
        self.assertFalse(self.slot.busy)
        self.assertEqual([e['recording_id'] for e in owner.events if e['event']=='synthetic_input'],['route-a','route-b'])
        result=await task
        self.assertTrue(all(r['review']=='REVIEW_TIMEOUT' for r in result['rows']))
        self.assertEqual(result['replay_status'],'completed')

    async def test_before_snapshot_precedes_input_and_capture_timeout_is_gap(self):
        cps=tuple(replace(c,phase='before_dispatch',expected='QA_READY') for c in self.plan.checkpoints)
        owner=self.owner(replace(self.plan,checkpoints=cps))
        await owner.run(self.scenes)
        ev=[e['event'] for e in owner.events]
        self.assertLess(ev.index('evidence_sealed'),ev.index('synthetic_input'))
        self.scenes['route-a',0,'tap']=Scene(capture_delay=0.1)
        result=await self.owner().run(self.scenes)
        self.assertEqual(result['rows'][0]['collection'],'CAPTURE_TIMEOUT')
        self.assertEqual(result['rows'][1]['collection'],'SEALED')

    async def test_cancel_preserves_sealed_evidence_and_stops_following_route(self):
        # Three checkpoints create a scheduling point after the first sealed one.
        c=self.plan.checkpoints[0]
        extra=replace(c,checkpoint_id='second-before',phase='before_dispatch',expected='QA_READY')
        plan=replace(self.plan,checkpoints=(extra,*self.plan.checkpoints),capture_timeout=0.1)
        self.scenes['route-a',0,'tap']=Scene(capture_delay=0.02)
        owner=self.owner(plan,FakeReview(delay=1))
        task=asyncio.create_task(owner.run(self.scenes))
        for _ in range(100):
            if owner.snapshots:break
            await asyncio.sleep(0.001)
        self.assertTrue(owner.snapshots)
        owner.cancel.set()
        result=await task
        self.assertEqual(result['replay_status'],'cancelled')
        self.assertFalse(any(e['event']=='route_started' and e['recording_id']=='route-b' for e in owner.events))
        self.assertTrue(all((owner.root/s['evidence_ref']).exists() for s in result['rows'] if s['evidence_ref']))
        self.assertIn('REVIEW_CANCELLED',[r['review'] for r in result['rows']])
        self.assertFalse(self.slot.busy)

    async def test_no_secret_raw_data_is_retained_and_real_reviewer_unavailable(self):
        self.scenes['route-a',0,'tap']=Scene(after='PRIVATE_MARKER_PASSWORD')
        owner=self.owner(); result=await owner.run(self.scenes)
        self.assertEqual(result['rows'][0]['collection'],'EVIDENCE_PRIVACY_EXCLUDED')
        self.assertTrue(all(b'PRIVATE_MARKER_PASSWORD' not in p.read_bytes() for p in owner.root.rglob('*') if p.is_file()))
        with self.assertRaisesRegex(ValueError,'UNAVAILABLE'):
            self.owner(review=lambda:None)
        self.assertEqual(result['real_reviewer'],'unavailable')

    async def test_changed_plan_and_route_versions_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError,'APPROVAL'):
            ObservationPOC(self.root,self.plan,'old-hash',self.slot)
        plan=replace(self.plan,checkpoints=(replace(self.plan.checkpoints[0],route_version='v2'),))
        with self.assertRaisesRegex(ValueError,'ROUTE_MISMATCH'):self.owner(plan)
        self.assertFalse(self.slot.busy)

    async def test_single_device_busy_then_explicit_new_run(self):
        self.scenes['route-a',0,'tap']=Scene(capture_delay=0.015)
        first=self.owner(); task=asyncio.create_task(first.run(self.scenes))
        await asyncio.sleep(0)
        with self.assertRaisesRegex(RuntimeError,'BUSY'):
            await self.owner().run(self.scenes)
        await task
        with self.assertRaisesRegex(RuntimeError,'ALREADY'):
            await first.run(self.scenes)
        self.assertEqual((await self.owner().run(self.scenes))['replay_status'],'completed')

    async def test_storage_failure_never_publishes_final_success_and_releases_mock_slot(self):
        owner=self.owner(); original=Path.open
        def fail(path,*args,**kwargs):
            if path.name=='events.jsonl':raise OSError('synthetic storage unavailable')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',fail),self.assertRaises(OSError):
            await owner.run(self.scenes)
        self.assertEqual(owner.phase,'finalizing_failed')
        self.assertIsNone(owner.final);self.assertFalse(self.slot.busy)
        self.assertFalse((owner.root/'result.json').exists())

    async def test_review_error_is_separate_from_replay_and_final_save_failure(self):
        owner=self.owner(review=FakeReview(error=True))
        result=await owner.run(self.scenes)
        self.assertEqual(result['replay_status'],'completed')
        self.assertTrue(all(r['review']=='REVIEW_ERROR' for r in result['rows']))
        owner=self.owner()
        with patch('integration.observation_poc.os.replace',side_effect=OSError('synthetic write failure')):
            with self.assertRaises(OSError):await owner.run(self.scenes)
        self.assertEqual(owner.phase,'finalizing_failed')
        self.assertFalse((owner.root/'result.json').exists())
        self.assertIsNone(owner.final)
        self.assertFalse(self.slot.busy)


if __name__=='__main__':unittest.main()
