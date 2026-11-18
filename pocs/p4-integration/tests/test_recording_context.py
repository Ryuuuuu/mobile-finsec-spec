import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from integration.recording_context import resolve_recording
from integration.supervisor import StructureSupervisor

RID='synthetic-recording-01'
def catalog():
    return {RID:dict(recording_id=RID,app_id='dev.finsec.synthetic',
        route=dict(recording_id=RID,ref_id='synthetic-p1-route',status='complete',count=3),
        packets=dict(recording_id=RID,ref_id='synthetic-p2-packets',status='complete',count=0))}

class ReferenceTests(unittest.TestCase):
    def test_unselected_launch_default_not_missing_record_fallback(self):
        none=resolve_recording(None,{})
        self.assertEqual(none['mode'],'app_launch_default')
        self.assertEqual(none['actions'],[{'operation':'app.launch','app_id':'dev.finsec.synthetic'}])
        missing=resolve_recording(RID,{})
        self.assertEqual(missing['mode'],'recording_unavailable');self.assertEqual(missing['actions'],[])
    def test_complete_zero_packets_not_missing(self):
        r=resolve_recording(RID,catalog())
        self.assertEqual(r['collection_status'],'complete')
        self.assertEqual(r['packets']['count'],0)
        self.assertEqual(r['mode'],'recorded_route')
    def test_partial_and_missing_both_channels(self):
        for kind in ('route','packets'):
            for status in ('partial','missing','not_collected'):
                c=catalog();v=c[RID][kind];v['status']=status
                if status!='partial':v.update(ref_id=None,count=None)
                r=resolve_recording(RID,c)
                self.assertEqual(r[kind]['status'],status)
                self.assertEqual(r['collection_status'],'incomplete')
                if kind=='route':self.assertEqual(r['mode'],'route_unavailable')
    def test_foreign_record_or_payload_rejected(self):
        for mutate in (lambda c:c[RID]['packets'].update(recording_id='synthetic-other'),
                       lambda c:c[RID].update(app_id='different.app'),
                       lambda c:c[RID]['route'].update(raw_text='PRIVATE'),
                       lambda c:c[RID]['route'].update(count=True)):
            c=catalog();mutate(c)
            with self.assertRaises(ValueError):resolve_recording(RID,c)
    def test_empty_route_and_snapshot_isolation(self):
        c=catalog();c[RID]['route']['count']=0
        r=resolve_recording(RID,c);c[RID]['route']['status']='missing'
        self.assertEqual(r['mode'],'recorded_route_empty')
        self.assertEqual(r['route']['status'],'complete')

class HandoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_sequential_selected_only_detached_delivery_and_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);skills=root/'skills';seen=[]
            for item in ('first','second','unselected'):
                p=skills/item/'common'/'SKILL.md';p.parent.mkdir(parents=True);p.write_text('MOCK')
            class Executor:
                async def run(_,context,progress):
                    seen.append(deepcopy(context))
                    context['recording_context']['route']['count']=999
                    progress();await asyncio.sleep(.001)
                    return {'execution_status':'completed'}
            s=StructureSupervisor(root/'runs',skills,Executor())
            result=await s.run(['first','second'],recording_id=RID,recordings=catalog())
            self.assertEqual([c['item_id'] for c in seen],['first','second'])
            self.assertEqual([c['recording_context']['route']['count'] for c in seen],[3,3])
            self.assertTrue(all(c['recording_context']['packets']['recording_id']==RID for c in seen))
            saved=json.loads((root/'runs'/result['run_id']/'result.json').read_text())
            self.assertEqual(saved,result)
            self.assertEqual([r['recording_context']['route']['count'] for r in saved['items']],[3,3])
            self.assertNotIn('verdict',json.dumps(saved))
    async def test_missing_and_partial_are_context_not_execution_success_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'skills'/'first'/'common'/'SKILL.md';p.parent.mkdir(parents=True);p.write_text('MOCK')
            s=StructureSupervisor(root/'runs',root/'skills')
            variants=[(None,{},'not_selected'),(RID,{},'recording_missing')]
            partial=catalog();partial[RID]['packets']['status']='partial'
            variants.append((RID,partial,'incomplete'))
            for rid,c,status in variants:
                r=await s.run(['first'],recording_id=rid,recordings=c)
                self.assertEqual(r['execution_status'],'completed')
                self.assertEqual(r['items'][0]['recording_context']['collection_status'],status)
                self.assertNotIn('replay_completed',json.dumps(r))
