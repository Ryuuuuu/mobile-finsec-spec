import subprocess
import unittest
from unittest.mock import patch
from integration.qa_state_only import run_probe, COMPONENT

class StateOnlyTests(unittest.TestCase):
    def test_only_fixed_instrumentation_no_settings_proxy_or_shell_payload(self):
        output=b'INSTRUMENTATION_RESULT: qa_contract=state-only.v1\nINSTRUMENTATION_RESULT: qa_states=QA_READY>QA_SENT\nINSTRUMENTATION_CODE: -1\n'
        with patch('integration.qa_state_only.subprocess.run',return_value=subprocess.CompletedProcess([],0,output,b'')) as call:
            result=run_probe('adb','synthetic-device')
        self.assertEqual(call.call_args.args[0],['adb','-s','synthetic-device','shell','am','instrument','-w','-r',COMPONENT])
        self.assertEqual(call.call_count,1)
        self.assertNotIn('shell',call.call_args.kwargs)
        self.assertEqual(result['states'],['QA_READY','QA_SENT'])
        self.assertEqual(result['cleanup'],'activity_finish_reported')

    def test_unknown_output_and_timeout_are_not_success_or_retry(self):
        with patch('integration.qa_state_only.subprocess.run',return_value=subprocess.CompletedProcess([],0,b'PRIVATE_MARKER',b'')):
            result=run_probe('adb','synthetic-device')
        self.assertEqual(result['status'],'unverified');self.assertNotIn('PRIVATE_MARKER',str(result))
        with patch('integration.qa_state_only.subprocess.run',side_effect=subprocess.TimeoutExpired('fixed',15)) as call:
            result=run_probe('adb','synthetic-device')
        self.assertEqual(call.call_count,1);self.assertEqual(result['status'],'outcome_unknown')
        self.assertFalse(result['retry_allowed']);self.assertEqual(result['cleanup'],'unverified')

    def test_invalid_device_rejected_without_execution(self):
        with patch('integration.qa_state_only.subprocess.run') as call:
            for device in ('','-x','a b',None):
                with self.assertRaises(ValueError):run_probe('adb',device)
        call.assert_not_called()
