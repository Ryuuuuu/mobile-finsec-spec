import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest


class Child:
    def __init__(self, root):
        self.proc = subprocess.Popen([sys.executable, '-m', 'integration.mock_stdio',
            '--mock-root', str(root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        self.lines = queue.Queue()
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()
        assert self.receive()['status'] == 'ready'

    def read(self):
        for line in self.proc.stdout:
            self.lines.put(line)

    def receive(self):
        return json.loads(self.lines.get(timeout=5))

    def call(self, op, args):
        payload = dict(contract='mock-ui-request.v1', project_id='synthetic-stdio',
            request_generation=1, operation=op, arguments=args)
        self.proc.stdin.write(json.dumps(payload).encode() + b'\n')
        self.proc.stdin.flush()
        return self.receive()

    def close(self):
        if not self.proc.stdin.closed:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill(); self.proc.wait(timeout=5)
            raise
        finally:
            self.reader.join(timeout=2)
            self.proc.stdout.close(); self.proc.stderr.close()


def request():
    return dict(contract='structural-start.v1', command_id='mock-start',
        device_id='synthetic-device-p4', platform='aos', items=['mock-item'], inventory_revision=1)


class StdioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def child(self):
        child = Child(self.root); self.addCleanup(child.close); return child

    def test_process_roundtrip_completion_and_restart(self):
        child = self.child()
        self.assertTrue(child.call('inspect', {'request': request()})['data']['enabled'])
        reply = child.call('submit', {'request': request()})['data']
        jid = reply['execution_id']; deadline = time.monotonic() + 5
        while True:
            state = child.call('progress', {'execution_id': jid, 'cursor': 0})
            if state['execution']['status'] == 'finished': break
            self.assertLess(time.monotonic(), deadline)
        rid = state['run_id']
        self.assertEqual(child.call('result', {'run_id': rid})['status'], 'ok')
        self.assertEqual(len(child.call('history', {})['runs']), 1)
        child.close(); self.assertEqual(child.proc.returncode, 0)
        restarted = self.child()
        self.assertEqual(restarted.call('submit', {'request': request()})['data']['status'], 'recovery_required')
        self.assertEqual(restarted.call('result', {'run_id': rid})['status'], 'ok')

    def test_killed_process_does_not_repeat_admission(self):
        child = self.child()
        self.assertEqual(child.call('submit', {'request': request()})['data']['status'], 'accepted')
        child.proc.kill(); child.proc.wait(timeout=5)
        restarted = self.child()
        self.assertEqual(restarted.call('submit', {'request': request()})['data']['status'], 'recovery_required')
        # Completion before kill is deliberately unspecified; acceptance is durable.

    def test_invalid_frame_terminates_without_consuming_tail(self):
        child = self.child()
        child.proc.stdin.write(b'{}'); child.proc.stdin.close()
        self.assertEqual(child.receive()['error'], 'INVALID_FRAME')
        child.proc.wait(timeout=5); self.assertEqual(child.proc.returncode, 0)
        self.assertFalse(list((self.root / 'runs').glob('synthetic-*')))
