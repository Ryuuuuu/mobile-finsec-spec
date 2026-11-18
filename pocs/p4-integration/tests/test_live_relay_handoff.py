"""Real P1 engine/barriers + P2 loopback relay; device adapter alone is fake."""
import asyncio,base64,importlib.util,json,tempfile,unittest
from pathlib import Path
from uuid import uuid4
import test_artifact_reader as files_fixture  # Existing P1/P2 source-path setup.
from pc.core import Engine
from pc.combined import CombinedRun
from relay import Config,Relay
from integration.artifact_reader import read_artifacts
from integration.structure_supervisor import StructureSupervisor


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


BASE=Path(__file__).resolve().parents[2]
p1_fixture=load('p4_real_p1_fixture',BASE/'p1-record-replay/tests/test_core.py')
p2_fixture=load('p4_real_p2_fixture',BASE/'p2-proxy-relay/tests/test_relay.py')


class LiveRelayHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.up=p2_fixture.Upstream();await self.up.start()
        self.addAsyncCleanup(self.up.close)
        self.db=self.root/'packets.sqlite'
        self.relay=Relay(Config(db=self.db,upstream_port=self.up.port,io_timeout=.5))
        await self.relay.start();self.addAsyncCleanup(self.relay.close)
        await self.relay.command({'schema_version':1,'command_id':'on','command':'ON'})
        self.loop=asyncio.get_running_loop();self.stop_calls=0;self.lose_stop=False
        test=self
        class Network:
            def command(_,operation,**kwargs):
                if operation=='STOP':test.stop_calls+=1
                future=asyncio.run_coroutine_threadsafe(test.relay.command(dict(
                    schema_version=1,command_id=uuid4().hex,command=operation,**kwargs)),test.loop)
                reply=future.result(timeout=3)
                if not reply['ok']:raise RuntimeError('MOCK_COMMAND_FAILED')
                if operation=='STOP' and test.lose_stop:raise TimeoutError('synthetic lost STOP reply')
                return reply['result']
        self.engine=Engine(p1_fixture.Fake(),self.root/'input')
        self.combined=CombinedRun(self.engine,Network(),self.root/'combined')

    async def capture(self,path):
        await asyncio.to_thread(self.combined.start)
        await asyncio.to_thread(self.engine.record_action,p1_fixture.tap())
        reader,writer=await asyncio.open_connection('127.0.0.1',self.relay.port)
        try:
            writer.write(p2_fixture.request_bytes(path,b'QA HANDOFF'));await writer.drain()
            await asyncio.wait_for(reader.read(),3)
        finally:writer.close();await writer.wait_closed()
        if self.lose_stop:
            with self.assertRaises(TimeoutError):await asyncio.to_thread(self.combined.finish)
        else:await asyncio.to_thread(self.combined.finish)
        await self.relay.close()  # Offline reader requires sealed storage, not a live writer.
        self.files=dict(link=self.engine.j.path/'combined-link.json',
                        route=self.engine.j.path/'route.json',packets=self.db)
        return read_artifacts(**dict(link_path=self.files['link'],route_path=self.files['route'],db_path=self.db))

    async def handoff(self):
        skills=self.root/'skills';p=skills/'handoff'/'common'/'SKILL.md'
        p.parent.mkdir(parents=True);p.write_text('OPAQUE MOCK',encoding='utf-8');seen=[]
        class Observer:
            async def run(_,context,progress):
                data=context['artifact_data'];summary=context['recording_context']
                read=context['read_packet'](summary['recording_id'],data['packets'][0]['packet_id'],'request')
                seen.append((summary,len(data['actions']),base64.b64decode(read['data'])))
                progress();return {'execution_status':'completed'}
        result=await StructureSupervisor(self.root/'runs',skills,Observer()).run(['handoff'],artifact_files=self.files)
        self.assertEqual(result['execution_status'],'completed')
        self.assertIn(b'QA HANDOFF',seen[0][2]);self.assertEqual(seen[0][1],1)
        self.assertNotIn('QA HANDOFF',json.dumps(result))
        return seen[0][0]

    async def test_normal_capture_to_structural_handoff(self):
        summary,_=await self.capture('/normal')
        self.assertEqual((summary['link_status'],summary['route_status'],summary['packet_status']),('complete','complete','complete'))
        self.assertEqual((await self.handoff())['packet_status'],'complete')
        self.assertEqual(self.stop_calls,1)

    async def test_real_short_response_stays_partial(self):
        summary,_=await self.capture('/short-response')
        self.assertEqual(summary['packet_status'],'partial')
        self.assertEqual((await self.handoff())['packet_status'],'partial')
        link=json.loads(self.files['link'].read_text());self.assertEqual(link['status'],'partial')

    async def test_lost_stop_ack_does_not_retry_or_complete(self):
        self.lose_stop=True;summary,_=await self.capture('/normal')
        self.assertEqual(self.stop_calls,1)
        link=json.loads(self.files['link'].read_text())
        self.assertEqual(link['status'],'partial');self.assertTrue(link['network_stop_uncertain'])
        self.assertEqual(summary['route_status'],'partial')
        delivered=await self.handoff();self.assertEqual(delivered['route_status'],'partial')
        self.assertEqual(self.stop_calls,1)
