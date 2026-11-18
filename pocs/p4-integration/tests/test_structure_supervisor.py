import asyncio,json,tempfile,unittest
from pathlib import Path
from integration.supervisor import StructureSupervisor

class StructureRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.skills=self.root/'skills'
        for item in ('first','second','third'):
            for role in ('common','aos','ios'):
                p=self.skills/item/role/'SKILL.md';p.parent.mkdir(parents=True)
                p.write_text('OPAQUE MOCK '+role)
    def supervisor(self,executor=None):return StructureSupervisor(self.root/'runs',self.skills,executor)
    def assert_saved(self,result):
        saved=json.loads((self.root/'runs'/result['run_id']/'result.json').read_text())
        self.assertEqual(saved,result)
        self.assertNotIn('verdict',json.dumps(saved))
        self.assertNotIn('OPAQUE MOCK',json.dumps(saved))
    async def test_selected_platform_and_sequential_delivery(self):
        for platform in (None,'aos','ios'):
            seen=[];active=0
            class Executor:
                async def run(_,context,progress):
                    nonlocal active
                    active+=1;self.assertEqual(active,1)
                    seen.append((context['item_id'],[s['role'] for s in context['skill_snapshot']['skills']]))
                    await asyncio.sleep(.01);progress();active-=1
                    return {'execution_status':'completed'}
            result=await self.supervisor(Executor()).run(['first','second'],platform)
            self.assertEqual(result['execution_status'],'completed')
            roles=['common']+([platform] if platform else [])
            self.assertEqual(seen,[('first',roles),('second',roles)])
            self.assertEqual([e['type'] for e in result['events']],['item_started','item_completed','item_started','item_completed','run_finished'])
            self.assert_saved(result)
    async def test_missing_skill_no_executor_and_not_failure(self):
        (self.skills/'second'/'aos'/'SKILL.md').unlink()
        result=await self.supervisor().run(['first','second'],'aos')
        self.assertEqual(result['execution_status'],'not_run')
        self.assertEqual([r['execution_status'] for r in result['items']],['not_run','not_run'])
        self.assertEqual(result['items'][1]['reason'],'SKILL_LOAD_FAILED')
        self.assert_saved(result)
    async def test_error_exit_and_hang_stop_followups(self):
        for mode,reason,status in (('error','EXECUTOR_ERROR','failed'),('exit','EXECUTOR_EXIT_OR_INVALID_RESULT','failed'),('hang','PROGRESS_TIMEOUT','timed_out')):
            seen=[]
            class Executor:
                async def run(_,context,progress):
                    seen.append(context['item_id'])
                    if context['item_id']=='first':return {'execution_status':'completed'}
                    if mode=='error':raise RuntimeError('PRIVATE_SENTINEL')
                    if mode=='exit':return None
                    await asyncio.Event().wait()
            result=await self.supervisor(Executor()).run(['first','second','third'],timeout=.2,progress_timeout=.03)
            self.assertEqual([r['execution_status'] for r in result['items']],['completed',status,'not_run'])
            self.assertEqual(result['items'][1]['reason'],reason)
            self.assertEqual(seen,['first','second']);self.assertNotIn('PRIVATE_SENTINEL',json.dumps(result))
            self.assert_saved(result)
    async def test_item_deadline_despite_progress(self):
        class Executor:
            async def run(_,context,progress):
                while True:progress();await asyncio.sleep(.005)
        result=await self.supervisor(Executor()).run(['first'],timeout=.03,progress_timeout=.1)
        self.assertEqual(result['items'][0]['reason'],'ITEM_TIMEOUT')
    async def test_same_device_exclusion_two_supervisors(self):
        entered=asyncio.Event();release=asyncio.Event()
        class Executor:
            async def run(_,context,progress):
                entered.set();await release.wait();return {'execution_status':'completed'}
        task=asyncio.create_task(self.supervisor(Executor()).run(['first'],timeout=1,progress_timeout=1))
        await entered.wait()
        blocked=await self.supervisor().run(['first'])
        self.assertEqual(blocked['execution_status'],'not_run')
        self.assertEqual(blocked['reason'],'DEVICE_BUSY_OR_RECOVERY')
        release.set();self.assertEqual((await task)['execution_status'],'completed')
    async def test_cancel_resistant_worker_retains_durable_recovery(self):
        release=asyncio.Event()
        self.addCleanup(release.set)
        class Executor:
            async def run(_,context,progress):
                while not release.is_set():
                    try:await release.wait()
                    except asyncio.CancelledError:pass
                return {'execution_status':'completed'}
        supervisor=self.supervisor(Executor())
        result=await supervisor.run(['first'],timeout=.03,progress_timeout=.02)
        self.assertTrue(result['recovery_required'])
        blocked=await self.supervisor().run(['first'])
        self.assertEqual(blocked['execution_status'],'not_run')
        release.set()
        await asyncio.gather(*supervisor.survivors)
        self.assertEqual(self.supervisor().lease.inspect()['lifecycle'],'recovery_required')
        self.assert_saved(result)
    async def test_external_cancel_records_cancelled_and_missing_followup(self):
        entered=asyncio.Event()
        class Executor:
            async def run(_,context,progress):entered.set();await asyncio.Event().wait()
        task=asyncio.create_task(self.supervisor(Executor()).run(['first','second']))
        await entered.wait();task.cancel();result=await task
        self.assertEqual([r['execution_status'] for r in result['items']],['cancelled','not_run'])
        self.assert_saved(result)
