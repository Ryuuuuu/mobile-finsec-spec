import tempfile,unittest,json,threading
from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path
from pc.core import Journal,atomic
from pc.combined import CombinedRun

class CombinedTests(unittest.TestCase):
    def make(self,root,fail=None):
        engine=SimpleNamespace(a=SimpleNamespace(package='dev.finsec.qa.network'),j=None,mode='idle',stop_requested=Mock(),cancel=threading.Event())
        def start():engine.j=Journal(root,'recording');engine.mode='recording';engine.record={'status':'incomplete'}
        def finish():engine.record['status']='completed';engine.mode='idle'
        engine.start=start;engine.finish=finish
        network=Mock()
        def command(name,**kw):
            if name==fail:raise TimeoutError('injected lost acknowledgement')
            return {'recording_id':'net-1'} if name=='RECORD' else {'network_coverage':'complete_for_supported_scope'}
        network.command.side_effect=command
        return CombinedRun(engine,network,root),engine,network
    def test_start_barrier_ids_and_stop_completion(self):
        with tempfile.TemporaryDirectory() as root:
            run,engine,network=self.make(root);run.start();self.assertEqual(run.state,'active')
            self.assertEqual(run.link['input_recording_id'],engine.j.id);self.assertEqual(run.link['network_recording_id'],'net-1')
            run.finish();saved=json.loads((run.j.path/'combined.json').read_text())
            self.assertEqual(saved['status'],'completed')
            events=[json.loads(s)['event'] for s in (run.j.path/'events.jsonl').read_text().splitlines()]
            self.assertLess(events.index('network_start_ack'),events.index('input_enabled'))
            self.assertLess(events.index('input_closed'),events.index('network_stop_ack'))
    def test_lost_start_ack_blocks_input_and_compensates(self):
        with tempfile.TemporaryDirectory() as root:
            run,engine,network=self.make(root,'RECORD')
            with self.assertRaises(TimeoutError):run.start()
            self.assertEqual(run.state,'partial');self.assertEqual(engine.mode,'incomplete')
            self.assertEqual(network.command.call_args.args[0],'STOP')
    def test_lost_stop_ack_never_reports_completion(self):
        with tempfile.TemporaryDirectory() as root:
            run,engine,network=self.make(root,'STOP');run.start()
            with self.assertRaises(TimeoutError):run.finish()
            self.assertEqual(json.loads((run.j.path/'combined.json').read_text())['status'],'partial')
            self.assertTrue(run.link['network_stop_uncertain'])
    def test_input_failure_abort_preserves_partial_route(self):
        with tempfile.TemporaryDirectory() as root:
            run,engine,network=self.make(root);run.start();run.abort('postcondition failed')
            self.assertEqual(json.loads((engine.j.path/'route.json').read_text())['status'],'incomplete')
            self.assertEqual(run.state,'partial')
    def test_repeated_start_does_not_create_new_network_recording(self):
        with tempfile.TemporaryDirectory() as root:
            run,engine,network=self.make(root);run.start()
            with self.assertRaises(RuntimeError):run.start()
            self.assertEqual(network.command.call_count,1)

    def test_cancel_during_start_never_enables_input(self):
        with tempfile.TemporaryDirectory() as root:
            run,engine,network=self.make(root)
            original=network.command.side_effect
            def command(name,**kw):
                if name=='RECORD':engine.cancel.set()
                return original(name,**kw)
            network.command.side_effect=command
            with self.assertRaises(InterruptedError):run.start()
            self.assertEqual(run.state,'partial')
            self.assertNotIn('input_enabled',(run.j.path/'events.jsonl').read_text())

class NetworkLifecycleTests(unittest.TestCase):
    def test_favicon_and_request_close_cleanly(self):
        import urllib.request
        from pc.combined_ui import Network
        with tempfile.TemporaryDirectory() as root:
            network=Network(root)
            try:
                network.command('RECORD',device_id='synthetic',app_id='dev.finsec.qa.network')
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for path,status in (('/synthetic/qa-regression',200),('/favicon.ico',204)):
                    with opener.open('http://127.0.0.1:'+str(network.port)+path,timeout=3) as r:
                        self.assertEqual(r.status,status);r.read()
                self.assertEqual(network.command('STOP')['network_coverage'],'complete_for_supported_scope')
            finally:network.close()
            self.assertFalse(network.thread.is_alive())
