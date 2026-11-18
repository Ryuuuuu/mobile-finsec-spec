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
