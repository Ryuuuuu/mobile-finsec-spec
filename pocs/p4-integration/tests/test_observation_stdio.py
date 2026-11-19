import asyncio,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from integration.observation_stdio import ObservationAPI


class ObservationAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_approval_version_pending_and_route_coverage(self):
        with tempfile.TemporaryDirectory() as root:
            api=ObservationAPI(root);v1=api.operation('preview',{})
            self.assertEqual(api.operation('start',{'plan_hash':v1['plan_hash']})['status'],'PLAN_NOT_APPROVED')
            self.assertEqual(api.operation('approve',{'plan_hash':v1['plan_hash']})['status'],'approved')
            v2=api.operation('new_version',{})
            self.assertEqual(api.operation('start',{'plan_hash':v1['plan_hash']})['status'],'PLAN_VERSION_MISMATCH')
            api.operation('approve',{'plan_hash':v2['plan_hash']})
            self.assertEqual(api.operation('start',{'plan_hash':v2['plan_hash']})['status'],'accepted')
            for _ in range(100):
                status=api.operation('status',{})
                if status.get('status')=='review_pending':break
                await asyncio.sleep(.002)
            self.assertEqual(status['replay'],'completed');self.assertFalse(status['final_available'])
            self.assertEqual(api.operation('result',{})['status'],'not_finalized')
            self.assertEqual(api.operation('new_version',{})['status'],'busy')
            await api.task
            result=api.operation('result',{})['result']
            self.assertEqual(result['checks']['mock-check']['routes_with_evidence'],1)
            self.assertEqual(result['checks']['mock-check']['routes_expected'],2)
            self.assertEqual([r['review'] for r in result['rows']],['REVIEW_TIMEOUT','NOT_REVIEWED'])
            self.assertEqual(result['rows'][1]['reason'],'EVIDENCE_INSUFFICIENT')
            await api.close()

    async def test_actual_child_preview_scope_and_eof_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            child=await asyncio.create_subprocess_exec(sys.executable,'-m','integration.observation_stdio','--root',root,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            try:
                ready=json.loads(await asyncio.wait_for(child.stdout.readline(),3))
                self.assertEqual(ready['contract'],'observation-stdio.v1')
                for gen,op,args in [(1,'preview',{})]:
                    child.stdin.write((json.dumps(dict(contract='observation-request.v1',project_id='synthetic-observation',request_generation=gen,operation=op,arguments=args))+'\n').encode())
                    await child.stdin.drain();reply=json.loads(await asyncio.wait_for(child.stdout.readline(),3))
                    self.assertEqual(reply['request_generation'],gen)
                    self.assertEqual(len(reply['checkpoints']),2)
                child.stdin.close();await asyncio.wait_for(child.wait(),3)
                self.assertEqual(child.returncode,0)
            finally:
                if child.returncode is None:child.kill();await child.wait()
