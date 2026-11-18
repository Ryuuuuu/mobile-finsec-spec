import json
import subprocess
import sys
import unittest
from unittest.mock import patch
from integration.stdio_client import StdioClient, UnknownOutcome


READY = json.dumps({'contract':'mock-stdio.v1','status':'ready','synthetic':True})


class CleanupTests(unittest.TestCase):
    def child(self, tail):
        client=StdioClient([sys.executable,'-c',f'import sys,time\nprint({READY!r},flush=True)\n'+tail])
        self.addCleanup(client.close)
        return client

    def test_eof_cleanup_and_repeat_are_confirmed(self):
        client=self.child('sys.stdin.read()')
        result=client.close()
        self.assertEqual(result,{'status':'closed','forced':False,'exit_code':0})
        self.assertEqual(client.close(),result)
        self.assertTrue(client.process.stdin.closed);self.assertTrue(client.process.stdout.closed)

    def test_ignores_eof_forced_exit_not_task_success(self):
        client=self.child('sys.stdin.read()\ntime.sleep(10)');client.timeout=.1
        result=client.close()
        self.assertEqual(result['status'],'closed');self.assertTrue(result['forced'])
        self.assertIsNotNone(result['exit_code']);self.assertTrue(client.closed)

    def test_injected_kill_failure_retains_retry_and_blocks_work(self):
        client=self.child('time.sleep(10)');client.uncertain=True
        with patch.object(client.process,'kill',side_effect=OSError('PRIVATE_FAILURE')):
            result=client.close()
        self.assertEqual(result['status'],'cleanup_unconfirmed')
        self.assertNotIn('PRIVATE',str(result));self.assertFalse(client.closed)
        self.assertIsNone(client.process.poll())
        with self.assertRaises(UnknownOutcome):client.exchange({})
        result=client.close();self.assertEqual(result['status'],'closed')
        self.assertIsNotNone(client.process.poll())

    def test_startup_failure_preserves_handle_when_cleanup_fails(self):
        code='import time\nprint("{}",flush=True)\ntime.sleep(10)'
        with patch.object(subprocess.Popen,'kill',side_effect=OSError('synthetic failure')):
            with self.assertRaisesRegex(UnknownOutcome,'INVALID_HANDSHAKE') as caught:
                StdioClient([sys.executable,'-c',code])
        client=caught.exception.cleanup_client;self.addCleanup(client.close)
        self.assertFalse(client.closed)
        self.assertEqual(client.close()['status'],'closed')
