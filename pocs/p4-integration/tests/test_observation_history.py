import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from integration.observation_archive import save_completed,history
from integration.observation_stdio import ObservationAPI
from integration.observation_poc import ObservationPOC,FakeReview,SyntheticDeviceSlot,Scene,digest

class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def create(self,root,revision,missing):
        api=ObservationAPI(root,'v2');api.revision=revision;api.make_plan();p=api.plan
        owner=ObservationPOC(root,p,p.content_hash,SyntheticDeviceSlot(),FakeReview())
        r=await owner.run({('route-A',0,'tap'):Scene(missing=missing),('route-A',1,'tap'):Scene(missing=True)})
        with patch('integration.observation_archive.publication_time',return_value='2026-11-19T12:00:00.000Z'):
            save_completed(root,r,api.matching)
        return r

    async def test_collision_selection_and_no_execution(self):
        with tempfile.TemporaryDirectory() as root:
            a=await self.create(root,1,False);b=await self.create(root,2,True)
            restarted=ObservationAPI(root)
            listed=restarted.operation('history',{})['history']
            self.assertEqual(len(listed),2);self.assertEqual(len({i['saved_at'] for i in listed}),1)
            self.assertEqual([i['run_id'] for i in listed],sorted([a['run_id'],b['run_id']],reverse=True))
            for original in (a,b):
                loaded=restarted.operation('load_completed',dict(run_id=original['run_id'],plan_hash=original['plan_hash']))
                self.assertEqual(loaded['result'],original)
                self.assertEqual({r['status'] for r in loaded['matching_report']['rows']},{'MATCHED','UNMATCHED','AMBIGUOUS'})
            self.assertEqual(a['checks']['before-check']['routes_with_evidence'],1)
            self.assertEqual(b['checks']['before-check']['routes_with_evidence'],0)
            self.assertIsNone(restarted.owner);self.assertIsNone(restarted.task);self.assertIsNone(restarted.approved)

    async def test_malformed_stale_selection_and_legacy_date(self):
        with tempfile.TemporaryDirectory() as root:
            r=await self.create(root,1,False);p=Path(root)/'completed-reports'/(r['run_id']+'.json')
            envelope=json.loads(p.read_bytes());envelope['payload']['contract']='synthetic-completed-report.v1';del envelope['payload']['saved_at'];envelope['checksum']=digest(envelope['payload']);p.write_text(json.dumps(envelope))
            self.assertIsNone(history(root)['history'][0]['saved_at'])
            p.write_bytes(b'{')
            self.assertFalse(history(root)['history'][0]['available'])
            api=ObservationAPI(root)
            self.assertEqual(api.operation('load_completed',dict(run_id=r['run_id'],plan_hash=r['plan_hash']))['status'],'COMPLETED_REPORT_UNAVAILABLE_OR_INVALID')
            self.assertEqual(api.operation('status',{})['status'],'idle')

    async def test_directory_bound_and_no_other_folder_scan(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'unrelated').mkdir();Path(root,'unrelated','private.json').write_text('not a fixture')
            self.assertEqual(history(root),dict(status='ok',history=[]))
            folder=Path(root,'completed-reports');folder.mkdir()
            for i in range(101):(folder/(str(i)+'.tmp')).write_text('partial')
            self.assertEqual(history(root),dict(status='HISTORY_LIMIT',history=[]))
