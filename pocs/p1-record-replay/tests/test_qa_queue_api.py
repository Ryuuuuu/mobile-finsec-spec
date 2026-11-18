import io,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock
from pc.qa_queue_api import QueueAPI,serve

class APIQueueTests(unittest.TestCase):
    def config(self,root):
        root=Path(root);path=root/'route.json';package='dev.finsec.qa.network';state=package+':id/state'
        path.write_text(json.dumps(dict(schema_version=2,recording_id='synthetic-route',status='completed',device_id='SYNTHETIC',package_id=package,
            target=dict(version_code='1',version_name='1',apk_sha256s={'base.apk':'a'*64}),initial={'id':state,'text':'ready'},secure='unknown',network_coverage='none',
            actions=[dict(action_id='synthetic-action',action=dict(type='wait',timeout=1,post={'id':state,'text':'ready'}))])))
        return dict(output=str(root/'output'),routes=[dict(ref='qa',name='Synthetic fixture',recorded_at='2026-11-18T00:00:00Z',path=str(path))])
    def submit(self,api,command='one',refs=None):
        return api.operation('submit',{'request':dict(command_id=command,recording_refs=['qa'] if refs is None else refs)})['data']
    def test_async_duplicate_busy_cancel_and_final_history(self):
        with tempfile.TemporaryDirectory() as root:
            began=threading.Event();received=[]
            def backend(config,routes,cancel,emit):
                received.extend(routes);began.set();emit('synthetic_running');cancel.wait(3)
                return dict(execution_status='interrupted',cleanup_verified=True,items=[],completion={})
            api=QueueAPI(self.config(root),backend)
            first=self.submit(api);self.assertTrue(began.wait(1))
            self.assertEqual(self.submit(api)['status'],'duplicate');self.assertEqual(self.submit(api,'two')['status'],'busy')
            self.assertEqual(self.submit(api,'one',['qa','qa'])['status'],'conflict')
            live=api.operation('progress',{'execution_id':first['execution_id']});self.assertEqual(live['execution']['status'],'in_progress')
            self.assertEqual(api.operation('history',{})['runs'],[])
            api.operation('cancel',{'execution_id':first['execution_id']});api.thread.join(3)
            final=api.operation('result',{'run_id':first['execution_id']});self.assertTrue(final['result']['cleanup_verified'])
            self.assertEqual(len(received),1);self.assertEqual(len(api.operation('history',{})['runs']),1)
            again=QueueAPI(api.config,Mock());self.assertEqual(self.submit(again)['status'],'recovery_required')
    def test_uncertain_cleanup_blocks_new_and_restart(self):
        with tempfile.TemporaryDirectory() as root:
            config=self.config(root);backend=Mock(return_value=dict(execution_status='interrupted',cleanup_verified=False,items=[]))
            api=QueueAPI(config,backend);first=self.submit(api);api.thread.join(3)
            self.assertEqual(self.submit(api,'two')['status'],'busy')
            self.assertFalse(api.operation('progress',{'execution_id':first['execution_id']})['execution']['cleanup_verified'])
            again=QueueAPI(config,backend);self.assertEqual(self.submit(again,'three')['status'],'busy');self.assertEqual(backend.call_count,1)
    def test_incomplete_admission_and_scope_rejection(self):
        with tempfile.TemporaryDirectory() as root:
            config=self.config(root);backend=Mock(side_effect=OSError('synthetic storage failure'));api=QueueAPI(config,backend)
            self.submit(api);api.thread.join(3);again=QueueAPI(config,backend)
            self.assertEqual(self.submit(again,'two')['status'],'busy')
            with self.assertRaises(ValueError):self.submit(api,'bad',['../private'])
            with self.assertRaises(ValueError):api.operation('result',{'run_id':'../private'})
            out=io.StringIO()
            with self.assertRaises(ValueError):serve(api,io.StringIO(json.dumps(dict(contract='mock-ui-request.v1',project_id='synthetic',request_generation=1))+'\n'),out)
            self.assertEqual(json.loads(out.getvalue())['contract'],'qa-device-stdio.v1')
    def test_close_requests_cancel_and_joins_owner(self):
        with tempfile.TemporaryDirectory() as root:
            def backend(config,routes,cancel,emit):
                self.assertTrue(cancel.wait(3));return dict(execution_status='interrupted',cleanup_verified=True,items=[])
            api=QueueAPI(self.config(root),backend);self.submit(api);api.close();self.assertFalse(api.thread.is_alive())
