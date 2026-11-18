import base64,hashlib,json,sqlite3,unittest
from contextlib import closing
from pathlib import Path
import test_artifact_reader as fixture_module
from integration.artifact_reader import read_artifacts
from integration.packet_access import PacketGrant
from integration.supervisor import StructureSupervisor

class PacketAccessTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture_module.ArtifactTests.asyncSetUp
    def set_message(self,raw=b'QA REQUEST',original=None,incomplete=False,direction='request'):
        original=raw if original is None else original
        with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as c:
            data=json.loads(c.execute('SELECT data FROM packets').fetchone()[0])
            data['incomplete']=incomplete
            data[direction]=dict(stored_size=len(raw),size=len(original),truncated=len(raw)!=len(original),
                stored_sha256=hashlib.sha256(raw).hexdigest(),sha256=hashlib.sha256(original).hexdigest())
            c.execute('UPDATE packets SET data=?,'+direction+'=?',(json.dumps(data),raw))
    def grant(self,limit=65536):
        digest=hashlib.sha256(self.files['packets'].read_bytes()).hexdigest()
        return PacketGrant(self.files['packets'],'synthetic-common','synthetic-network',digest,lambda:None,limit)
    async def test_binary_request_response_and_empty(self):
        for side,raw in (('request',b'\x00\xff\x80QA'),('response',b'')):
            self.set_message(raw,direction=side);result=self.grant().read('synthetic-common','synthetic-packet',side)
            self.assertTrue(result['complete']);self.assertEqual(base64.b64decode(result['data']),raw)
    async def test_capture_and_delivery_partial(self):
        self.set_message(b'QA',b'QA COMPLETE')
        result=self.grant().read('synthetic-common','synthetic-packet','request')
        self.assertEqual(result['status'],'partial');self.assertTrue(result['capture_truncated'])
        self.set_message(b'123456')
        result=self.grant(limit=3).read('synthetic-common','synthetic-packet','request')
        self.assertEqual(base64.b64decode(result['data']),b'123');self.assertTrue(result['delivery_truncated'])
        self.set_message(incomplete=True)
        self.assertTrue(self.grant().read('synthetic-common','synthetic-packet','request')['packet_incomplete'])
    async def test_missing_corrupt_changed_and_oversize(self):
        self.set_message();g=self.grant()
        self.assertEqual(g.read('synthetic-common','absent','request')['status'],'missing')
        with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as c:c.execute('UPDATE packets SET request=?',(b'corruption',))
        self.assertEqual(g.read('synthetic-common','synthetic-packet','request')['status'],'artifact_changed')
        self.assertEqual(self.grant().read('synthetic-common','synthetic-packet','request')['status'],'corrupt')
        with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as c:c.execute('UPDATE packets SET request=NULL')
        self.assertEqual(self.grant().read('synthetic-common','synthetic-packet','request')['status'],'missing')
        self.set_message(b'x'*1048577)
        self.assertEqual(self.grant().read('synthetic-common','synthetic-packet','request')['status'],'limit')
    async def test_record_isolation_revocation_and_call_budget(self):
        self.set_message();g=self.grant()
        self.assertEqual(g.read('synthetic-other','synthetic-packet','request')['status'],'denied')
        with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as c:
            c.execute("UPDATE packets SET recording_id='synthetic-other'")
        self.assertEqual(self.grant().read('synthetic-common','synthetic-packet','request')['status'],'missing')
        g=self.grant()
        for _ in range(20):g.read('synthetic-common','absent','request')
        self.assertEqual(g.read('synthetic-common','absent','request')['status'],'limit')
        g.revoke();self.assertEqual(g.read('synthetic-common','absent','request')['status'],'expired')
    async def test_selected_agent_access_and_private_result(self):
        self.set_message(b'PRIVATE_SYNTHETIC_BYTES')
        skills=self.root/'skills';retained=[];seen=[]
        for item in ('first','second'):
            p=skills/item/'common'/'SKILL.md';p.parent.mkdir(parents=True);p.write_text('MOCK')
        test=self
        class Executor:
            async def run(_,context,progress):
                rid=context['recording_context']['recording_id'];read=context['read_packet']
                if retained:test.assertEqual(retained[0](rid,'synthetic-packet','request')['status'],'expired')
                retained.append(read);seen.append(read(rid,'synthetic-packet','request'))
                progress();return {'execution_status':'completed'}
        result=await StructureSupervisor(self.root/'runs',skills,Executor()).run(['first','second'],artifact_files=self.files)
        self.assertEqual(result['execution_status'],'completed');self.assertEqual(len(seen),2)
        self.assertTrue(all(base64.b64decode(r['data'])==b'PRIVATE_SYNTHETIC_BYTES' for r in seen))
        self.assertEqual([r['packet_access_statuses'] for r in result['items']],[['complete'],['complete']])
        serialized=json.dumps(result)
        self.assertNotIn('PRIVATE_SYNTHETIC_BYTES',serialized)
        self.assertNotIn(base64.b64encode(b'PRIVATE_SYNTHETIC_BYTES').decode(),serialized)
    async def test_total_delivery_and_audit_budgets(self):
        self.set_message(b'x'*65536);g=self.grant()
        for _ in range(4):
            self.assertEqual(g.read('synthetic-common','synthetic-packet','request')['delivered_size'],65536)
        self.assertEqual(g.read('synthetic-common','synthetic-packet','request')['status'],'limit')
        for _ in range(100):g.read('synthetic-other','synthetic-packet','request')
        self.assertEqual(len(g.audit),50)
