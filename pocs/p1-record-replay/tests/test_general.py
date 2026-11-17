"""Non-sensitive selected-app scenarios; no physical device or bank account."""
import copy, json, tempfile, unittest
from unittest.mock import Mock, patch
from pc import protocol as p
from pc.adapter import Appium, TargetNotForeground, Uncertain
from pc.core import Engine
from pc.ui import tap_resource
from test_core import Fake

PACKAGE='org.example.qa'
ID=PACKAGE+':id/state'
class General(Fake):
    package=PACKAGE
    def __init__(self):
        super().__init__(); self.values={ID:'ready'}
    def target(self):return {'version_code':'42','version_name':'2.0','apk_sha256s':{'base.apk':'a'*64,'split_config.en.apk':'b'*64}}
    def check_text_target(self,e):pass
    def click(self,e):self.inputs.append(('tap',e));self.values[ID]='done'

class GeneralTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.a=General();self.e=Engine(self.a,self.tmp.name,initial_condition={'id':ID,'text':'ready'})
    def tearDown(self):self.tmp.cleanup()
    def route(self):
        self.e.start();self.e.record_action({'type':'tap','locator':ID,'timeout':1,'post':{'id':ID,'text':'done'}});self.e.finish()
        return copy.deepcopy(self.e.record)
    def test_v2_round_trip_no_evidence(self):
        route=self.route();self.assertEqual(route['schema_version'],2);self.assertEqual(list((self.e.j.path/'evidence').iterdir()),[])
        self.a.values[ID]='ready';self.assertEqual(self.e.replay(route)['status'],'succeeded')
    def test_package_mismatch_no_input(self):
        route=self.route();self.a.inputs=[];self.a.package='org.example.other'
        result=self.e.replay(route);self.assertEqual(result['status'],'failed');self.assertEqual(self.a.inputs,[]);self.assertEqual(result['steps'][0]['status'],'not_run')
    def test_split_update_blocks(self):
        route=self.route();self.a.inputs=[];route['target']['apk_sha256s']['split_config.en.apk']='c'*64
        self.assertEqual(self.e.replay(route)['status'],'failed');self.assertEqual(self.a.inputs,[])
    def test_initial_required(self):
        self.e.initial_condition=None
        with self.assertRaises(ValueError):self.e.start()
        self.assertEqual(self.a.inputs,[])
    def test_capture_unavailable_locator_allowed(self):
        self.a.screenshot=Mock(side_effect=RuntimeError('protected'));self.route();self.a.screenshot.assert_not_called()
    def test_foreground_change_blocks(self):
        self.e.start();self.a.foreground=Mock(side_effect=TargetNotForeground())
        with self.assertRaises(TargetNotForeground):self.e.record_action({'type':'back','timeout':1,'post':{'id':ID}})
        self.assertEqual(self.a.inputs,[])
    def test_disconnect_blocks_no_retry(self):
        self.e.start();self.a.broken=True
        with self.assertRaises(Uncertain):self.e.record_action({'type':'back','timeout':1,'post':{'id':ID}})
        self.assertEqual(self.a.inputs,[])
    def test_password_rejected_before_intent(self):
        self.e.start();self.a.check_text_target=Mock(side_effect=RuntimeError('password'))
        with self.assertRaises(RuntimeError):self.e.record_action({'type':'text','locator':ID,'text':'not-a-secret','timeout':1,'post':{'id':ID}})
        events=[json.loads(v)['event'] for v in (self.e.j.path/'events.jsonl').read_text().splitlines()]
        self.assertNotIn('intent',events);self.assertEqual(self.a.inputs,[])
    def test_selected_resource_namespace(self):
        p.resource(ID,PACKAGE);p.resource('android:id/button1',PACKAGE)
        for rid in ['org.other.app:id/state','bad',PACKAGE+':id/a;cmd']:
            with self.assertRaises(ValueError):p.resource(rid,PACKAGE)
    def test_general_text_and_fixture_compatibility(self):
        a={'type':'text','locator':ID,'text':'sample QA','timeout':1,'post':{'id':ID}}
        p.action(a,PACKAGE)
        with self.assertRaises(ValueError):p.action(a)
    def test_schema_not_interchangeable(self):
        r=self.route();r['schema_version']=1
        with self.assertRaises(ValueError):p.route(r)

