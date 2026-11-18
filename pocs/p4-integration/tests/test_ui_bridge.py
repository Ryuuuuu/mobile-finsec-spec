import asyncio,json,sqlite3,unittest
from contextlib import closing
import test_integrated_structure as integrated_fixture
from integration.ui_bridge import UIBridge,MockUIClient

class UIBridgeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=integrated_fixture.IntegratedFlowTests.asyncSetUp
    set_message=integrated_fixture.IntegratedFlowTests.set_message
    api=integrated_fixture.IntegratedFlowTests.api
    request=integrated_fixture.IntegratedFlowTests.request
    async def test_record_check_results_and_live_cursor(self):
        self.set_message();entered=asyncio.Event();release=asyncio.Event()
        class Executor:
            async def run(_,context,progress):entered.set();await release.wait();return {'execution_status':'completed'}
        api=self.api(Executor());bridge=UIBridge('synthetic-project',api);ui=MockUIClient('synthetic-project')
        record=bridge.recording('qa-record',ui.generation)
        self.assertEqual(record['recording']['packet_status'],'complete')
        generation=ui.select('check');reply=api.submit(self.request());await entered.wait()
        event_response=bridge.progress(reply['execution_id'],generation)
        self.assertTrue(ui.apply(event_response));count=len(ui.events);ui.apply(event_response);self.assertEqual(len(ui.events),count)
        self.assertGreater(count,0);self.assertEqual(ui.tab,'check')
        self.assertFalse(event_response['controls']['selection_enabled']);self.assertFalse(event_response['controls']['device_input_enabled'])
        self.assertTrue(event_response['controls']['history_enabled'])
        self.assertEqual(bridge.history(generation)['runs'],[])
        self.assertEqual(bridge.result(event_response['run_id'],generation)['status'],'not_finalized')
        gap=bridge.progress(reply['execution_id'],generation,cursor=999)
        self.assertTrue(gap['resync_required']);self.assertFalse(ui.apply(gap))
        self.assertTrue(ui.apply(bridge.progress(reply['execution_id'],generation,cursor=0)))
        release.set();result=await api.wait(reply['execution_id'])
        self.assertEqual(ui.tab,'check')
        generation=ui.select('results',result['run_id']);detail=bridge.result(result['run_id'],generation)
        self.assertTrue(ui.apply(detail));self.assertNotIn('events',ui.result)
        self.assertEqual(len(bridge.history(generation)['runs']),1)
    async def test_partial_and_disconnected_history_cancel(self):
        self.record.update(status='interrupted',network_coverage='partial')
        with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as c:c.execute('UPDATE recordings SET data=?',(json.dumps(self.record),))
        entered=asyncio.Event()
        class Executor:
            async def run(_,context,progress):entered.set();await asyncio.Event().wait()
        api=self.api(Executor());bridge=UIBridge('synthetic-project',api)
        self.assertEqual(bridge.recording('qa-record',0)['recording']['packet_status'],'partial')
        reply=api.submit(self.request());await entered.wait()
        self.assertEqual(api.cancel(reply['execution_id'])['status'],'cancel_requested')
        self.assertEqual(api.cancel(reply['execution_id'])['status'],'cancel_already_requested')
        result=await api.wait(reply['execution_id']);self.assertEqual(result['execution_status'],'cancelled')
        api.inventory['devices']['synthetic-device-p4']['connection']='disconnected'
        self.assertFalse(api.inspect(self.request())['enabled'])
        self.assertEqual(bridge.history(1)['runs'][0]['execution_status'],'cancelled')
        self.assertEqual(bridge.result(result['run_id'],1)['status'],'ok')
    async def test_late_project_generation_and_run_responses_rejected(self):
        ui=MockUIClient('project-a');generation=ui.select('results','synthetic-new')
        base=dict(project_id='project-a',request_generation=generation,run_id='synthetic-new',status='ok',result={'marker':'new'})
        self.assertTrue(ui.apply(base))
        for changes in ({'project_id':'project-b'},{'request_generation':generation-1},{'run_id':'synthetic-old'}):
            self.assertFalse(ui.apply(dict(base,**changes)));self.assertEqual(ui.result,{'marker':'new'})
    async def test_no_device_no_run_and_result_path_rejection(self):
        api=self.api();api.inventory['devices']={};bridge=UIBridge('synthetic-project',api)
        self.assertIn('DEVICE_MISSING',api.inspect(self.request())['reasons'])
        self.assertEqual(api.submit(self.request())['status'],'not_run')
        self.assertEqual(bridge.history(0)['runs'],[])
        self.assertFalse(bridge.progress('unknown',0)['controls']['device_input_enabled'])
        self.assertEqual(bridge.result('../outside',0)['status'],'invalid_selection')
