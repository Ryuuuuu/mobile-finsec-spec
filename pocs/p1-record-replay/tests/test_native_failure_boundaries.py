"""POC failure acceptance with disposable files/processes; no device or GUI."""
import hashlib,json,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import test_qa_queue_api as api_fixture
import test_replay_queue as replay_fixture
from test_core import Fake
from pc.adapter import Uncertain
from pc.qa_queue_api import QueueAPI
from pc.qa_queue_stdio import capture

def snapshot(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(root).rglob('*') if p.is_file()}

class NativeFailureTests(unittest.TestCase):
    def test_mid_action_disconnect_timeout_cancel_stop_next_and_preserve_sources(self):
        for failure in ('disconnect','timeout','cancel'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as root:
                queue,routes,network=replay_fixture.ReplayQueueTests().make(root);before=snapshot(root)
                def prepare(index,route):
                    self.assertEqual(index,0)
                    adapter=Fake();original=adapter.click
                    def click(element):
                        original(element)  # Dispatch may have happened; never retry.
                        if failure=='cancel':queue.cancel()
                        elif failure=='timeout':raise TimeoutError('synthetic response timeout after dispatch')
                        else:raise Uncertain('synthetic disconnect after dispatch')
                    adapter.click=click;queue.combined.engine.a=adapter
                queue.prepare=prepare
                result=queue.run(routes)
                self.assertIn(result['status'],('partial','cancelled'))
                self.assertEqual([e['status'] for e in result['entries']][1:],['not_run','not_run'])
                self.assertEqual(len(queue.combined.engine.a.inputs),1)
                self.assertEqual([c.args[0] for c in network.command.call_args_list],['RECORD','STOP'])
                with self.assertRaises(RuntimeError):queue.run(routes)
                after=snapshot(root)
                self.assertTrue(all(after[path]==digest for path,digest in before.items()))

    def test_capture_child_cancel_drains_without_publish_and_clean_restart(self):
        with tempfile.TemporaryDirectory() as root:
            config=api_fixture.APIQueueTests().config(root);before=snapshot(root);spawned=[];ready=threading.Event()
            original=subprocess.Popen
            code="""import pathlib,sys,time,json
p=pathlib.Path(sys.argv[1]);deadline=time.monotonic()+5
while not (p/'cancel').exists():
 if time.monotonic()>deadline:raise RuntimeError('test cancellation not delivered')
 time.sleep(.01)
(p/'capture-result.json').write_text(json.dumps(dict(execution_status='interrupted',cleanup_verified=True,items=[],completion={})))
"""
            def child(args,**kwargs):
                process=original([sys.executable,'-c',code,args[-1]],**kwargs);spawned.append(process);ready.set();return process
            api=QueueAPI(config,Mock(),capture)
            with patch('pc.qa_queue_stdio.subprocess.Popen',side_effect=child):
                response=api.operation('capture',{'request':{'command_id':'cancel-child'}})['data']
                self.assertTrue(ready.wait(3));api.close()
            self.assertEqual(spawned[0].poll(),0)
            self.assertIsNone(api.current)
            self.assertEqual(api.operation('progress',{'execution_id':response['execution_id']})['execution']['execution_status'],'interrupted')
            self.assertEqual(len(api.catalog),1);self.assertFalse(list((api.root/'saved-recordings').glob('*')))
            after=snapshot(root);self.assertTrue(all(after[p]==v for p,v in before.items()))
            again=QueueAPI(config,Mock(return_value=dict(execution_status='completed',cleanup_verified=True,items=[])),capture)
            self.assertEqual(again.operation('capture',{'request':{'command_id':'cancel-child'}})['data']['status'],'recovery_required')
            self.assertEqual(api_fixture.APIQueueTests().submit(again,'explicit-new')['status'],'accepted');again.thread.join(3)

    def test_child_exit_without_cleanup_proof_blocks_restart(self):
        with tempfile.TemporaryDirectory() as root:
            config=api_fixture.APIQueueTests().config(root);original=subprocess.Popen;spawned=[]
            def child(args,**kwargs):
                process=original([sys.executable,'-c','raise SystemExit(7)'],**kwargs);spawned.append(process);return process
            api=QueueAPI(config,Mock(),capture)
            with patch('pc.qa_queue_stdio.subprocess.Popen',side_effect=child):
                response=api.operation('capture',{'request':{'command_id':'lost-child'}})['data'];api.thread.join(5)
            self.assertFalse(api.thread.is_alive());self.assertEqual(spawned[0].poll(),7)
            self.assertEqual(api.operation('progress',{'execution_id':response['execution_id']})['execution']['status'],'failed')
            again=QueueAPI(config,Mock(),capture)
            self.assertEqual(api_fixture.APIQueueTests().submit(again,'do-not-repeat')['status'],'busy')
            self.assertFalse(list((api.root/'saved-recordings').glob('*')))

    def test_delayed_child_cleanup_keeps_owner_and_final_result_unavailable(self):
        import time
        with tempfile.TemporaryDirectory() as root:
            config=api_fixture.APIQueueTests().config(root);original=subprocess.Popen;spawned=[];started=threading.Event();paths=[]
            code="""import pathlib,sys,time,json
p=pathlib.Path(sys.argv[1]);deadline=time.monotonic()+5
while not (p/'cancel').exists():
 if time.monotonic()>deadline:raise RuntimeError('test cancel missing')
 time.sleep(.01)
(p/'cancel-seen').write_text('yes')
while not (p/'allow-cleanup').exists():
 if time.monotonic()>deadline:raise RuntimeError('test cleanup release missing')
 time.sleep(.01)
(p/'capture-result.json').write_text(json.dumps(dict(execution_status='interrupted',cleanup_verified=True,items=[],completion={})))
"""
            def child(args,**kwargs):
                paths.append(Path(args[-1]));process=original([sys.executable,'-c',code,args[-1]],**kwargs);spawned.append(process);started.set();return process
            api=QueueAPI(config,Mock(),capture);closing=None
            with patch('pc.qa_queue_stdio.subprocess.Popen',side_effect=child):
                response=api.operation('capture',{'request':{'command_id':'slow-cleanup'}})['data']
                try:
                    self.assertTrue(started.wait(3));closing=threading.Thread(target=api.close);closing.start()
                    until=time.monotonic()+3
                    while not (paths[0]/'cancel-seen').exists() and time.monotonic()<until:time.sleep(.01)
                    self.assertTrue((paths[0]/'cancel-seen').exists());self.assertIsNone(spawned[0].poll())
                    self.assertTrue(closing.is_alive());self.assertEqual(api.operation('history',{})['runs'],[])
                    self.assertEqual(api_fixture.APIQueueTests().submit(api,'overlap')['status'],'busy')
                    self.assertEqual(api.operation('progress',{'execution_id':response['execution_id']})['execution']['status'],'in_progress')
                    restart=QueueAPI(config,Mock(),capture);self.assertEqual(api_fixture.APIQueueTests().submit(restart,'restart')['status'],'busy')
                finally:
                    if paths:(paths[0]/'allow-cleanup').write_text('test permits cleanup')
                    if closing:closing.join(6)
                    else:api.close()
            self.assertFalse(closing.is_alive());self.assertEqual(spawned[0].poll(),0);self.assertIsNone(api.current)

    def test_real_pipe_eof_requests_cleanup_and_preserves_restart_uncertainty(self):
        for clean in (True,False):
            with self.subTest(clean=clean),tempfile.TemporaryDirectory() as root:
                config=api_fixture.APIQueueTests().config(root);path=Path(root)/'config.json';path.write_text(json.dumps(config));before=snapshot(root)
                code="""import sys,json
from pc.qa_queue_api import QueueAPI,serve
config=json.load(open(sys.argv[1]));clean=sys.argv[2]=='True'
def backend(config,routes,cancel,emit):
 if not cancel.wait(3):raise RuntimeError('EOF cancellation missing')
 return dict(execution_status='interrupted',cleanup_verified=clean,items=[])
serve(QueueAPI(config,backend),sys.stdin,sys.stdout)
"""
                request=dict(contract='qa-device-request.v1',project_id='qa-device-queue',request_generation=1,operation='submit',arguments={'request':{'command_id':'pipe-eof','recording_refs':['qa']}})
                result=subprocess.run([sys.executable,'-c',code,str(path),str(clean)],input=json.dumps(request)+'\n',capture_output=True,text=True,timeout=8,check=True)
                self.assertEqual(json.loads(result.stdout.splitlines()[1])['data']['status'],'accepted')
                again=QueueAPI(config,Mock())
                self.assertEqual(api_fixture.APIQueueTests().submit(again,'pipe-eof')['status'],'recovery_required')
                self.assertEqual(again.current is None,clean)
                finals=list((Path(config['output'])).glob('api-*/native-result.json'));self.assertEqual(len(finals),1)
                self.assertEqual(json.loads(finals[0].read_text())['cleanup_verified'],clean)
                after=snapshot(root);self.assertTrue(all(after[p]==v for p,v in before.items()))
