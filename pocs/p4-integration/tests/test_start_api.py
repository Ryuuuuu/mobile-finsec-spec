import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile,unittest
from integration.start_api import preflight,StartAPI
from integration.supervisor import StructureSupervisor


def inventory():return {'revision':1,'devices':{'synthetic-device-p4':{'platform':'aos','connection':'connected','authorized':True,'capabilities':{'mock_input':True,'recording_read':True}}}}
def catalog():return {'first':{'platforms':['aos','ios'],'common_skill':True,'platform_skills':['aos','ios'],'requires':['mock_input']},'second':{'platforms':['aos'],'common_skill':True,'platform_skills':['aos'],'requires':['recording_read']}}
def request():return {'contract':'structural-start.v1','command_id':'synthetic-command','device_id':'synthetic-device-p4','platform':'aos','items':['first','second'],'inventory_revision':1}

class PreflightTests(unittest.TestCase):
    def test_enabled_and_each_reason(self):
        r=request();self.assertTrue(preflight(r,inventory(),catalog())['enabled'])
        for field,value,reason in (('connection','offline','DEVICE_UNAVAILABLE'),('authorized',False,'DEVICE_NOT_AUTHORIZED'),('platform','ios','PLATFORM_MISMATCH')):
            inv=inventory();inv['devices']['synthetic-device-p4'][field]=value
            self.assertIn(reason,preflight(r,inv,catalog())['reasons'])
        self.assertIn('DEVICE_BUSY_OR_RECOVERY',preflight(r,inventory(),catalog(),'active')['reasons'])
        self.assertIn('DEVICE_MISSING',preflight(r,{'revision':1,'devices':{}},catalog())['reasons'])
        inv=inventory();inv['revision']=2
        self.assertIn('STALE_SELECTION',preflight(r,inv,catalog())['reasons'])
    def test_item_capability_and_skill_availability(self):
        inv=inventory();inv['devices']['synthetic-device-p4']['capabilities']['recording_read']=False
        rows=preflight(request(),inv,catalog())['items']
        self.assertTrue(rows[0]['enabled']);self.assertFalse(rows[1]['enabled'])
        self.assertIn('CAPABILITY_MISSING:recording_read',rows[1]['reasons'])
        c=catalog();c['first']['common_skill']=False;c['second']['platform_skills']=[]
        rows=preflight(request(),inventory(),c)['items']
        self.assertIn('COMMON_SKILL_MISSING',rows[0]['reasons'])
        self.assertIn('PLATFORM_SKILL_MISSING',rows[1]['reasons'])
    def test_unknown_duplicate_and_payload_fields(self):
        r=request();r['items']=['unknown']
        self.assertIn('ITEM_UNKNOWN',preflight(r,inventory(),catalog())['items'][0]['reasons'])
        for field,value in (('items',['first','first']),('items',[]),('inventory_revision',True),('platform','other')):
            r=request();r[field]=value
            with self.assertRaises(ValueError):preflight(r,inventory(),catalog())
        r=request();r['model']='unexpected'
        with self.assertRaises(ValueError):preflight(r,inventory(),catalog())

class StartTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.skills=self.root/'skills'
        for item in ('first','second'):
            for platform in ('common','aos','ios'):
                p=self.skills/item/platform/'SKILL.md';p.parent.mkdir(parents=True);p.write_text('MOCK')
    def api(self,executor=None):return StartAPI(StructureSupervisor(self.root/'runs',self.skills,executor),inventory(),catalog())
    async def test_duplicate_same_handle_and_changed_payload_conflict(self):
        api=self.api();r=request();first=api.submit(r);duplicate=api.submit(r)
        self.assertEqual(first['execution_id'],duplicate['execution_id']);self.assertEqual(duplicate['status'],'duplicate')
        r['items']=['first'];self.assertEqual(api.submit(r)['status'],'conflict')
        result=await api.wait(first['execution_id']);self.assertEqual(result['execution_status'],'completed')
        self.assertEqual(api.submit(request())['execution_id'],first['execution_id'])
        self.assertEqual(api.status(first['execution_id'])['status'],'finished')
    async def test_selection_changed_before_admission_no_executor(self):
        api=self.api();r=api.submit(request());api.inventory['revision']=2
        result=await api.wait(r['execution_id'])
        self.assertEqual(result['execution_status'],'not_run');self.assertEqual(result['reason'],'PRECONDITION_CHANGED')
        self.assertFalse(any(e['type']=='item_started' for e in result['events']))
    async def test_disconnect_during_item_stops_followups(self):
        entered=asyncio.Event();seen=[]
        class Executor:
            async def run(_,context,progress):seen.append(context['item_id']);entered.set();await asyncio.Event().wait()
        api=self.api(Executor());r=api.submit(request());await entered.wait()
        api.inventory['devices']['synthetic-device-p4']['connection']='disconnected'
        result=await api.wait(r['execution_id'])
        self.assertEqual([x['execution_status'] for x in result['items']],['failed','not_run'])
        self.assertEqual(result['items'][0]['reason'],'PRECONDITION_CHANGED');self.assertEqual(seen,['first'])
    async def test_two_commands_have_one_owner(self):
        entered=asyncio.Event();release=asyncio.Event()
        class Executor:
            async def run(_,context,progress):entered.set();await release.wait();return {'execution_status':'completed'}
        api=self.api(Executor());r=request();first=api.submit(r);r['command_id']='another-command';second=api.submit(r)
        await entered.wait();release.set()
        results=await asyncio.gather(api.wait(first['execution_id']),api.wait(second['execution_id']))
        self.assertEqual(sorted(x['execution_status'] for x in results),['completed','not_run'])
    async def test_disabled_and_ios_selection(self):
        api=self.api();api.inventory['devices']['synthetic-device-p4']['authorized']=False
        self.assertEqual(api.submit(request())['status'],'not_run');self.assertEqual(api.jobs,{})
        api=self.api();api.inventory['devices']['synthetic-device-p4']['platform']='ios'
        r=request();r.update(platform='ios',items=['first'])
        reply=api.submit(r);self.assertEqual((await api.wait(reply['execution_id']))['execution_status'],'completed')
