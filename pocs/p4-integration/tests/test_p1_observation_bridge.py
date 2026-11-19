"""Actual P1 Engine/CombinedRun/ReplayQueue, fake device and network command peer."""
import asyncio,copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
import test_artifact_reader  # Existing source-path setup, no device execution.
from test_live_relay_handoff import p1_fixture
from pc.core import Engine
from pc.combined import CombinedRun
from pc.replay_queue import ReplayQueue
from pc import protocol
from integration.observation_poc import Checkpoint,Plan,ObservationPOC,FakeReview,SyntheticDeviceSlot
from integration.p1_observation_bridge import P1ObservationBridge,bound_route


class P1ObservationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.engine=Engine(p1_fixture.Fake(),self.root/'p1')
        self.routes=[]
        for _ in range(2):
            self.engine.a=p1_fixture.Fake();self.engine.start()
            self.engine.record_action(p1_fixture.tap());self.engine.finish()
            self.routes.append(copy.deepcopy(self.engine.record))
        self.original={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.network=Mock()
        self.network.command.side_effect=lambda name,**kw: {'recording_id':kw['recording_id']} if name=='RECORD' else {'network_coverage':'complete_for_supported_scope'}
        self.queue=ReplayQueue(CombinedRun(self.engine,self.network,self.root/'combined'),self.root/'queues')
        self.queue.prepare=lambda i,r:setattr(self.engine,'a',p1_fixture.Fake())
        bound=tuple(bound_route(r,i) for i,r in enumerate(self.routes))
        cps=tuple(Checkpoint(phase,'check-one',r.recording_id,r.version,r.content_hash,r.occurrence,
                            r.steps[0],phase,'QA_READY' if phase=='before_dispatch' else 'QA_SENT')
                  for r in bound for phase in ('before_dispatch','after_postcondition'))
        self.plan=Plan(bound,cps,review_timeout=0.7)
        self.owner=ObservationPOC(self.root/'observations',self.plan,self.plan.content_hash,SyntheticDeviceSlot(),FakeReview(delay=1))
        self.reads=[]

    def read_state(self,adapter):
        state=adapter.values[protocol.PREFIX+'screen_state']
        value={'login':'QA_READY','menu':'QA_SENT'}.get(state,'QA_OTHER')
        self.reads.append((value,len(adapter.inputs)))
        return value

    def assert_clean(self):
        self.assertFalse(self.queue.running);self.assertFalse(self.queue.guard.locked())
        self.assertFalse(self.owner.slot.busy);self.assertIsNone(self.engine.replay_observer)
        self.assertTrue(all(p.read_bytes()==value for p,value in self.original.items()))

    async def test_real_engine_queue_timing_attribution_and_review_nonblocking(self):
        bridge=P1ObservationBridge(self.owner,self.queue,self.read_state)
        task=asyncio.create_task(bridge.run(self.routes))
        for _ in range(200):
            if self.owner.phase=='review_pending':break
            await asyncio.sleep(.002)
        self.assertEqual(self.owner.phase,'review_pending')
        self.assertFalse(task.done());self.assertFalse((self.owner.root/'result.json').exists())
        self.assertEqual(bridge.result['status'],'succeeded')
        self.assertEqual([e['source_recording_id'] for e in bridge.result['entries']],
                         [r['recording_id'] for r in self.routes])
        self.assertEqual(self.reads,[('QA_READY',0),('QA_SENT',1)]*2)
        self.assertEqual([c.args[0] for c in self.network.command.call_args_list],['RECORD','STOP']*2)
        self.assert_clean()
        result=await task
        self.assertEqual(result['checks']['check-one']['routes_with_evidence'],2)
        self.assertTrue(all(r['review']=='REVIEW_TIMEOUT' for r in result['rows']))
        self.assertEqual(len(self.owner.snapshots),4)
        self.assertTrue(all(s.observed_state in ('QA_READY','QA_SENT') for s in self.owner.snapshots.values()))

    async def test_observation_mismatch_does_not_fail_normal_p1_replay(self):
        def mismatch(adapter):
            value=self.read_state(adapter)
            return 'QA_OTHER' if len(self.reads)==2 else value
        bridge=P1ObservationBridge(self.owner,self.queue,mismatch)
        result=await bridge.run(self.routes)
        self.assertEqual(bridge.result['status'],'succeeded')
        self.assertEqual(result['rows'][1]['collection'],'STATE_MISMATCH')
        self.assertEqual(result['checks']['check-one']['routes_with_evidence'],1)
        self.assertEqual(result['checks']['check-one']['routes_expected'],2)
        self.assert_clean()

    async def test_cancel_after_first_input_keeps_snapshot_and_never_dispatches_second_route(self):
        bridge=None
        def cancel_after_input(adapter):
            value=self.read_state(adapter)
            if len(adapter.inputs):bridge.cancel()
            return value
        bridge=P1ObservationBridge(self.owner,self.queue,cancel_after_input)
        result=await bridge.run(self.routes)
        self.assertEqual(bridge.result['status'],'cancelled')
        self.assertEqual(bridge.result['entries'][1]['status'],'not_run')
        self.assertEqual(len(self.reads),2)
        self.assertEqual([c.args[0] for c in self.network.command.call_args_list],['RECORD','STOP'])
        self.assertEqual([r['collection'] for r in result['rows']],['SEALED','SEALED','STEP_NOT_REACHED','STEP_NOT_REACHED'])
        self.assertTrue(all((self.owner.root/r['evidence_ref']).exists() for r in result['rows'] if r['evidence_ref']))
        self.assert_clean()

    async def test_source_mutation_rejected_before_queue_and_host_error_stops_before_input(self):
        altered=copy.deepcopy(self.routes);altered[0]['actions'][0]['action']['timeout']=2
        bridge=P1ObservationBridge(self.owner,self.queue,self.read_state)
        with self.assertRaisesRegex(ValueError,'SOURCE_VERSION'):
            await bridge.run(altered)
        self.network.command.assert_not_called()
        def broken(adapter):raise OSError('synthetic acquisition unavailable')
        bridge=P1ObservationBridge(self.owner,self.queue,broken)
        result=await bridge.run(self.routes)
        self.assertEqual(bridge.result['status'],'partial')
        self.assertEqual(bridge.result['entries'][1]['status'],'not_run')
        self.assertEqual(self.engine.a.inputs,[])
        self.assertEqual(result['replay_status'],'failed')
        self.assertEqual(result['rows'][0]['reason'],'HOST_ACQUISITION_ERROR')
        self.assertEqual(result['rows'][0]['collection'],'EVIDENCE_INSUFFICIENT')
        self.assertTrue(all(r['collection']=='STEP_NOT_REACHED' for r in result['rows'][1:]))
        self.assert_clean()


if __name__=='__main__':unittest.main()
