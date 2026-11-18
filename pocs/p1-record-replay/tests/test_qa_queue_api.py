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

    def capture_fixture(self,config,folder,cancel,emit):
        path=folder/'route.json';path.write_text(Path(config['routes'][0]['path']).read_text())
        route=json.loads(path.read_text())
        (folder/'combined-link.json').write_text(json.dumps(dict(status='completed',input_recording_id=route['recording_id'],network_stop={'network_coverage':'complete_for_supported_scope'})))
        return dict(execution_status='completed',cleanup_verified=True,items=[],saved_recording=dict(ref='capture-'+'a'*32,name='Synthetic saved route',recorded_at='2026-11-19T00:00:00Z',path=str(path)))

    def test_capture_publication_restart_and_selected_replay(self):
        with tempfile.TemporaryDirectory() as root:
            config=self.config(root);backend=Mock(return_value=dict(execution_status='completed',cleanup_verified=True,items=[]))
            api=QueueAPI(config,backend,self.capture_fixture)
            request={'request':{'command_id':'capture-one'}}
            first=api.operation('capture',request)['data'];api.thread.join(3)
            self.assertEqual(api.operation('capture',request)['data']['status'],'duplicate')
            self.assertEqual(len(api.operation('recordings',{})['recordings']),2)
            again=QueueAPI(config,backend,self.capture_fixture)
            self.assertEqual(len(again.catalog),2)
            self.assertEqual(again.operation('capture',request)['data']['status'],'recovery_required')
            self.submit(again,'replay-new',['capture-'+'a'*32,'qa']);again.thread.join(3)
            self.assertEqual(len(backend.call_args.args[1]),2)

    def test_capture_incomplete_cleanup_and_wrong_link_never_publish(self):
        for defect in ('cleanup','link','outside'):
            with self.subTest(defect=defect),tempfile.TemporaryDirectory() as root:
                config=self.config(root)
                def capture(config,folder,cancel,emit):
                    result=self.capture_fixture(config,folder,cancel,emit)
                    if defect=='cleanup':result['cleanup_verified']=False
                    if defect=='link':(folder/'combined-link.json').write_text('{}')
                    if defect=='outside':result['saved_recording']['path']=config['routes'][0]['path']
                    return result
                api=QueueAPI(config,Mock(),capture);api.operation('capture',{'request':{'command_id':'bad'}});api.thread.join(3)
                self.assertEqual(len(api.catalog),1)
                self.assertFalse(list((api.root/'saved-recordings').glob('*.json')))
                self.assertEqual(self.submit(api,'next')['status'],'busy')

    def test_capture_and_replay_share_exclusion_and_cancel(self):
        with tempfile.TemporaryDirectory() as root:
            began=threading.Event()
            def capture(config,folder,cancel,emit):
                began.set();self.assertTrue(cancel.wait(3));return dict(execution_status='interrupted',cleanup_verified=True,items=[])
            api=QueueAPI(self.config(root),Mock(),capture)
            api.operation('capture',{'request':{'command_id':'one'}});self.assertTrue(began.wait(1))
            self.assertEqual(self.submit(api,'replay')['status'],'busy');api.close()
            self.assertIsNone(api.current);self.assertEqual(len(api.catalog),1)
