import asyncio,base64,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
from copy import deepcopy
from contextlib import closing
from integration.artifact_reader import read_artifacts
from integration.supervisor import StructureSupervisor
BASE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(BASE/'p2-proxy-relay'))
sys.path.insert(0,str(BASE/'p1-record-replay'))
from relay import Store
from pc.core import atomic

class ArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.files={k:self.root/n for k,n in (('link','combined-link.json'),('route','route.json'),('packets','packets.sqlite'))}
        self.link=dict(combined_id='synthetic-combined',input_recording_id='synthetic-input',network_recording_id='synthetic-network',status='completed')
        self.route=dict(schema_version=1,recording_id='synthetic-input',status='completed',device_id='synthetic-device',
            package_id='dev.finsec.poc',target=dict(version_code='1',version_name='1.0',apk_sha256='a'*64),
            initial={'id':'dev.finsec.poc:id/initial_state','text':'reset:0::'},secure='secure:off',network_coverage='none',
            actions=[dict(action_id='synthetic-action',action=dict(type='wait',timeout=1,post={'id':'dev.finsec.poc:id/screen_state','text':'SYNTHETIC_SCREEN'}))])
        atomic(self.files['link'],self.link);atomic(self.files['route'],self.route)
        self.record=dict(schema_version=1,recording_id='synthetic-network',session_id='synthetic-session',run_id=None,
            status='completed',network_coverage='complete_for_supported_scope',persisted_packets=1,gaps=[],
            attribution=dict(app_id='dev.finsec.poc',device_id='synthetic-device',confidence='unverified'))
        packet=dict(schema_version=1,packet_id='synthetic-packet',recording_id='synthetic-network',sequence=1,
            timestamp='2026-11-18T00:00:00Z',kind='http',protocol='HTTP/1.1',incomplete=False,error=None,
            request=dict(raw_base64=base64.b64encode(b'GET /synthetic HTTP/1.1\r\n\r\n').decode(),method='GET',target='/synthetic'),
            response=dict(raw_base64=base64.b64encode(b'HTTP/1.1 200 OK\r\n\r\n').decode(),status=200))
        store=Store(self.files['packets']);await store.start()
        try:await store.record(self.record);await store.packet(packet)
        finally:await store.close()
    def read(self):return read_artifacts(self.files['link'],self.files['route'],self.files['packets'])
    async def test_actual_serializers_and_agent_handoff(self):
        summary,data=self.read()
        self.assertEqual((summary['route_status'],summary['packet_status']),('complete','complete'))
        self.assertEqual(data['packets'][0]['request']['target'],'/synthetic')
        self.assertNotIn('raw_base64',json.dumps(data))
        seen=[];skills=self.root/'skills'
        for item in ('first','second'):
            p=skills/item/'common'/'SKILL.md';p.parent.mkdir(parents=True);p.write_text('MOCK')
        class Executor:
            async def run(_,context,progress):
                seen.append(deepcopy(context));context['artifact_data']['actions'].clear()
                progress();return {'execution_status':'completed'}
        result=await StructureSupervisor(self.root/'runs',skills,Executor()).run(['first','second'],artifact_files=self.files)
        self.assertEqual([len(c['artifact_data']['actions']) for c in seen],[1,1])
        saved=json.loads((self.root/'runs'/result['run_id']/'result.json').read_text())
        self.assertEqual(saved,result);self.assertNotIn('SYNTHETIC_SCREEN',json.dumps(saved))
        self.assertNotIn('/synthetic',json.dumps(saved));self.assertNotIn('verdict',json.dumps(saved))
    async def test_versions(self):
        self.route['schema_version']=99;atomic(self.files['route'],self.route)
        self.assertEqual(self.read()[0]['route_status'],'unsupported_version')
        with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as c:c.execute('PRAGMA user_version=99')
        self.assertEqual(self.read()[0]['packet_status'],'unsupported_version')
    async def test_partial_route_and_collection(self):
        self.route.update(status='incomplete',actions=[]);atomic(self.files['route'],self.route)
        self.record.update(status='interrupted',network_coverage='partial')
        with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as c:c.execute('UPDATE recordings SET data=?',(json.dumps(self.record),))
        summary,data=self.read()
        self.assertEqual((summary['route_status'],summary['packet_status']),('partial','partial'))
        self.assertEqual(data['actions'],[])
    async def test_packet_sequence_gap_is_partial_even_if_record_claims_complete(self):
        with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as c:
            raw=c.execute('SELECT data FROM packets').fetchone()[0];packet=json.loads(raw);packet['sequence']=3
            c.execute('UPDATE packets SET sequence=3,data=?',(json.dumps(packet),))
        summary,data=self.read()
        self.assertEqual(summary['packet_status'],'partial')
        self.assertEqual([p['sequence'] for p in data['packets']],[3])

    async def test_invalid_or_duplicate_packet_sequence_still_corrupt(self):
        with closing(sqlite3.connect(self.files['packets'])) as c:
            original=json.loads(c.execute('SELECT data FROM packets').fetchone()[0])
        for sequence in (0,-1,True,'1'):
            packet=dict(original,sequence=sequence)
            with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as c:
                c.execute('UPDATE packets SET sequence=?,data=?',(sequence,json.dumps(packet)))
            self.assertEqual(self.read()[0]['packet_status'],'corrupt')
        with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as c:
            c.execute('UPDATE packets SET sequence=1,data=?',(json.dumps(original),))
            duplicate=dict(original,packet_id='synthetic-duplicate')
            c.execute('INSERT INTO packets SELECT ?,recording_id,sequence,?,request,response FROM packets',
                      ('synthetic-duplicate',json.dumps(duplicate)))
        self.assertEqual(self.read()[0]['packet_status'],'corrupt')

    async def test_missing_and_corrupt(self):
        self.files['route'].unlink();self.assertEqual(self.read()[0]['route_status'],'missing')
        self.files['route'].write_text('{');self.assertEqual(self.read()[0]['route_status'],'corrupt')
        self.files['packets'].unlink();self.assertEqual(self.read()[0]['packet_status'],'missing')
        self.files['packets'].write_bytes(b'not sqlite');self.assertEqual(self.read()[0]['packet_status'],'corrupt')
        self.files['link'].unlink();self.assertEqual(self.read()[0]['link_status'],'missing')
    async def test_id_mismatch_and_missing_packet_rows(self):
        self.route['recording_id']='wrong';atomic(self.files['route'],self.route)
        self.assertEqual(self.read()[0]['route_status'],'corrupt')
        with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as c:c.execute('DELETE FROM packets')
        self.assertEqual(self.read()[0]['packet_status'],'partial')
    async def test_unsealed_sqlite_rejected(self):
        Path(str(self.files['packets'])+'-wal').write_bytes(b'synthetic')
        self.assertEqual(self.read()[0]['packet_status'],'unsealed')
    async def test_v2_general_app_route(self):
        self.route.update(schema_version=2,package_id='qa.synthetic.app',secure='unknown',
            target=dict(version_code='1',version_name='1.0',apk_sha256s={'base.apk':'a'*64}),
            initial={'id':'qa.synthetic.app:id/home'})
        self.route['actions'][0]['action']['post']={'id':'qa.synthetic.app:id/home'}
        atomic(self.files['route'],self.route)
        self.record['attribution']['app_id']='qa.synthetic.app'
        with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as c:c.execute('UPDATE recordings SET data=?',(json.dumps(self.record),))
        self.assertEqual(self.read()[0]['route_status'],'complete')
