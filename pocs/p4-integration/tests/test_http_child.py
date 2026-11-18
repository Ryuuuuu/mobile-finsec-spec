import http.client,json,socket,sys,tempfile,time,unittest
from pathlib import Path
from integration.http_child_launcher import HTTPChild
from test_mock_stdio import request


def message(op,args):
    return dict(contract='mock-ui-request.v1',project_id='synthetic-http',
                request_generation=1,operation=op,arguments=args)


class HTTPChildTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def child(self,code=None):
        argv=None if code is None else [sys.executable,'-c',code,str(self.root)]
        child=HTTPChild(self.root,argv=argv);self.addCleanup(child.close);return child

    def test_bootstrap_flow_token_rotation_and_history(self):
        child=self.child();secret=child.ready['token']
        self.assertNotIn(secret,str(child.process.args))
        jid=child.exchange(message('submit',{'request':request()}))['data']['execution_id']
        deadline=time.monotonic()+3
        while True:
            state=child.exchange(message('progress',{'execution_id':jid,'cursor':0}))
            if state['execution']['status']=='finished':break
            self.assertLess(time.monotonic(),deadline)
        rid=state['run_id'];self.assertEqual(child.exchange(message('result',{'run_id':rid}))['status'],'ok')
        cleanup=child.close();self.assertEqual(cleanup['exit_code'],0)
        for file in self.root.rglob('*'):
            if file.is_file():self.assertNotIn(secret.encode(),file.read_bytes())
        restarted=self.child();self.assertNotEqual(secret,restarted.ready['token'])
        connection=http.client.HTTPConnection('127.0.0.1',restarted.ready['port'],timeout=2)
        try:
            connection.request('POST','/v1/ui',b'{}',headers={'Authorization':'Bearer '+secret})
            self.assertEqual(connection.getresponse().status,401)
        finally:connection.close()
        self.assertEqual(restarted.exchange(message('submit',{'request':request()}))['data']['status'],'recovery_required')
        self.assertEqual(restarted.exchange(message('result',{'run_id':rid}))['status'],'ok')

    def test_eof_shutdown_during_task_and_incomplete_http(self):
        code='''import asyncio,sys
from pathlib import Path
import integration.mock_stdio as factory
from integration.mock_http_child import serve
original=factory.StructureSupervisor
class Blocking:
 async def run(self,context,progress):
  await asyncio.Event().wait()
factory.StructureSupervisor=lambda root,skills:original(root,skills,Blocking())
raise SystemExit(asyncio.run(serve(Path(sys.argv[1]))))
'''
        child=self.child(code)
        jid=child.exchange(message('submit',{'request':request()}))['data']['execution_id']
        state=child.exchange(message('progress',{'execution_id':jid,'cursor':0}))
        self.assertEqual(state['execution']['status'],'in_progress')
        sock=socket.create_connection(('127.0.0.1',child.ready['port']),timeout=2)
        try:
            sock.sendall(b'POST /v1/ui HTTP/1.1\r\n')
            cleanup=child.close();self.assertEqual(cleanup['exit_code'],0);self.assertFalse(cleanup['forced'])
            self.assertEqual(sock.recv(1),b'')
        finally:sock.close()
        results=list((self.root/'runs').glob('synthetic-*/result.json'))
        self.assertEqual(len(results),1)
        self.assertEqual(json.loads(results[0].read_text())['execution_status'],'cancelled')

    def test_abrupt_exit_preserves_admission(self):
        child=self.child()
        self.assertEqual(child.exchange(message('submit',{'request':request()}))['data']['status'],'accepted')
        child.process.kill();child.process.wait(timeout=3);child.close()
        restarted=self.child()
        self.assertEqual(restarted.exchange(message('submit',{'request':request()}))['data']['status'],'recovery_required')
