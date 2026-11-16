import copy, json, pathlib, tempfile, unittest
from unittest.mock import patch
from pc import protocol as p
from pc.core import Engine, Lease, Journal
from pc.adapter import Uncertain

class Fake:
    device='QA-SERIAL'; package=p.PACKAGE
    def __init__(self):
        self.values={p.PREFIX+'initial_state':'reset:0::',p.PREFIX+'username':'',p.PREFIX+'password':'',p.PREFIX+'secure_state':'secure:off',p.PREFIX+'screen_state':'login',p.PREFIX+'login':''}
        self.inputs=[]; self.dupe=False; self.missing=False; self.broken=False; self.image=True
    def target(self):return {'version_code':'1','version_name':'1.0','apk_sha256':'a'*64}
    def foreground(self):
        if self.broken:raise Uncertain('disconnected')
    def elements(self,r):
        if r==p.PREFIX+'login' and self.dupe:return ['x','y']
        if self.missing:return []
        return [r] if r in self.values else []
    def text(self,e):return self.values[e]
    def source(self):return '<hierarchy/>'
    def screenshot(self):
        if not self.image:raise RuntimeError('Capture unavailable; cause unknown')
        return b'fake-png'
    def click(self,e):self.inputs.append(('tap',e)); self.values[p.PREFIX+'screen_state']='menu'
    def enter(self,e,t):self.inputs.append(('text',t));self.values[e]=t
    def back(self):self.inputs.append(('back',))
    def geometry(self):return {'width':1080,'height':1920,'rotation':'PORTRAIT'}
    def gesture(self,start,end):self.inputs.append(('gesture',start,end)); self.values[p.PREFIX+'screen_state']='menu'

def tap():return {'type':'tap','locator':p.PREFIX+'login','timeout':1,'post':{'id':p.PREFIX+'screen_state','text':'menu'}}

