import asyncio,copy,json,sys,tempfile,unittest
from pathlib import Path
from integration.observation_stdio import ObservationAPI
from integration.observation_poc import ObservationPOC,FakeReview,SyntheticDeviceSlot,Scene,digest
from integration.observation_archive import save_completed,load_completed,LIMIT

class ArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def fixture(self,root,mode='v2'):
        api=ObservationAPI(root,mode);p=api.plan
        owner=ObservationPOC(root,p,p.content_hash,SyntheticDeviceSlot(),FakeReview())
        result=await owner.run({('route-A',0,'tap'):Scene(),('route-A',1,'tap'):Scene(missing=True)})
        save_completed(root,result,api.matching)
        return result,api.matching

    async def test_restart_child_read_only_and_binding(self):
        with tempfile.TemporaryDirectory() as root:
            result,matching=await self.fixture(root)
            child=await asyncio.create_subprocess_exec(sys.executable,'-m','integration.observation_stdio','--root',root,
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE)
            try:
                await asyncio.wait_for(child.stdout.readline(),3)
                async def request(n,op,args):
                    child.stdin.write((json.dumps(dict(contract='observation-request.v1',project_id='synthetic-observation',request_generation=n,operation=op,arguments=args))+'\n').encode());await child.stdin.drain()
                    return json.loads(await asyncio.wait_for(child.stdout.readline(),3))
                reply=await request(1,'load_completed',dict(run_id=result['run_id'],plan_hash=result['plan_hash']))
                self.assertEqual(reply['result'],result);self.assertEqual(reply['matching_report'],json.loads(json.dumps(matching)))
                self.assertEqual({r['status'] for r in reply['matching_report']['rows']},{'MATCHED','UNMATCHED','AMBIGUOUS'})
                self.assertEqual((await request(2,'status',{}))['status'],'idle')
                listed=await request(4,'history',{})
                self.assertEqual(listed['history'][0]['run_id'],result['run_id'])
                self.assertTrue(listed['history'][0]['available'])
                self.assertEqual((await request(3,'load_completed',dict(run_id=result['run_id'],plan_hash='0'*64)))['status'],'COMPLETED_REPORT_UNAVAILABLE_OR_INVALID')
                self.assertEqual(len([p for p in Path(root).iterdir() if len(p.name)==32]),1)
            finally:
                child.stdin.close();await asyncio.wait_for(child.wait(),3)

    async def test_legacy_missing_metadata_and_incomplete_rejection(self):
        with tempfile.TemporaryDirectory() as root:
            r,_=await self.fixture(root,'v1')
            reply=load_completed(root,r['run_id'],r['plan_hash'])
            self.assertIsNone(reply['matching_report']);self.assertEqual(reply['historical_detail'],'HISTORICAL_TIMING_UNAVAILABLE')
            path=Path(root)/'completed-reports'/(r['run_id']+'.json');original=path.read_bytes()
            path.unlink() # disposable fixture: exercise pre-archive result.json compatibility
            self.assertEqual(load_completed(root,r['run_id'],r['plan_hash'])['historical_detail'],'HISTORICAL_TIMING_UNAVAILABLE')
            path.write_bytes(original)
            for change in ('truncated','checksum','missing_row','coverage','oversize','missing_review'):
                e=json.loads(original)
                if change=='truncated':data=b'{'
                elif change=='oversize':data=b' '* (LIMIT+1)
                else:
                    if change=='checksum':e['checksum']='0'*64
                    if change=='missing_row':e['payload']['result']['rows'].pop();e['checksum']=digest(e['payload'])
                    if change=='coverage':e['payload']['result']['checks']['mock-check']['routes_with_evidence']=2;e['checksum']=digest(e['payload'])
                    if change=='missing_review':del e['payload']['result']['rows'][0]['review'];e['checksum']=digest(e['payload'])
                    data=json.dumps(e).encode()
                path.write_bytes(data)
                with self.subTest(change=change),self.assertRaises((ValueError,KeyError,TypeError)):load_completed(root,r['run_id'],r['plan_hash'])
            for data in (b'null',b'[]',b'{"payload":null,"checksum":"x"}'):
                path.write_bytes(data)
                api=ObservationAPI(root)
                self.assertEqual(api.operation('load_completed',dict(run_id=r['run_id'],plan_hash=r['plan_hash']))['status'],'COMPLETED_REPORT_UNAVAILABLE_OR_INVALID')
                self.assertEqual(api.operation('status',{})['status'],'idle')

    async def test_archive_write_failure_keeps_completed_result(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            api=ObservationAPI(root,'v2');h=api.plan.content_hash
            api.operation('approve',dict(plan_hash=h))
            with patch('integration.observation_stdio.FakeReview',return_value=FakeReview()),patch('integration.observation_stdio.save_completed',side_effect=OSError('synthetic disk failure')):
                api.operation('start',dict(plan_hash=h));await api.task
            self.assertEqual(api.operation('result',{})['archive_status'],'REPORT_ARCHIVE_FAILED')
            self.assertEqual(api.operation('result',{})['result']['replay_status'],'completed')
            self.assertFalse(api.slot.busy)

    async def test_timing_mismatch_and_noncompleted_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            r,m=await self.fixture(root)
            from integration.observation_archive import validate
            bad=copy.deepcopy(m);bad['rows'][1]['status']='AMBIGUOUS'
            with self.assertRaisesRegex(ValueError,'TIMING_MISMATCH'):validate(r,bad,r['run_id'],r['plan_hash'])
            r['replay_status']='cancelled'
            with self.assertRaisesRegex(ValueError,'NOT_COMPLETED'):validate(r,m,r['run_id'],r['plan_hash'])

    async def test_existing_temporary_report_is_not_removed(self):
        with tempfile.TemporaryDirectory() as root:
            r,m=await self.fixture(root)
            folder=Path(root)/'completed-reports'
            (folder/(r['run_id']+'.json')).unlink() # disposable test archive only
            temporary=folder/(r['run_id']+'.tmp');temporary.write_bytes(b'prior synthetic partial')
            with self.assertRaises(FileExistsError):save_completed(root,r,m)
            self.assertEqual(temporary.read_bytes(),b'prior synthetic partial')
