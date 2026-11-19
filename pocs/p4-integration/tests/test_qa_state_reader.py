import unittest
from unittest.mock import Mock,patch
from integration.qa_state_reader import read_network_qa_state,PACKAGE,RESOURCE,ELEMENT


class StateReaderTests(unittest.TestCase):
    def adapter(self,value='ready'):
        adapter=Mock(package=PACKAGE,session='qa-session',uncertain=False)
        adapter.request.side_effect=[PACKAGE,[{ELEMENT:'qa-element'}],value]
        return adapter

    def test_exact_scope_allowlist_and_no_raw_capture_endpoints(self):
        for value,expected in [('ready','QA_READY'),('sent:1','QA_SENT'),('PRIVATE_SYNTHETIC_MARKER','UNSUPPORTED_QA_STATE')]:
            a=self.adapter(value);self.assertEqual(read_network_qa_state(a),expected)
            calls=a.request.call_args_list
            self.assertEqual([c.args[1] for c in calls],['/session/qa-session/appium/device/current_package','/session/qa-session/elements','/session/qa-session/element/qa-element/text'])
            self.assertEqual(calls[1].args[2],{'using':'id','value':RESOURCE})
            self.assertTrue(all(0<c.kwargs['timeout']<=1 for c in calls))

    def test_package_foreground_ambiguity_and_deadline_fail_closed(self):
        a=self.adapter();a.package='other.package'
        with self.assertRaises(ValueError):read_network_qa_state(a)
        a.request.assert_not_called()
        for replies in (['other.package'],[PACKAGE,[]],[PACKAGE,[{ELEMENT:'a'},{ELEMENT:'b'}]]):
            a=self.adapter();a.request.side_effect=replies
            with self.assertRaises(ValueError):read_network_qa_state(a)
        a=self.adapter()
        with patch('integration.qa_state_reader.time.monotonic',side_effect=[0,0,2]):
            with self.assertRaises(TimeoutError):read_network_qa_state(a)
        self.assertEqual(a.request.call_count,1)

    def test_transport_error_does_not_copy_private_error_body(self):
        a=self.adapter();a.request.side_effect=RuntimeError('PRIVATE_SYNTHETIC_BODY')
        with self.assertRaisesRegex(RuntimeError,'^QA_STATE_READ_FAILED$'):read_network_qa_state(a)


if __name__=='__main__':unittest.main()
