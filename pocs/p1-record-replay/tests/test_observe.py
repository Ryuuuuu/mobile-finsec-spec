import unittest
from unittest.mock import Mock, patch
from pc.observe import Viewer, target_state, viewer_command
from pc.ui import Window
from types import SimpleNamespace

class ObservationTest(unittest.TestCase):
    def test_viewer_cannot_inject_or_record(self):
        command=viewer_command('scrcpy','QA-SERIAL')
        self.assertIn('--no-control',command);self.assertIn('--no-audio',command)
        self.assertNotIn('--record',command);self.assertNotIn('--stay-awake',command)
    def test_target_only_multiprocess_and_foreground(self):
        state=target_state('PID NAME\n1 org.qa\n2 org.qa:worker\n3 org.qa.other\n4 private.other',
            'mResumedActivity: ActivityRecord{ org.qa/.Entry }','org.qa')
        self.assertEqual(state,{'pids':('1','2'),'foreground':True})
        self.assertFalse(target_state('', 'topResumedActivity=ActivityRecord{ private.other/.Home }','org.qa')['foreground'])
        self.assertIsNone(target_state('','','org.qa')['foreground'])
    @patch('pc.observe.subprocess.Popen')
    def test_viewer_lifecycle_is_owned_and_idempotent(self,popen):
        process=Mock();process.poll.return_value=None;popen.return_value=process
        viewer=Viewer('scrcpy','QA-SERIAL','adb');viewer.start();viewer.start()
        popen.assert_called_once();self.assertEqual(popen.call_args.kwargs['env']['ADB'],'adb')
        viewer.stop();process.terminate.assert_called_once();process.wait.assert_called_once()
        process.poll.return_value=1;self.assertIn('restart is manual',viewer.status())
        viewer.stop();process.terminate.assert_called_once()
    @patch('pc.ui.subprocess.Popen')
    def test_p1_observer_has_separate_process_and_explicit_binary(self,popen):
        process=Mock();process.poll.return_value=None;popen.return_value=process
        window=object.__new__(Window);window.observer_process=None;window.status=Mock()
        window.args=SimpleNamespace(device='QA-SERIAL',package='org.qa',scrcpy='official-scrcpy')
        window.observe_device();window.observe_device()
        popen.assert_called_once();command=popen.call_args.args[0]
        self.assertIn('pc.observe',command);self.assertEqual(command[-2:],['--scrcpy','official-scrcpy'])
