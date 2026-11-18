"""Real subprocess pipe ownership; synthetic child replaces ADB, no device."""
import json,subprocess,sys,unittest

class NativePipeTests(unittest.TestCase):
    def test_adb_children_cannot_consume_protocol_input(self):
        for kind in ('adapter','fixture','reverse'):
            with self.subTest(kind=kind):
                code = r'''
import json,sys,subprocess,pathlib
from unittest.mock import patch
from pc.adapter import Appium
from pc.qa_queue_stdio import adb_run
sys.path.insert(0,str(pathlib.Path.cwd().parent/'p2-proxy-relay'))
from device_resources import OwnedReverse
original=subprocess.run
def reader(command,**kw):
    return original([sys.executable,'-c','import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'],**kw)
kind=sys.argv[1]
with patch('subprocess.run',reader):
    if kind=='adapter': observed=Appium('SYNTHETIC','dev.finsec.qa.network','http://127.0.0.1:1').adb('shell','echo')
    elif kind=='fixture': observed=adb_run('unused','SYNTHETIC','shell','echo').decode()
    else: observed=OwnedReverse('unused','SYNTHETIC',45000,runner=reader).command('--list').stdout
print(json.dumps([observed,sys.stdin.read()]))
'''
                result=subprocess.run([sys.executable,'-c',code,kind],input='protocol-request\n',text=True,capture_output=True,timeout=10,check=True)
                self.assertEqual(json.loads(result.stdout),['','protocol-request\n'])

    def test_explicit_receipt_input_uses_its_own_pipe(self):
        from unittest.mock import patch
        from pc.qa_queue_stdio import adb_run
        original=subprocess.run
        def reader(command,**kw):
            return original([sys.executable,'-c','import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'],**kw)
        with patch('subprocess.run',reader):
            self.assertEqual(adb_run('unused','SYNTHETIC',input=b'synthetic receipt'),b'synthetic receipt')
