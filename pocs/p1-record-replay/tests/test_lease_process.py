"""Real child-process lease boundaries, isolated from user/device lease folders."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
SCRIPT=r'''
import json,pathlib,sys,time
from unittest.mock import patch
from pc.core import Lease
with patch('pathlib.Path.home',return_value=pathlib.Path(sys.argv[1])):
    lease=Lease('synthetic-process-boundary')
    try:lease.acquire()
    except RuntimeError:
        print(json.dumps({'state':'blocked'}),flush=True)
        sys.exit(0)
    if sys.argv[2]=='clean':
        lease.release(clean=True)
        print(json.dumps({'state':'clean'}),flush=True)
    else:
        if sys.argv[2]=='poison':lease.poison('synthetic uncertain cleanup')
        print(json.dumps({'state':'held'}),flush=True)
        time.sleep(60)
'''

class LeaseProcessTests(unittest.TestCase):
    def spawn(self,root,mode):
        return subprocess.Popen([sys.executable,'-u','-c',SCRIPT,str(root),mode],cwd=ROOT,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)

    def probe(self,root):
        child=self.spawn(root,'clean')
        try:
            stdout,stderr=child.communicate(timeout=5)
            self.assertEqual(child.returncode,0,stderr)
            self.assertEqual(stderr,'')
            return json.loads(stdout)['state']
        finally:
            if child.poll() is None:child.kill();child.communicate(timeout=5)

    def test_normal_child_exit_allows_fresh_process(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self.probe(root),'clean')
            self.assertEqual(self.probe(root),'clean')
            self.assertFalse(list(pathlib.Path(root).rglob('*.active')))
            self.assertFalse(list(pathlib.Path(root).rglob('*.quarantine')))

    def test_killed_owner_blocks_fresh_process_without_clearing_evidence(self):
        # Bound the readiness read; kill the owned child before joining on failure.
        import concurrent.futures
        for mode in ('held','poison'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as root:
                child=self.spawn(root,mode)
                try:
                    with concurrent.futures.ThreadPoolExecutor(1) as pool:
                        ready=pool.submit(child.stdout.readline)
                        try:self.assertEqual(json.loads(ready.result(timeout=5))['state'],'held')
                        except BaseException:
                            child.kill();raise
                    markers={p.name:p.read_bytes() for p in pathlib.Path(root).rglob('*') if p.suffix in ('.active','.quarantine')}
                    self.assertTrue(any(name.endswith('.active') for name in markers))
                    self.assertEqual(any(name.endswith('.quarantine') for name in markers),mode=='poison')
                    # A simultaneous independent client must also be blocked.
                    self.assertEqual(self.probe(root),'blocked')
                    child.kill();_,stderr=child.communicate(timeout=5)
                    self.assertEqual(stderr,'')
                    self.assertEqual(self.probe(root),'blocked')
                    self.assertEqual(markers,{p.name:p.read_bytes() for p in pathlib.Path(root).rglob('*') if p.suffix in ('.active','.quarantine')})
                finally:
                    if child.poll() is None:child.kill()
                    child.communicate(timeout=5)

if __name__=='__main__':unittest.main()