class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.a=Fake();self.e=Engine(self.a,self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def recording(self):self.e.start();self.e.record_action(tap());self.e.finish();return copy.deepcopy(self.e.record)
    def test_round_trip_and_order(self):
        r=self.recording();p.route(r)
        events=[json.loads(s) for s in (self.e.j.path/'events.jsonl').read_text().splitlines()]
        names=[e['event'] for e in events];self.assertLess(names.index('intent'),names.index('dispatch'));self.assertLess(names.index('dispatch'),names.index('result'))
        self.a=Fake();self.e.a=self.a
        self.assertEqual(self.e.replay(r)['status'],'succeeded')
    def test_action_id_cannot_escape_evidence_directory(self):
        r=self.recording();r['actions'][0]['action_id']='../../outside'
        with self.assertRaises(ValueError):p.route(r)
    def test_duplicate_start_stop(self):
        self.e.start()
        with self.assertRaises(RuntimeError):self.e.start()
        self.e.record_action(tap());self.e.finish();original=(self.e.j.path/'route.json').read_bytes();self.e.finish()
        self.assertEqual(original,(self.e.j.path/'route.json').read_bytes())
        with self.assertRaises(RuntimeError):self.e.record_action(tap())
    def test_intent_storage_failure_blocks_dispatch(self):
        self.e.start();original=self.e.j.write
        def write(event,**data):
            if event=='intent':raise OSError('disk full')
            original(event,**data)
        self.e.j.write=write
        with self.assertRaises(OSError):self.e.record_action(tap())
        self.assertEqual(self.a.inputs,[]);self.assertEqual(self.e.mode,'incomplete')
    def test_result_storage_failure_no_retry(self):
        self.e.start();original=self.e.j.write
        def write(event,**data):
            if event=='result':raise OSError('disk full after dispatch')
            original(event,**data)
        self.e.j.write=write
        with self.assertRaises(OSError):self.e.record_action(tap())
        self.assertEqual(len(self.a.inputs),1);self.assertEqual(self.e.steps,[])
    def test_ambiguous_locator_no_coordinate_fallback(self):
        self.e.start();self.a.dupe=True;self.e.allow_coordinates=True;a=tap();a.update(point=[.5,.5],geometry=self.a.geometry())
        with self.assertRaisesRegex(RuntimeError,'Ambiguous'):self.e.record_action(a)
        self.assertEqual(self.a.inputs,[])
    def test_geometry_mismatch_blocks(self):
        self.e.start();self.e.allow_coordinates=True;a=tap();del a['locator'];a.update(point=[.5,.5],geometry={'width':1920,'height':1080,'rotation':'LANDSCAPE'})
        with self.assertRaisesRegex(RuntimeError,'Geometry'):self.e.record_action(a)
        self.assertEqual(self.a.inputs,[])
    def test_coordinate_limit(self):
        self.e.start();self.e.allow_coordinates=True;a=tap();del a['locator'];a.update(point=[.5,.5],geometry=self.a.geometry())
        for _ in range(3):self.e.record_action(a)
        with self.assertRaisesRegex(RuntimeError,'limit'):self.e.record_action(a)
        self.assertEqual(len(self.a.inputs),3)
    def test_screen_unavailable_locator_still_observed(self):
        self.e.start();self.a.image=False;self.e.record_action(tap());self.e.finish()
        events=[json.loads(s) for s in (self.e.j.path/'events.jsonl').read_text().splitlines()]
        result=next(e for e in events if e['event']=='result')
        self.assertEqual(result['after']['screen'],'unavailable');self.assertEqual(result['after']['hierarchy'],'available')
    def test_stop_boundary(self):
        self.e.start();self.e.stop_requested()
        with self.assertRaises(RuntimeError):self.e.record_action(tap())
        self.assertEqual(self.a.inputs,[])
    def test_disconnect_not_completed(self):
        self.e.start();self.a.broken=True
        with self.assertRaises(Uncertain):self.e.record_action(tap())
        self.assertEqual(self.e.mode,'incomplete')
    def test_failed_replay_tail_not_run(self):
        r=self.recording();r['actions'].append({'action_id':'tail','action':tap()});self.e.a=Fake();self.e.a.dupe=True
        result=self.e.replay(r)
        self.assertEqual([s['status'] for s in result['steps']],['failed','not_run'])
    def test_build_mismatch_no_dispatch(self):
        r=self.recording();r['target']['apk_sha256']='b'*64;self.e.a=Fake()
        self.assertEqual(self.e.replay(r)['status'],'failed');self.assertEqual(self.e.a.inputs,[])
    def test_device_mismatch(self):
        r=self.recording();r['device_id']='OTHER';self.e.a=Fake()
        self.assertEqual(self.e.replay(r)['status'],'failed');self.assertEqual(self.e.a.inputs,[])
    def test_initial_mismatch(self):
        r=self.recording();self.e.a=Fake();self.e.a.values[p.PREFIX+'initial_state']='reset:1::'
        self.assertEqual(self.e.replay(r)['status'],'incomplete');self.assertEqual(self.e.a.inputs,[])
    def test_replay_rejects_manual_input(self):
        self.e.mode='replaying'
        with self.assertRaises(RuntimeError):self.e.record_action(tap())
    def test_postcondition_timeout(self):
        self.e.start();a=tap();a['post']['text']='never'
        with self.assertRaises(TimeoutError):self.e.record_action(a)
        self.assertEqual(self.e.mode,'incomplete')
    def test_cancel_after_dispatch(self):
        self.e.start();old=self.a.click
        def click(e):old(e);self.e.stop_requested()
        self.a.click=click
        with self.assertRaises(InterruptedError):self.e.record_action(tap())
        self.assertEqual(self.e.steps,[])
    def test_lock_and_quarantine(self):
        with patch('pathlib.Path.home',return_value=pathlib.Path(self.tmp.name)):
            a=Lease('test');b=Lease('test');a.acquire()
            with self.assertRaises(RuntimeError):b.acquire()
            a.poison('uncertain');a.release()
            with self.assertRaises(RuntimeError):b.acquire()

    def test_concurrent_api_rejected_immediately(self):
        self.e.guard.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError,'Busy'):self.e.start()
            with self.assertRaisesRegex(RuntimeError,'Busy'):self.e.record_action(tap())
        finally:self.e.guard.release()
    def test_clean_lease_release_and_crash_marker(self):
        with patch('pathlib.Path.home',return_value=pathlib.Path(self.tmp.name)):
            a=Lease('clean'); a.acquire(); a.release(clean=True)
            b=Lease('clean'); b.acquire(); b.release() # simulated process exit without cleanup
            with self.assertRaises(RuntimeError): Lease('clean').acquire()

class ProtocolTest(unittest.TestCase):
    def test_code_and_unknown_fields_rejected(self):
        for a in [dict(tap(),type='shell'),dict(tap(),code='print(1)'),dict(tap(),timeout=float('inf')),dict(tap(),timeout=True),dict(tap(),locator='other:id/login')]:
            with self.assertRaises(ValueError):p.action(a)
    def test_literal_allowlist(self):
        with self.assertRaises(ValueError):p.action({'type':'text','locator':p.PREFIX+'password','text':'real secret','timeout':1,'post':{'id':p.PREFIX+'password'}})
    def test_mapping_three_geometries(self):
        for vw,vh,iw,ih in [(600,900,1080,1920),(900,600,1920,1080),(600,600,1440,2560)]:
            self.assertEqual(p.view_point(vw/2,vh/2,vw,vh,iw,ih),[.5,.5])
        with self.assertRaises(ValueError):p.view_point(0,0,600,900,1080,1920)
    def test_partial_and_version_rejected(self):
        for r in [{'schema_version':99},{'status':'incomplete'}]:
            with self.assertRaises(ValueError):p.route(r)
if __name__=='__main__':unittest.main()
