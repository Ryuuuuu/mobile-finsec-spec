import asyncio, json, unittest
from unittest.mock import patch
import test_integrated_structure as fixture
from integration.ui_bridge import UIBridge
from integration.ui_wire import UIWire, LIMIT


class WireTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.IntegratedFlowTests.asyncSetUp
    api = fixture.IntegratedFlowTests.api
    request = fixture.IntegratedFlowTests.request
    set_message = fixture.IntegratedFlowTests.set_message

    def call(self, wire, op, args, **changes):
        msg = dict(contract='mock-ui-request.v1', project_id='mock', request_generation=1,
                   operation=op, arguments=args)
        msg.update(changes)
        return json.loads(wire.exchange(json.dumps(msg).encode()))

    async def test_serialized_record_start_live_final(self):
        self.set_message(); entered=asyncio.Event(); release=asyncio.Event()
        class Executor:
            async def run(_, context, progress):
                entered.set(); await release.wait(); return {'execution_status':'completed'}
        api=self.api(Executor()); wire=UIWire(UIBridge('mock',api))
        self.assertEqual(self.call(wire,'recording',{'ref':'qa-record'})['recording']['packet_status'],'complete')
        self.assertTrue(self.call(wire,'inspect',{'request':self.request()})['data']['enabled'])
        reply=self.call(wire,'submit',{'request':self.request()})['data']; jid=reply['execution_id']
        await entered.wait()
        self.assertEqual(self.call(wire,'submit',{'request':self.request()})['data']['execution_id'],jid)
        live=self.call(wire,'progress',{'execution_id':jid,'cursor':0})
        self.assertTrue(live['events']); self.assertEqual(self.call(wire,'history',{})['runs'],[])
        release.set(); final=await api.wait(jid)
        self.assertEqual(len(self.call(wire,'history',{})['runs']),1)
        detail=self.call(wire,'result',{'run_id':final['run_id']})
        self.assertEqual(detail['status'],'ok'); self.assertNotIn('events',detail['result'])

    async def test_rejection_and_bounded_failure(self):
        bridge=UIBridge('mock',self.api()); wire=UIWire(bridge)
        for changes in ({'contract':'v999'},{'project_id':'other'},{'request_generation':True}):
            self.assertIn('error',self.call(wire,'history',{},**changes))
        for raw in (b'{',b'{"x":1,"x":2}',b'x'*(LIMIT+1),b'null'):
            self.assertIn('error',json.loads(wire.exchange(raw)))
        self.assertIn('error',self.call(wire,'result',{'path':'outside'}))
        with patch.object(bridge,'history',return_value={'large':'x'*LIMIT}):
            self.assertEqual(self.call(wire,'history',{})['error'],'RESPONSE_LIMIT')
        with patch.object(bridge,'history',side_effect=OSError('PRIVATE')):
            reply=self.call(wire,'history',{})
            self.assertEqual(reply['outcome'],'unknown'); self.assertNotIn('PRIVATE',str(reply))

    async def test_cancel_and_disconnected_history(self):
        entered=asyncio.Event()
        class Executor:
            async def run(_, context, progress): entered.set(); await asyncio.Event().wait()
        api=self.api(Executor());wire=UIWire(UIBridge('mock',api))
        jid=self.call(wire,'submit',{'request':self.request()})['data']['execution_id']
        await entered.wait()
        self.assertEqual(self.call(wire,'cancel',{'execution_id':jid})['data']['status'],'cancel_requested')
        self.assertEqual((await api.wait(jid))['execution_status'],'cancelled')
        api.inventory['devices']={}
        self.assertFalse(self.call(wire,'inspect',{'request':self.request('new')})['data']['enabled'])
        self.assertEqual(len(self.call(wire,'history',{})['runs']),1)
