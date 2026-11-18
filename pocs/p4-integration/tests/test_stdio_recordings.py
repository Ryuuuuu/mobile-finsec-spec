import hashlib,json,shutil,sqlite3,sys,time,unittest
from contextlib import closing
from pathlib import Path
import test_packet_access as fixture
from integration.stdio_client import StdioClient
from integration.recording_bundle import publish_bundle
from test_stdio_client import message
from test_mock_stdio import request

# Child-only observer verifies delivery, not skill content or an assessment.
OBSERVER = '''import asyncio,base64,hashlib,json,sys
from pathlib import Path
import integration.mock_stdio as worker
root=Path(sys.argv[1]);original=worker.StructureSupervisor
class Observer:
 async def run(self,context,progress):
  summary=context['recording_context'];data=context.get('artifact_data',{})
  receipt={'route_status':summary['route_status'],'packet_status':summary['packet_status'],
   'actions_sha256':hashlib.sha256(json.dumps(data.get('actions',[]),sort_keys=True).encode()).hexdigest()}
  if 'read_packet' in context and data.get('packets'):
   packet=data['packets'][0]['packet_id'];read=context['read_packet']
   actual=read(summary['recording_id'],packet,'request')
   receipt.update(read_status=actual['status'],request_sha256=hashlib.sha256(base64.b64decode(actual['data'])).hexdigest(),
    foreign_status=read('synthetic-other-recording',packet,'request')['status'])
  with (root/'receipts.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(receipt)+'\\n')
  progress();return {'execution_status':'completed'}
worker.StructureSupervisor=lambda root,skills:original(root,skills,Observer())
asyncio.run(worker.serve(root))
'''


class RecordingProcessTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.fixture_module.ArtifactTests.asyncSetUp
    set_message = fixture.PacketAccessTests.set_message

    def bundle(self):
        root=self.root/'recordings';root.mkdir(exist_ok=True)
        files=publish_bundle(self.files['link'],self.files['route'],self.files['packets'],root)
        return files,files['link'].parent.name

    async def test_refresh_discovers_new_bundle_and_excludes_staging_and_corruption(self):
        self.set_message(b'QA LATE BUNDLE');c=self.child()
        self.assertEqual(c.exchange(message('recordings',{}))['recordings'],[])
        files,ref=self.bundle()
        (self.root/'recordings'/'.bundle-preparing').mkdir()
        listing=c.exchange(message('recordings',{}))
        self.assertEqual(listing['status'],'ok')
        self.assertEqual([(r['ref'],r['selectable']) for r in listing['recordings']],[(ref,True)])
        self.run_ref(c,ref)
        files['packets'].unlink()
        listing=c.exchange(message('recordings',{}))
        self.assertEqual(listing['recordings'][0]['selectable'],False)
        r=request();r.update(command_id='after-refresh',recording_ref=ref)
        self.assertEqual(c.exchange(message('submit',{'request':r}))['data']['status'],'not_run')
        self.assertEqual(len(c.exchange(message('history',{}))['runs']),1)

    async def test_refresh_scan_failure_clears_stale_selection_then_recovers(self):
        self.set_message(b'QA REFRESH');files,ref=self.bundle();c=self.child()
        self.assertTrue(c.exchange(message('recordings',{}))['recordings'][0]['selectable'])
        invalid=self.root/'recordings'/'invalid.name';invalid.mkdir()
        reply=c.exchange(message('recordings',{}))
        self.assertEqual(reply['status'],'unavailable')
        r=request();r.update(command_id='stale-refresh',recording_ref=ref)
        self.assertEqual(c.exchange(message('submit',{'request':r}))['data']['status'],'not_run')
        invalid.rmdir()
        self.assertTrue(c.exchange(message('recordings',{}))['recordings'][0]['selectable'])
        self.run_ref(c,ref)

    async def test_published_partial_bundle_through_child_registry(self):
        self.set_message(b'QA BUNDLE PARTIAL');self.record.update(status='interrupted',network_coverage='partial')
        with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as db:
            db.execute('UPDATE recordings SET data=?',(json.dumps(self.record),))
        files,ref=self.bundle()
        (self.root/'recordings'/'.bundle-unpublished').mkdir()
        c=self.child()
        summary=c.exchange(message('recording',{'ref':ref}))['recording']
        self.assertEqual(summary['bundle_status'],'verified');self.assertEqual(summary['packet_status'],'partial')
        result=self.run_ref(c,ref)
        self.assertEqual(result['result']['items'][0]['recording_context']['bundle_status'],'verified')
        receipt=json.loads((self.root/'receipts.jsonl').read_text().splitlines()[0])
        self.assertEqual(receipt['packet_status'],'partial')
        self.assertEqual(receipt['request_sha256'],hashlib.sha256(b'QA BUNDLE PARTIAL').hexdigest())

    async def test_bundle_mutation_and_manifest_mismatch_block_child_executor(self):
        self.set_message(b'QA BUNDLE');files,ref=self.bundle();c=self.child()
        self.assertEqual(c.exchange(message('recording',{'ref':ref}))['status'],'available')
        manifest=files['link'].parent/'manifest.json';original=manifest.read_bytes()
        changed=json.loads(original);changed['recording_id']='synthetic-foreign'
        manifest.write_text(json.dumps(changed),encoding='utf-8')
        self.assertEqual(c.exchange(message('recording',{'ref':ref}))['status'],'invalid')
        manifest.write_bytes(original)
        with files['route'].open('ab') as stream:stream.write(b' ')  # Still valid JSON, changed committed bytes.
        reply=c.exchange(message('recording',{'ref':ref}))
        self.assertEqual(reply['recording']['bundle_status'],'invalid')
        r=request();r.update(command_id='invalid-bundle',recording_ref=ref)
        jid=c.exchange(message('submit',{'request':r}))['data']['execution_id']
        deadline=time.monotonic()+5
        while True:
            state=c.exchange(message('progress',{'execution_id':jid,'cursor':0}))
            if state['execution']['status']=='finished':break
            self.assertLess(time.monotonic(),deadline)
        result=c.exchange(message('result',{'run_id':state['run_id']}))['result']
        self.assertEqual(result['execution_status'],'not_run')
        self.assertEqual(result['reason'],'INVALID_RECORDING_BUNDLE')
        self.assertFalse((self.root/'receipts.jsonl').exists())
        manifest.unlink()
        self.assertEqual(c.exchange(message('recording',{'ref':ref}))['status'],'invalid')

    async def test_startup_registry_limits_and_names(self):
        from integration.mock_stdio import recording_registry
        self.assertEqual(recording_registry(self.root),{})
        (self.root/'recordings'/'not.a.reference').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'INVALID_RECORDING_REF'):recording_registry(self.root)
        other=self.root/'many'
        for i in range(21):(other/'recordings'/str(i)).mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'REGISTRY_LIMIT'):recording_registry(other)

    def copy(self, ref):
        folder=self.root/'recordings'/ref;folder.mkdir(parents=True)
        for file in self.files.values():shutil.copy2(file,folder/file.name)
        return folder

    def child(self):
        c=StdioClient([sys.executable,'-c',OBSERVER,str(self.root)],timeout=5)
        self.addCleanup(c.close);return c

    def run_ref(self, c, ref):
        r=request();r.update(command_id='run-'+ref,recording_ref=ref)
        reply=c.exchange(message('submit',{'request':r}))['data'];jid=reply['execution_id']
        deadline=time.monotonic()+5
        while True:
            state=c.exchange(message('progress',{'execution_id':jid,'cursor':0}))
            if state['execution']['status']=='finished':break
            self.assertLess(time.monotonic(),deadline)
        result=c.exchange(message('result',{'run_id':state['run_id']}))
        self.assertEqual(result['status'],'ok');self.assertEqual(result['result']['execution_status'],'completed')
        return result

    async def test_two_selected_records_and_grant_isolation(self):
        self.set_message(b'QA RECORD A');self.copy('record-a')
        self.set_message(b'QA RECORD B');self.route['actions'][0]['action']['post']['text']='SYNTHETIC_B'
        self.files['route'].write_text(json.dumps(self.route),encoding='utf-8');self.copy('record-b')
        c=self.child()
        for ref in ('record-a','record-b'):
            self.assertEqual(c.exchange(message('recording',{'ref':ref}))['recording']['packet_status'],'complete')
            result=self.run_ref(c,ref);self.assertNotIn('QA RECORD',json.dumps(result))
        receipts=[json.loads(line) for line in (self.root/'receipts.jsonl').read_text().splitlines()]
        self.assertEqual([r['request_sha256'] for r in receipts],[hashlib.sha256(x).hexdigest() for x in (b'QA RECORD A',b'QA RECORD B')])
        self.assertNotEqual(receipts[0]['actions_sha256'],receipts[1]['actions_sha256'])
        for ref, receipt in zip(('record-a','record-b'),receipts):
            actions=json.loads((self.root/'recordings'/ref/'route.json').read_text())['actions']
            self.assertEqual(receipt['actions_sha256'],hashlib.sha256(json.dumps(actions,sort_keys=True).encode()).hexdigest())
        self.assertTrue(all(r['foreign_status']=='denied' for r in receipts))
        self.assertEqual(len(c.exchange(message('history',{}))['runs']),2)

    async def test_partial_missing_and_unknown_selection(self):
        self.set_message(b'QA PARTIAL');self.record.update(status='interrupted',network_coverage='partial')
        with closing(sqlite3.connect(self.files['packets'],isolation_level=None)) as db:
            db.execute('UPDATE recordings SET data=?',(json.dumps(self.record),))
        self.copy('partial');missing=self.copy('missing');(missing/'route.json').unlink();(missing/'packets.sqlite').unlink()
        c=self.child()
        self.assertEqual(c.exchange(message('recording',{'ref':'partial'}))['recording']['packet_status'],'partial')
        self.run_ref(c,'partial');result=self.run_ref(c,'missing')
        summary=result['result']['items'][0]['recording_context']
        self.assertEqual(summary['route_status'],'missing');self.assertEqual(summary['packet_status'],'missing')
        self.assertEqual(summary['mode'],'route_unavailable')
        r=request();r.update(recording_ref='not-registered')
        self.assertEqual(c.exchange(message('submit',{'request':r}))['data']['status'],'not_run')
        r['recording_ref']='../outside'
        self.assertIn('error',c.exchange(message('submit',{'request':r})))
        receipts=[json.loads(line) for line in (self.root/'receipts.jsonl').read_text().splitlines()]
        self.assertEqual(receipts[0]['packet_status'],'partial');self.assertNotIn('read_status',receipts[1])
