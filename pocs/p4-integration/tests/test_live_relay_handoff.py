"""Real P1 engine/barriers + P2 loopback relay; device adapter alone is fake."""
import asyncio,base64,importlib.util,json,sqlite3,tempfile,threading,time,unittest
from unittest.mock import patch
from contextlib import closing
from pathlib import Path
from uuid import uuid4
import test_artifact_reader as files_fixture  # Existing P1/P2 source-path setup.
from pc.core import Engine
from pc.combined import CombinedRun
from relay import Config,Relay
from integration.artifact_reader import read_artifacts
from integration.structure_supervisor import StructureSupervisor
from integration.packet_access import PacketGrant
from integration import recording_snapshot
from integration import recording_bundle


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

    async def prepare_capture(self):
        await asyncio.to_thread(self.combined.start)
        await asyncio.to_thread(self.engine.record_action,p1_fixture.tap())
        await self.request('/normal')
        await self.relay.queue.join()
        self.files=dict(link=self.engine.j.path/'combined-link.json',
                        route=self.engine.j.path/'route.json',packets=self.db)

    def assert_partial_input(self):
        self.assertEqual(self.stop_calls,1)
        self.assertEqual(self.combined.state,'partial')
        self.assertEqual(self.engine.record['status'],'incomplete')
        self.assertTrue(self.combined.link['network_stop_uncertain'])

    async def test_cancel_during_replay_stop_keeps_input_success_but_combined_partial(self):
        await self.capture('/normal',seal=False)
        source=self.files['route'];saved=source.read_bytes();route=json.loads(saved)
        self.engine.a=p1_fixture.Fake();click=self.engine.a.click;test=self
        def network_click(element):
            click(element)
            asyncio.run_coroutine_threadsafe(test.request('/replay'),test.loop).result(3)
        self.engine.a.click=network_click
        network=self.combined.network
        class CancelOnStop:
            def command(_,operation,**kwargs):
                result=network.command(operation,**kwargs)
                if operation=='STOP':test.engine.stop_requested()
                return result
        self.combined.network=CancelOnStop()
        result=await asyncio.to_thread(self.combined.replay,route)
        self.assertEqual(result['status'],'incomplete');self.assertEqual(result['input_status'],'succeeded')
        self.assertEqual(json.loads((self.engine.j.path/'result.json').read_text())['status'],'succeeded')
        link=json.loads((self.engine.j.path/'combined-link.json').read_text())
        self.assertEqual(link['status'],'partial');self.assertTrue(link['cancel_requested'])
        self.assertEqual(link['network_stop']['network_coverage'],'complete_for_supported_scope')
        self.assertEqual(source.read_bytes(),saved)
        self.assertIsNone(self.relay.active_recording)

    async def test_relay_closed_before_input_stop_does_not_complete_input(self):
        await self.prepare_capture()
        await self.relay.close()  # Unexpected by P1, but orderly relay shutdown (not a kill).
        with self.assertRaises(RuntimeError):await asyncio.to_thread(self.combined.finish)
        self.assert_partial_input()
        self.assertEqual(self.read_files(self.files)[0]['packet_status'],'complete')
        summary=await self.handoff()
        self.assertEqual(summary['route_status'],'partial')
        self.assertEqual(summary['packet_status'],'complete')  # Relay shutdown did seal packet storage.

    async def test_stop_storage_failure_recovers_as_partial_without_losing_packet(self):
        await self.prepare_capture()
        with patch.object(self.relay.store,'_finalize_packets',side_effect=sqlite3.OperationalError('synthetic disk write failure')):
            with self.assertRaises(RuntimeError):await asyncio.to_thread(self.combined.finish)
        self.assert_partial_input()
        await self.relay.close()
        # Existing P2 restart recovery must interpret persisted recording/stopping as interrupted.
        recovered=Relay(Config(db=self.db,upstream_port=self.up.port))
        await recovered.start()
        try:
            rows=p2_fixture.query(self.db)['result']
            self.assertEqual(rows[0]['status'],'interrupted')
            self.assertEqual(rows[0]['network_coverage'],'partial')
            self.assertTrue(any(g['reason']=='process_interrupted' for g in rows[0]['gaps']))
        finally:await recovered.close()
        summary=await self.handoff()
        self.assertEqual(summary['route_status'],'partial');self.assertEqual(summary['packet_status'],'partial')

    async def test_stop_journal_failure_never_promotes_partial_input(self):
        await self.prepare_capture()
        with patch.object(self.relay.store,'_command_save',side_effect=sqlite3.OperationalError('synthetic command journal failure')):
            with self.assertRaises(RuntimeError):await asyncio.to_thread(self.combined.finish)
        self.assert_partial_input()
        await self.relay.close()
        summary=await self.handoff()
        self.assertEqual(summary['route_status'],'partial')
        self.assertEqual(summary['packet_status'],'complete')  # Packet seal committed before command journal failed.

    async def test_start_timeout_then_late_dispatch_cannot_create_recording(self):
        release=asyncio.Event();futures=[];network=self.combined.network;test=self
        class DelayedNetwork:
            def command(_,operation,**kwargs):
                if operation!='RECORD':return network.command(operation,**kwargs)
                async def delayed():
                    await release.wait()
                    return await test.relay.command(dict(schema_version=1,command_id='late-start',command='RECORD',**kwargs))
                future=asyncio.run_coroutine_threadsafe(delayed(),test.loop);futures.append(future)
                return future.result(timeout=.03)  # Controlled transport delay before actual dispatch.
        self.combined.network=DelayedNetwork()
        try:
            with self.assertRaises(TimeoutError):await asyncio.to_thread(self.combined.start)
        finally:release.set()
        reply=await asyncio.wrap_future(futures[0])
        self.assertEqual(reply['error'],'recording_cancelled')
        self.assertIsNone(self.relay.active_recording)
        self.assertEqual(self.stop_calls,1)
        self.assertTrue(self.combined.link['network_stop']['start_fenced'])
        self.assertEqual(self.engine.record['status'],'incomplete')
        self.assertNotIn('input_enabled',(self.combined.j.path/'events.jsonl').read_text())

    async def test_bundle_selects_one_record_and_detaches_sources(self):
        await self.capture('/normal',seal=False);first=dict(self.files)
        await self.capture('/second',b'QA OTHER',seal=False)
        bundles=self.root/'bundles';bundles.mkdir()
        self.files=await asyncio.to_thread(recording_bundle.publish_bundle,
                                          first['link'],first['route'],self.db,bundles)
        manifest=json.loads((self.files['link'].parent/'manifest.json').read_text())
        summary,_=self.read_files(self.files)
        self.assertEqual(manifest['recording_id'],summary['recording_id'])
        self.assertEqual(manifest['network_recording_id'],json.loads(first['link'].read_text())['network_recording_id'])
        self.assertEqual(summary['packet_count'],1)
        first['route'].write_text('source replaced',encoding='utf-8')
        self.assertEqual((await self.handoff())['packet_status'],'complete')
        self.assertEqual(len(list(bundles.iterdir())),1)
        self.assertEqual(self.relay.relay_state,'on')

    async def test_bundle_partial_state_and_foreign_route_rejection(self):
        await self.capture('/normal',seal=False);first=dict(self.files)
        await self.capture('/short-response',seal=False);second=dict(self.files)
        bundles=self.root/'bundles';bundles.mkdir()
        with self.assertRaisesRegex(ValueError,'BUNDLE_INVALID_ARTIFACTS'):
            await asyncio.to_thread(recording_bundle.publish_bundle,first['link'],second['route'],self.db,bundles)
        self.assertEqual(list(bundles.iterdir()),[])
        self.files=await asyncio.to_thread(recording_bundle.publish_bundle,
                                          second['link'],second['route'],self.db,bundles)
        self.assertEqual((await self.handoff())['packet_status'],'partial')

    async def test_bundle_source_change_and_export_failure_publish_nothing(self):
        await self.capture('/normal',seal=False)
        bundles=self.root/'bundles';bundles.mkdir();original=recording_bundle.export_recording
        def changed(*args):
            result=original(*args)
            with self.files['route'].open('ab') as stream:stream.write(b' ')
            return result
        with patch.object(recording_bundle,'export_recording',changed):
            with self.assertRaisesRegex(ValueError,'BUNDLE_SOURCE_CHANGED'):
                await asyncio.to_thread(recording_bundle.publish_bundle,
                                        self.files['link'],self.files['route'],self.db,bundles)
        self.assertEqual(list(bundles.iterdir()),[])
        def failed(*args):
            original(*args)
            raise OSError('synthetic publication failure')
        with patch.object(recording_bundle,'export_recording',failed):
            with self.assertRaises(OSError):
                await asyncio.to_thread(recording_bundle.publish_bundle,
                                        self.files['link'],self.files['route'],self.db,bundles)
        self.assertEqual(list(bundles.iterdir()),[])
        await self.request('/still-on')

    async def test_snapshot_while_second_recording_commits(self):
        await self.capture('/normal',seal=False)
        first=dict(self.files);rid=self.combined.link['network_recording_id']
        await asyncio.to_thread(self.combined.start)
        await asyncio.to_thread(self.engine.record_action,p1_fixture.tap())
        entered=threading.Event();release=threading.Event()
        original=recording_snapshot._copy_packets
        def paused(*args):
            entered.set()
            if not release.wait(3):raise TimeoutError('test barrier')
            return original(*args)
        output=self.root/'selected.sqlite'
        with patch.object(recording_snapshot,'_copy_packets',paused):
            task=asyncio.create_task(asyncio.to_thread(recording_snapshot.export_recording,self.db,output,rid))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait,2))
                await self.request('/second',b'QA EXCLUDED SECOND')
                await asyncio.to_thread(self.combined.finish)  # Real writes commit during source read transaction.
            finally:release.set()
            manifest=await task
        self.assertEqual(manifest['recording_id'],rid)
        self.assertEqual(self.relay.relay_state,'on');self.assertFalse(self.relay.closed)
        with closing(sqlite3.connect(output)) as conn:
            self.assertEqual(conn.execute('SELECT id FROM recordings').fetchall(),[(rid,)])
            self.assertEqual(conn.execute('SELECT count(*) FROM packets').fetchone()[0],1)
            self.assertNotIn(b'QA EXCLUDED SECOND',conn.execute('SELECT request FROM packets').fetchone()[0])
        self.files=dict(first,packets=output)
        self.assertEqual((await self.handoff())['packet_status'],'complete')
        await self.request('/still-on',b'QA OUTSIDE')

    async def test_snapshot_preserves_real_partial_capture(self):
        await self.capture('/short-response',seal=False)
        output=self.root/'partial.sqlite'
        await asyncio.to_thread(recording_snapshot.export_recording,self.db,output,self.combined.link['network_recording_id'])
        self.files['packets']=output
        self.assertEqual((await self.handoff())['packet_status'],'partial')
        self.assertEqual(self.relay.relay_state,'on')

    async def test_snapshot_rejects_active_and_does_not_overwrite(self):
        await asyncio.to_thread(self.combined.start)
        rid=self.combined.link['network_recording_id'];output=self.root/'selected.sqlite'
        with self.assertRaisesRegex(ValueError,'RECORDING_NOT_TERMINAL'):
            await asyncio.to_thread(recording_snapshot.export_recording,self.db,output,rid)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob('.snapshot-*')),[])
        output.write_bytes(b'KEEP')
        with self.assertRaises(FileExistsError):
            await asyncio.to_thread(recording_snapshot.export_recording,self.db,output,rid)
        self.assertEqual(output.read_bytes(),b'KEEP')
        self.assertIsNotNone(self.relay.active_recording)
        await asyncio.to_thread(self.combined.finish)

    async def test_snapshot_limit_timeout_leave_no_published_file(self):
        await self.capture('/normal',seal=False)
        rid=self.combined.link['network_recording_id'];output=self.root/'selected.sqlite'
        with self.assertRaisesRegex(ValueError,'SNAPSHOT_LIMIT'):
            await asyncio.to_thread(recording_snapshot.export_recording,self.db,output,rid,max_bytes=1)
        original=recording_snapshot._copy_packets
        def delayed(*args):
            time.sleep(.05)
            return original(*args)
        with patch.object(recording_snapshot,'_copy_packets',delayed):
            with self.assertRaises((TimeoutError,sqlite3.OperationalError)):
                await asyncio.to_thread(recording_snapshot.export_recording,self.db,output,rid,timeout=.03)
        self.assertFalse(output.exists());self.assertEqual(list(self.root.glob('.snapshot-*')),[])
        await self.request('/still-on')

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