class GeneralAdapterTest(unittest.TestCase):
    def setUp(self):self.a=Appium('QA-SERIAL',PACKAGE)
    def baseline(self):return {'package':PACKAGE,'hidden_api':{'hidden_api_policy':'null','hidden_api_policy_p_apps':'2','hidden_api_policy_pre_p_apps':'0'},'helper_mock_location':'MOCK_LOCATION: default'}
    def test_no_session_without_approval(self):
        self.a.request=Mock()
        with self.assertRaises(RuntimeError):self.a.open()
        self.a.request.assert_not_called()
    def test_dynamic_launcher(self):
        self.a.adb=Mock(return_value='priority=0\n'+PACKAGE+'/.StartActivity')
        self.assertEqual(self.a.launcher(),PACKAGE+'/.StartActivity')
    def test_missing_foreign_or_injected_launcher(self):
        for response in ['No activity found','org.other.app/.Main',PACKAGE+'/.Main;reboot']:
            self.a.adb=Mock(return_value=response)
            with self.assertRaises(RuntimeError):self.a.launcher()
    def test_launch_windows_crlf_success(self):
        self.a.launcher=Mock(return_value=PACKAGE+'/.Start');self.a.adb=Mock(return_value='Starting: Intent\r\nStatus: ok\r\nTotalTime: 1')
        self.assertIn('started',self.a.launch())
    def test_uncertain_transport_defers_restore(self):
        self.a.approve_security(self.baseline());self.a.uncertain=True;self.a.adb=Mock()
        with self.assertRaises(RuntimeError):self.a.close()
        self.a.adb.assert_not_called();self.assertTrue(hasattr(self.a,'security_baseline'))
    def test_launch_failure(self):
        self.a.launcher=Mock(return_value=PACKAGE+'/.Start');self.a.adb=Mock(return_value='Error: disabled')
        with self.assertRaises(RuntimeError):self.a.launch()
    def test_no_reset_no_autolaunch_caps(self):
        self.a.approve_security(self.baseline());self.a.target=Mock(return_value={});self.a.launcher=Mock(return_value=PACKAGE+'/.Start')
        self.a.request=Mock(return_value={'sessionId':'fake'});self.a.open()
        caps=self.a.request.call_args_list[0].args[2]['capabilities']['alwaysMatch']
        self.assertTrue(caps['appium:noReset']);self.assertFalse(caps['appium:autoLaunch']);self.assertFalse(caps['appium:forceAppLaunch']);self.assertEqual(caps['appium:appActivity'],'.Start')
    def test_split_manifest(self):
        def adb(*args,**kwargs):
            if args==('get-state',):return 'device'
            if args[1]=='dumpsys':return 'versionCode=42 versionName=2.0'
            if args[1]=='pm':return 'package:/data/app/test/base.apk\npackage:/data/app/test/split_config.en.apk'
            return args[-1].encode()
        self.a.adb=adb;self.assertEqual(len(self.a.target()['apk_sha256s']),2)
    def test_restore_verified(self):
        report=self.baseline();self.a.approve_security(report)
        def adb(*args,**kwargs):
            if args[:3]==('shell','settings','get'):return report['hidden_api'][args[-1]]
            if args[:4]==('shell','cmd','appops','get'):return 'MOCK_LOCATION: default'
            return ''
        self.a.adb=Mock(side_effect=adb);self.a.close();self.assertFalse(self.a.security_approved)
    def test_restore_failure_retains_baseline(self):
        self.a.approve_security(self.baseline());self.a.adb=Mock(return_value='1')
        with self.assertRaises(RuntimeError):self.a.close()
        self.assertTrue(hasattr(self.a,'security_baseline'))
    def test_unknown_password_attribute_fails_closed(self):
        for value in [None,True,'true']:
            self.a.call=Mock(return_value=value)
            with self.assertRaises(RuntimeError):self.a.check_text_target('element')
    def test_invalid_package(self):
        for value in ['pkg;reboot','../test','org.example/Bad','']:
            with self.assertRaises(ValueError):Appium('QA-SERIAL',value)

class HitTargetTest(unittest.TestCase):
    def test_nonclickable_content_container_does_not_steal_canvas_tap(self):
        xml='<hierarchy><node resource-id="android:id/content" clickable="false" bounds="[0,0][100,100]"><node clickable="false" bounds="[10,10][90,90]"/></node></hierarchy>'
        self.assertIsNone(tap_resource(xml,50,50,PACKAGE))
    def test_smallest_enabled_clickable_target_wins(self):
        xml='<hierarchy><node resource-id="android:id/content" clickable="false" bounds="[0,0][100,100]"/><node resource-id="'+ID+'" clickable="true" enabled="true" bounds="[10,10][90,90]"/></hierarchy>'
        self.assertEqual(tap_resource(xml,50,50,PACKAGE),ID)
        self.assertIsNone(tap_resource(xml.replace('enabled="true"','enabled="false"'),50,50,PACKAGE))
