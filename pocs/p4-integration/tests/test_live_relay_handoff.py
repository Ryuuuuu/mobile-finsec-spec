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
from integration.packet_access import PacketGrant


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

    async def request(self,path,body=b'QA HANDOFF'):
        reader,writer=await asyncio.open_connection('127.0.0.1',self.relay.port)
        try:
            writer.write(p2_fixture.request_bytes(path,body));await writer.drain()
            await asyncio.wait_for(reader.read(),3)
        finally:writer.close();await writer.wait_closed()

    async def capture(self,path,body=b'QA HANDOFF',seal=True):
        await asyncio.to_thread(self.combined.start)
        await asyncio.to_thread(self.engine.record_action,p1_fixture.tap())
        await self.request(path,body)
        if self.lose_stop:
            with self.assertRaises(TimeoutError):await asyncio.to_thread(self.combined.finish)
        else:await asyncio.to_thread(self.combined.finish)
        if seal:await self.relay.close()  # Offline reader requires sealed storage, not a live writer.
        self.files=dict(link=self.engine.j.path/'combined-link.json',
                        route=self.engine.j.path/'route.json',packets=self.db)
        return read_artifacts(**dict(link_path=self.files['link'],route_path=self.files['route'],db_path=self.db))

    def read_files(self,files):
        return read_artifacts(link_path=files['link'],route_path=files['route'],db_path=files['packets'])

    async def test_stop_ack_is_not_storage_seal(self):
        summary,payload=await self.capture('/normal',seal=False)
        self.assertEqual(summary['link_status'],'complete')
        self.assertEqual(summary['packet_status'],'unsealed')
        self.assertEqual(payload['packets'],[])
        await self.relay.close()
        summary,payload=self.read_files(self.files)
        self.assertEqual(summary['packet_status'],'complete')
        self.assertEqual(len(payload['packets']),1)
        self.assertEqual((await self.handoff())['packet_status'],'complete')

    async def test_two_recordings_share_store_without_crossing_barriers(self):
        await self.request('/before',b'QA OUTSIDE BEFORE')
        await self.capture('/first',b'QA FIRST',seal=False)
        first=dict(self.files)
        await self.request('/between',b'QA OUTSIDE BETWEEN')
        await self.capture('/second',b'QA SECOND',seal=False)
        second=dict(self.files)
        await self.request('/after',b'QA OUTSIDE AFTER')
        await self.relay.close()
        records=[self.read_files(files) for files in (first,second)]
        self.assertNotEqual(records[0][0]['recording_id'],records[1][0]['recording_id'])
        for index,(summary,payload) in enumerate(records):
            self.assertEqual(summary['packet_status'],'complete')
            self.assertEqual(summary['packet_count'],1)
            self.assertEqual(summary['route_count'],1)
            grant=PacketGrant(self.db,summary['recording_id'],payload['network_recording_id'],
                              summary['source_hashes']['packets'],lambda:None)
            own=payload['packets'][0]['packet_id']
            other=records[1-index][1]['packets'][0]['packet_id']
            raw=base64.b64decode(grant.read(summary['recording_id'],own,'request')['data'])
            self.assertIn((b'QA FIRST',b'QA SECOND')[index],raw)
            self.assertNotIn((b'QA SECOND',b'QA FIRST')[index],raw)
            self.assertNotIn(b'QA OUTSIDE',raw)
            self.assertEqual(grant.read(summary['recording_id'],other,'request')['status'],'missing')
            self.assertEqual(grant.read(records[1-index][0]['recording_id'],other,'request')['status'],'denied')
            grant.revoke()
        self.assertEqual(self.stop_calls,2)
        self.assertEqual(len(self.up.received),5)  # Outside-barrier traffic was forwarded, not captured.

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
