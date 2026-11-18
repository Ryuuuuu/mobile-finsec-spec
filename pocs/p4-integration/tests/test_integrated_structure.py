import asyncio,base64,json,subprocess,sys
from pathlib import Path
from unittest.mock import patch
import unittest
import test_packet_access as packet_fixture
import test_start_api as start_fixture
from integration.start_api import StartAPI
from integration.supervisor import StructureSupervisor
from integration.run_journal import list_runs,write_new

class IntegratedFlowTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=packet_fixture.fixture_module.ArtifactTests.asyncSetUp
    set_message=packet_fixture.PacketAccessTests.set_message
    def api(self,executor=None):
        skills=self.root/'skills'
        for item in ('first','second'):
            for role in ('common','aos'):
                p=skills/item/role/'SKILL.md';p.parent.mkdir(parents=True,exist_ok=True);p.write_text('OPAQUE MOCK')
        return StartAPI(StructureSupervisor(self.root/'runs',skills,executor),start_fixture.inventory(),start_fixture.catalog(),{'qa-record':self.files})
    def request(self,command='synthetic-e2e'):
        r=start_fixture.request();r.update(command_id=command,recording_ref='qa-record');return r
    async def test_selection_to_live_packet_final_history_multiple_runs(self):
        self.set_message(b'QA E2E REQUEST');entered=asyncio.Event();release=asyncio.Event();seen=[]
        class Executor:
            async def run(_,context,progress):
                entered.set();await release.wait()
                data=context['read_packet'](context['recording_context']['recording_id'],'synthetic-packet','request')
                seen.append((context['item_id'],base64.b64decode(data['data'])))
                progress();return {'execution_status':'completed'}
        api=self.api(Executor());self.assertTrue(api.inspect(self.request())['enabled'])
        reply=api.submit(self.request());await entered.wait()
        row,=list_runs(self.root/'runs');self.assertEqual(row['storage_status'],'unfinalized')
        self.assertIn('item_started',(self.root/'runs'/row['run_id']/'live.jsonl').read_text())
        release.set();first=await api.wait(reply['execution_id'])
        self.assertEqual(first['execution_status'],'completed');self.assertEqual(seen[:2],[('first',b'QA E2E REQUEST'),('second',b'QA E2E REQUEST')])
        reply2=api.submit(self.request('synthetic-second-run'));second=await api.wait(reply2['execution_id'])
        self.assertNotEqual(first['run_id'],second['run_id'])
        rows=list_runs(self.root/'runs',date=first['started_at'][:10]);self.assertEqual(len(rows),2)
        self.assertTrue(all(r['storage_status']=='finalized' for r in rows))
        self.assertNotIn('QA E2E REQUEST',json.dumps(first))
        self.assertEqual(self.api().submit(self.request())['status'],'recovery_required')
    async def test_middle_failure_preserves_first_and_revokes(self):
        self.set_message();saved=[]
        class Executor:
            async def run(_,context,progress):
                saved.append((context['read_packet'],context['recording_context']['recording_id']))
                if context['item_id']=='second':raise RuntimeError('PRIVATE_FAILURE')
                return {'execution_status':'completed'}
        api=self.api(Executor());reply=api.submit(self.request());result=await api.wait(reply['execution_id'])
        self.assertEqual([r['execution_status'] for r in result['items']],['completed','failed'])
        self.assertEqual(result['completion'],{'completed':1,'selected':2})
        for call,rid in saved:self.assertEqual(call(rid,'synthetic-packet','request')['status'],'expired')
        self.assertNotIn('PRIVATE_FAILURE',json.dumps(result))
        self.assertEqual(list_runs(self.root/'runs')[0]['execution_status'],'failed')
    async def test_storage_failure_restart_does_not_retry_old_command(self):
        api=self.api()
        def broken(path,value):
            if Path(path).name=='finalized.json':raise OSError('synthetic marker failure')
            return write_new(path,value)
        with patch('integration.run_journal.write_new',side_effect=broken):
            reply=api.submit(self.request())
            with self.assertRaises(OSError):await api.wait(reply['execution_id'])
        self.assertEqual(api.status(reply['execution_id'])['status'],'error')
        self.assertEqual(list_runs(self.root/'runs')[0]['storage_status'],'unfinalized')
        restarted=self.api();self.assertEqual(restarted.submit(self.request())['status'],'recovery_required')
        self.assertEqual(restarted.status(reply['execution_id'])['status'],'recovery_required')
        changed=self.request();changed['items']=['first']
        self.assertEqual(restarted.submit(changed)['status'],'conflict')
    async def test_actual_child_exit_leaves_unfinalized_and_owned_lease(self):
        api=self.api();root=self.root/'runs'
        code="""import os,sys
from pathlib import Path
from integration.lease import LeaseStore
from integration.run_journal import RunJournal
root=Path(sys.argv[1]);run='synthetic-child-exit';out=root/run;out.mkdir()
lease=LeaseStore(root/'lease.sqlite');assert lease.acquire(run,'synthetic-child-epoch') is not None
journal=RunJournal(out,run);journal.event({'seq':1,'type':'item_started','item_id':'first'})
os._exit(7)
"""
        proc=subprocess.run([sys.executable,'-c',code,str(root)],capture_output=True,timeout=10)
        self.assertEqual(proc.returncode,7)
        restarted=self.api();self.assertEqual(restarted.submit(self.request())['status'],'not_run')
        row,=list_runs(root);self.assertEqual(row['storage_status'],'unfinalized')
        self.assertEqual(restarted.supervisor.lease.inspect()['lifecycle'],'active')
    async def test_missing_registry_ref_and_no_selection_default(self):
        api=self.api();r=self.request();r['recording_ref']='missing'
        self.assertEqual(api.submit(r)['status'],'not_run');self.assertEqual(api.jobs,{})
        reply=api.submit(start_fixture.request());result=await api.wait(reply['execution_id'])
        self.assertEqual(result['items'][0]['recording_context']['mode'],'app_launch_default')
