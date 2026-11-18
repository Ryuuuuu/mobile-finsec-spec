import json,pathlib,subprocess,tempfile,unittest
from unittest.mock import Mock
from android_probe import collect,COMMANDS

class ReadonlyTests(unittest.TestCase):
    def run_probe(self,output,runner):
        lease=Mock();report=collect('adb','private-device',output,runner,lambda _:lease)
        lease.release.assert_called_once_with(clean=True);return report
    def test_observations_never_become_security_pass(self):
        with tempfile.TemporaryDirectory() as root:
            out=pathlib.Path(root)/'new';seen=[]
            def runner(adb,device,command):seen.append(command);return 'device' if command==('get-state',) else '1'
            report=self.run_probe(out,runner)
            self.assertEqual(seen,[c for _,c in COMMANDS]);self.assertEqual(report['execution_status'],'completed')
            self.assertEqual(report['verdict'],'inconclusive');self.assertFalse(report['synthetic'])
            self.assertTrue((out/'COMPLETE').exists());self.assertNotIn('private-device',(out/'result.json').read_text())
            for command in seen:self.assertTrue(command[0]=='get-state' or command[:2] in (('shell','getprop'),('shell','id'),('shell','getenforce')))
    def test_disconnected_transport_is_not_run(self):
        with tempfile.TemporaryDirectory() as root:
            report=self.run_probe(pathlib.Path(root)/'new',lambda *args:'offline')
            self.assertEqual(report['execution_status'],'not_run');self.assertEqual(len(report['observations']),1)
    def test_timeout_stops_and_preserves_partial_observations(self):
        with tempfile.TemporaryDirectory() as root:
            def runner(a,d,c):
                if c==('get-state',):return 'device'
                raise subprocess.TimeoutExpired('hidden-device',5)
            out=pathlib.Path(root)/'new';report=self.run_probe(out,runner)
            self.assertEqual(report['execution_status'],'timed_out');self.assertEqual(len(report['observations']),2)
            self.assertFalse((out/'COMPLETE').exists());self.assertNotIn('hidden-device',(out/'result.json').read_text())
    def test_empty_property_is_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            report=self.run_probe(pathlib.Path(root)/'new',lambda a,d,c:'device' if c==('get-state',) else '')
            self.assertEqual(report['observations'][1]['status'],'unknown');self.assertEqual(report['verdict'],'inconclusive')
    def test_raw_error_not_stored(self):
        with tempfile.TemporaryDirectory() as root:
            def runner(*args):raise OSError('private-device unauthorized')
            out=pathlib.Path(root)/'new';report=self.run_probe(out,runner)
            self.assertEqual(report['execution_status'],'not_run');self.assertNotIn('private-device',(out/'result.json').read_text())
    def test_existing_output_refused(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(FileExistsError):collect('adb','device',root)
    def test_quarantine_not_bypassed(self):
        with tempfile.TemporaryDirectory() as root:
            lease=Mock();lease.acquire.side_effect=RuntimeError('recovery required');runner=Mock()
            report=collect('adb','device',pathlib.Path(root)/'new',runner,lambda _:lease)
            runner.assert_not_called();lease.release.assert_not_called()
            self.assertEqual(report['execution_status'],'not_run')
    def test_oversized_observation_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            report=self.run_probe(pathlib.Path(root)/'new',lambda *args:'x'*4097)
            self.assertEqual(report['execution_status'],'not_run')

class AdapterAndValidationTests(unittest.TestCase):
    def fixture(self,out):
        return collect('unused','synthetic',out,lambda a,d,c:'device' if c==('get-state',) else 'synthetic',lambda _:Mock())
    def test_real_local_subprocess_transport_stub(self):
        import sys
        from android_probe import invoke,validate
        with tempfile.TemporaryDirectory() as root:
            root=pathlib.Path(root);stub=root/'fake_adb.py'
            stub.write_text("import sys; print('device' if sys.argv[1:] == ['get-state'] else 'synthetic')",encoding='utf-8')
            # Python -s disables user site; the device slot is a LOCAL STUB script here.
            report=collect(sys.executable,str(stub),root/'out',invoke,lambda _:Mock())
            self.assertEqual(report['execution_status'],'completed');validate(root/'out')
    def test_real_local_process_timeout(self):
        import sys,time
        from android_probe import invoke
        with tempfile.TemporaryDirectory() as root:
            stub=pathlib.Path(root)/'slow_stub.py';stub.write_text('import time; time.sleep(30)',encoding='utf-8')
            start=time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):invoke(sys.executable,str(stub),('get-state',))
            self.assertLess(time.monotonic()-start,12)
    def test_adapter_rejects_mutation_before_process(self):
        from android_probe import invoke
        from unittest.mock import patch
        with patch('android_probe.subprocess.run') as run:
            with self.assertRaises(ValueError):invoke('adb','synthetic',('shell','settings','put','global','x','1'))
            run.assert_not_called()
    def test_cleanup_failure_cannot_complete(self):
        from android_probe import validate
        with tempfile.TemporaryDirectory() as root:
            out=pathlib.Path(root)/'out';lease=Mock();lease.release.side_effect=RuntimeError('injected')
            report=collect('adb','synthetic',out,lambda a,d,c:'device' if c==('get-state',) else '1',lambda _:lease)
            self.assertEqual(report['execution_status'],'failed');self.assertEqual(report['cleanup']['lease'],'unknown');validate(out)
    def test_cancel_preserves_partial_without_success_marker(self):
        from android_probe import validate
        with tempfile.TemporaryDirectory() as root:
            out=pathlib.Path(root)/'out'
            def runner(a,d,c):
                if c==('get-state',):return 'device'
                raise KeyboardInterrupt()
            report=collect('adb','synthetic',out,runner,lambda _:Mock())
            self.assertEqual(report['execution_status'],'cancelled');self.assertEqual(len(report['observations']),1);validate(out)
    def test_report_tampering_rejected_even_with_resealed_hash(self):
        import hashlib
        from android_probe import validate
        for mutation in ('verdict','command','value','truncated','duplicate','marker'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as root:
                out=pathlib.Path(root)/'out';report=self.fixture(out)
                if mutation=='verdict':report['verdict']='pass'
                elif mutation=='command':report['observations'][1]['command']=['shell','su']
                elif mutation=='value':report['observations'][1]['value']='changed'
                elif mutation=='truncated':report['observations'].pop()
                raw=json.dumps(report).encode()
                if mutation=='duplicate':raw=raw.replace(b'"verdict": "inconclusive"',b'"verdict": "pass", "verdict": "inconclusive"')
                (out/'result.json').write_bytes(raw)
                (out/'COMPLETE').write_text('bad' if mutation=='marker' else hashlib.sha256(raw).hexdigest(),encoding='ascii')
                with self.assertRaises(ValueError):validate(out)

    def test_validation_cli_uses_exit_code_without_device(self):
        import sys
        with tempfile.TemporaryDirectory() as root:
            out=pathlib.Path(root)/'out';self.fixture(out)
            command=[sys.executable,str(pathlib.Path(__file__).resolve().parents[1]/'android_probe.py'),'--validate','--output',str(out)]
            result=subprocess.run(command,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            (out/'COMPLETE').write_text('wrong',encoding='ascii')
            result=subprocess.run(command,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,2)
