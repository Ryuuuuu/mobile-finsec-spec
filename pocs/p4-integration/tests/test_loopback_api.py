import asyncio,json,unittest
import test_integrated_structure as fixture
from integration.ui_bridge import UIBridge
from integration.ui_wire import UIWire,LIMIT
from integration.loopback_api import LoopbackAPI


class LoopbackTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.IntegratedFlowTests.asyncSetUp
    api=fixture.IntegratedFlowTests.api
    request=fixture.IntegratedFlowTests.request

    async def service(self):
        api=self.api();server=LoopbackAPI(UIWire(UIBridge('mock',api)))
        await server.start();self.addAsyncCleanup(server.close)
        return api,server

    def body(self,op,args):
        return json.dumps(dict(contract='mock-ui-request.v1',project_id='mock',
            request_generation=1,operation=op,arguments=args)).encode()

    async def call(self,s,body,changes=None,extra='',send_body=True):
        headers={'Host':f'127.0.0.1:{s.port}','Authorization':'Bearer '+s.token,
            'X-Request-ID':'request-1','X-API-Version':'mock-loopback.v1',
            'Content-Type':'application/json','Content-Length':str(len(body))}
        headers.update(changes or {})
        raw=b'POST /v1/ui HTTP/1.1\r\n'+''.join(f'{k}: {v}\r\n' for k,v in headers.items()).encode()+extra.encode()+b'\r\n'
        reader,writer=await asyncio.open_connection('127.0.0.1',s.port)
        try:
            writer.write(raw+(body if send_body else b''));await writer.drain()
            response=await asyncio.wait_for(reader.read(),3)
            head,data=response.split(b'\r\n\r\n',1)
            return int(head.split()[1]),json.loads(data)
        finally:writer.close();await writer.wait_closed()

    async def test_authenticated_flow_and_request_correlation(self):
        api,s=await self.service()
        code,reply=await self.call(s,self.body('recording',{'ref':'qa-record'}))
        self.assertEqual(code,200);self.assertEqual(reply['request_id'],'request-1')
        self.assertEqual(reply['payload']['recording']['packet_status'],'complete')
        _,reply=await self.call(s,self.body('submit',{'request':self.request()}))
        jid=reply['payload']['data']['execution_id'];await api.wait(jid)
        _,duplicate=await self.call(s,self.body('submit',{'request':self.request()}),{'X-Request-ID':'request-2'})
        self.assertEqual(duplicate['request_id'],'request-2')
        self.assertEqual(duplicate['payload']['data']['execution_id'],jid)
        _,history=await self.call(s,self.body('history',{}))
        self.assertEqual(len(history['payload']['runs']),1)

    async def test_auth_rotation_version_and_host_rejection(self):
        api,s=await self.service();old=s.token
        for headers,status in (({'Authorization':'Bearer wrong'},401),({'X-API-Version':'old'},400),
                               ({'Host':'remote.example'},403),({'Origin':'https://example.com'},403)):
            code,reply=await self.call(s,self.body('submit',{'request':self.request()}),headers)
            self.assertEqual(code,status);self.assertEqual(reply['payload']['outcome'],'not_dispatched')
            self.assertNotIn(old,json.dumps(reply))
        self.assertEqual(api.jobs,{})
        await s.close();await s.start();self.assertNotEqual(old,s.token)
        code,_=await self.call(s,self.body('history',{}),{'Authorization':'Bearer '+old})
        self.assertEqual(code,401)

    async def test_invalid_body_version_and_json_keep_correlation(self):
        api,s=await self.service()
        bad=json.loads(self.body('history',{}));bad['contract']='unsupported'
        for body in (json.dumps(bad).encode(),b'{'):
            code,reply=await self.call(s,body,{'X-Request-ID':'bad-body'})
            self.assertEqual(code,200)  # Transport succeeded; payload explicitly failed.
            self.assertEqual(reply['request_id'],'bad-body')
            self.assertIn('error',reply['payload'])
        code,reply=await self.call(s,b'{}',{'X-Padding':'x'*9000})
        self.assertEqual(code,400);self.assertEqual(api.jobs,{})

    async def test_bounds_framing_and_body_deadline(self):
        api,s=await self.service()
        cases=[({'Content-Length':str(LIMIT+1)},'',413),
               ({},'Content-Length: 0\r\n',400),({'Transfer-Encoding':'chunked'},'',400),
               ({'X-Request-ID':'invalid id'},'',400)]
        for headers,extra,status in cases:
            code,_=await self.call(s,b'{}',headers,extra,send_body=False)
            self.assertEqual(code,status)
        code,reply=await self.call(s,b'{}',send_body=False)
        self.assertEqual(code,400);self.assertEqual(reply['payload']['outcome'],'not_dispatched')
        self.assertEqual(api.jobs,{})

    async def test_close_incomplete_connection_without_admission(self):
        api,s=await self.service()
        reader,writer=await asyncio.open_connection('127.0.0.1',s.port)
        writer.write(b'POST /v1/ui HTTP/1.1\r\n');await writer.drain();await asyncio.sleep(.02)
        await s.close()
        self.assertEqual(await asyncio.wait_for(reader.read(),2),b'')
        self.assertEqual(api.jobs,{});self.assertEqual(s.tasks,set())
        writer.close();await writer.wait_closed()
