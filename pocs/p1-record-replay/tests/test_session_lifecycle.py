"""Mock-only session timeout and lease failure contracts; no device or server."""
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch

from pc.adapter import Appium, Uncertain
from pc.core import Lease
from pc.protocol import PACKAGE


def response(value=None):
    return io.BytesIO(json.dumps({'value': value}).encode())


class SessionTimeoutTest(unittest.TestCase):
    def test_default_session_creation_timeout_is_90_seconds(self):
        opener = Mock()
        opener.open.side_effect = lambda *args, **kwargs: response()
        with patch('pc.adapter.urllib.request.build_opener', return_value=opener):
            Appium('TEST-SERIAL', PACKAGE).request('POST', '/session', {})
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 90)
        self.assertEqual(opener.open.call_count, 1)

    def test_only_exact_post_session_uses_configured_timeout(self):
        cases = [
            ('POST', '/session', 150),
            ('GET', '/session', 20),
            ('POST', '/session/', 20),
            ('POST', '/session/known/timeouts', 20),
            ('POST', '/session/known/element/one/click', 20),
            ('DELETE', '/session/known', 20),
        ]
        adapter = Appium('TEST-SERIAL', PACKAGE, session_create_timeout=150)
        for method, path, expected in cases:
            with self.subTest(method=method, path=path):
                opener = Mock()
                opener.open.side_effect = lambda *args, **kwargs: response()
                with patch('pc.adapter.urllib.request.build_opener', return_value=opener):
                    adapter.request(method, path, {} if method == 'POST' else None)
                opener.open.assert_called_once()
                request = opener.open.call_args.args[0]
                self.assertEqual(request.get_method(), method)
                self.assertEqual(request.full_url, 'http://127.0.0.1:4723' + path)
                self.assertEqual(opener.open.call_args.kwargs['timeout'], expected)

    def test_session_creation_timeout_accepts_integer_bounds(self):
        for value in (30, 90, 300):
            with self.subTest(value=value):
                opener = Mock()
                opener.open.side_effect = lambda *args, **kwargs: response()
                with patch('pc.adapter.urllib.request.build_opener', return_value=opener):
                    adapter = Appium('TEST-SERIAL', PACKAGE, session_create_timeout=value)
                    adapter.request('POST', '/session', {})
                self.assertEqual(opener.open.call_args.kwargs['timeout'], value)

    def test_session_creation_timeout_rejects_nonintegers_and_out_of_bounds(self):
        for value in (True, False, 29, 301, 0, -1, 90.0, '90', None, float('inf')):
            with self.subTest(value=value):
                with patch('pc.adapter.urllib.request.build_opener') as factory:
                    with self.assertRaises(ValueError):
                        Appium('TEST-SERIAL', PACKAGE, session_create_timeout=value)
                factory.assert_not_called()

    def test_session_creation_timeout_is_keyword_only(self):
        with self.assertRaises(TypeError):
            Appium('TEST-SERIAL', PACKAGE, 'http://127.0.0.1:4723', 90)

    def test_request_deadline_override_only_shortens_default(self):
        adapter=Appium('TEST-SERIAL',PACKAGE)
        opener=Mock();opener.open.side_effect=lambda *a,**kw:response()
        with patch('pc.adapter.urllib.request.build_opener',return_value=opener):
            adapter.request('GET','/session/qa/element/state/text',timeout=.4)
        self.assertEqual(opener.open.call_args.kwargs['timeout'],.4)
        for value in (True,0,-1,21,float('nan'),float('inf'),'1'):
            with patch('pc.adapter.urllib.request.build_opener') as factory:
                with self.assertRaises(ValueError):adapter.request('GET','/status',timeout=value)
                factory.assert_not_called()

    def test_create_timeout_is_uncertain_and_is_not_retried(self):
        adapter = Appium('TEST-SERIAL', PACKAGE, session_create_timeout=120)
        opener = Mock()
        opener.open.side_effect = TimeoutError('synthetic create timeout')
        with patch.object(adapter, 'target', return_value={}), patch(
            'pc.adapter.urllib.request.build_opener', return_value=opener
        ):
            with self.assertRaises(Uncertain):
                adapter.open()
        self.assertTrue(adapter.uncertain)
        self.assertIsNone(adapter.session)
        opener.open.assert_called_once()
        request = opener.open.call_args.args[0]
        self.assertEqual((request.get_method(), request.full_url), ('POST', adapter.url + '/session'))
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 120)

    def test_command_and_delete_timeouts_are_uncertain_without_retry(self):
        for operation, method, suffix in (
            ('click', 'POST', '/session/known/element/one/click'),
            ('close', 'DELETE', '/session/known'),
        ):
            with self.subTest(operation=operation):
                adapter = Appium('TEST-SERIAL', PACKAGE, session_create_timeout=180)
                adapter.session = 'known'
                opener = Mock()
                opener.open.side_effect = TimeoutError('synthetic command timeout')
                with patch('pc.adapter.urllib.request.build_opener', return_value=opener):
                    with self.assertRaises(Uncertain):
                        adapter.click('one') if operation == 'click' else adapter.close()
                self.assertTrue(adapter.uncertain)
                self.assertEqual(adapter.session, 'known')
                opener.open.assert_called_once()
                request = opener.open.call_args.args[0]
                self.assertEqual((request.get_method(), request.full_url), (method, adapter.url + suffix))
                self.assertEqual(opener.open.call_args.kwargs['timeout'], 20)


class LeasePermissionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch('pathlib.Path.home', return_value=pathlib.Path(self.temp.name)):
            self.lease = Lease('TEST-SERIAL')

    def test_denied_marker_check_before_lock_is_actionable_without_open_or_deletion(self):
        with patch('pathlib.Path.exists', side_effect=PermissionError('Access denied checking marker')), patch(
            'pathlib.Path.open'
        ) as opening, patch('pathlib.Path.unlink') as unlink:
            with self.assertRaises(Exception) as raised:
                self.lease.acquire()
        self.assertRegex(str(raised.exception), r'(?i)same Windows user')
        opening.assert_not_called()
        unlink.assert_not_called()
        self.assertIsNone(self.lease.handle)

    def test_denied_marker_recheck_after_lock_closes_handle_without_deletion(self):
        handle = Mock()
        lock_function = 'msvcrt.locking' if os.name == 'nt' else 'fcntl.flock'
        with patch('pathlib.Path.exists', side_effect=[False, False, PermissionError('Access denied rechecking marker')]), patch(
            'pathlib.Path.open', return_value=handle
        ) as opening, patch('pathlib.Path.stat', return_value=Mock(st_size=1)), patch(
            lock_function
        ), patch('pathlib.Path.unlink') as unlink:
            with self.assertRaises(Exception) as raised:
                self.lease.acquire()
        self.assertRegex(str(raised.exception), r'(?i)same Windows user')
        opening.assert_called_once_with('a+b')
        handle.close.assert_called_once()
        unlink.assert_not_called()
        self.assertIsNone(self.lease.handle)

    def test_denied_lock_open_is_actionable_without_fallback_or_deletion(self):
        original_path = self.lease.path
        with patch('pathlib.Path.open', side_effect=PermissionError('Access denied')) as opening, patch(
            'pathlib.Path.unlink'
        ) as unlink:
            with self.assertRaises(Exception) as raised:
                self.lease.acquire()
        self.assertRegex(str(raised.exception), r'(?i)same Windows user')
        opening.assert_called_once_with('a+b')
        unlink.assert_not_called()
        self.assertEqual(self.lease.path, original_path)
        self.assertIsNone(self.lease.handle)

    def test_initialization_failure_closes_open_handle(self):
        for failure in (PermissionError('Access denied during seek'), OSError('Synthetic seek failure')):
            with self.subTest(failure=type(failure).__name__):
                handle = Mock()
                handle.seek.side_effect = failure
                with patch('pathlib.Path.open', return_value=handle) as opening, patch('pathlib.Path.unlink') as unlink:
                    with self.assertRaises(Exception) as raised:
                        self.lease.acquire()
                if isinstance(failure, PermissionError):
                    self.assertRegex(str(raised.exception), r'(?i)same Windows user')
                opening.assert_called_once_with('a+b')
                handle.close.assert_called_once()
                unlink.assert_not_called()
                self.assertIsNone(self.lease.handle)

    def test_denied_active_marker_write_closes_lock_without_deleting_markers(self):
        real_open = pathlib.Path.open
        handles = []

        def track_open(path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            handles.append(handle)
            return handle

        lock_function = 'msvcrt.locking' if os.name == 'nt' else 'fcntl.flock'
        with patch('pathlib.Path.open', new=track_open), patch(lock_function), patch(
            'pc.core.atomic', side_effect=PermissionError('Access denied writing active marker')
        ), patch('pathlib.Path.unlink') as unlink:
            with self.assertRaises(Exception) as raised:
                self.lease.acquire()
        self.assertRegex(str(raised.exception), r'(?i)same Windows user')
        self.assertEqual(len(handles), 1)
        self.assertTrue(handles[0].closed)
        self.assertIsNone(self.lease.handle)
        unlink.assert_not_called()

    def test_release_denied_quarantine_check_closes_handle_without_deletion(self):
        handle = Mock()
        self.lease.handle = handle
        with patch('pathlib.Path.exists', side_effect=PermissionError('Access denied checking quarantine')), patch(
            'pathlib.Path.unlink'
        ) as unlink:
            with self.assertRaises(PermissionError):
                self.lease.release(clean=True)
        handle.close.assert_called_once()
        self.assertIsNone(self.lease.handle)
        unlink.assert_not_called()

    def test_release_denied_active_marker_delete_closes_handle(self):
        handle = Mock()
        self.lease.handle = handle
        with patch('pathlib.Path.exists', return_value=False), patch(
            'pathlib.Path.unlink', side_effect=PermissionError('Access denied deleting active marker')
        ) as unlink:
            with self.assertRaises(PermissionError):
                self.lease.release(clean=True)
        handle.close.assert_called_once()
        self.assertIsNone(self.lease.handle)
        unlink.assert_called_once_with(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
