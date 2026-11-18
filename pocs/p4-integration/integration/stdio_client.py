"""Deadline-bound synchronous mock IPC client. Run outside the UI thread."""
import json
import math
import queue
import subprocess
import threading
from .ui_wire import LIMIT


class UnknownOutcome(RuntimeError):
    """The channel cannot be reused; this does not mean the request was cancelled."""


class StdioClient:
    def __init__(self, argv, *, cwd=None, timeout=3):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError('INVALID_TIMEOUT')
        self.timeout = timeout
        self.lock = threading.Lock()
        self.uncertain = False
        self.closed = False
        self.io_thread = None
        # argv is supplied by a trusted launcher, never by a model or wire request.
        self.process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        try:
            ready = self._transaction(None)
            if ready != {'contract': 'mock-stdio.v1', 'status': 'ready', 'synthetic': True}:
                raise UnknownOutcome('INVALID_HANDSHAKE')
        except Exception:
            self.uncertain = True
            self.close()
            raise

    def _transaction(self, data):
        result = queue.Queue(maxsize=1)
        def io():
            try:
                if data is not None:
                    remaining = memoryview(data)
                    while remaining:
                        count = self.process.stdin.write(remaining)
                        if not count: raise OSError('PIPE_CLOSED')
                        remaining = remaining[count:]
                raw = self.process.stdout.readline(LIMIT + 2)
                if not raw.endswith(b'\n') or len(raw) > LIMIT + 1:
                    raise ValueError('FRAME')
                reply = json.loads(raw)
                if not isinstance(reply, dict): raise ValueError('SCHEMA')
                result.put((True, reply))
            except (OSError, ValueError, TypeError, RecursionError):
                result.put((False, None))
        self.io_thread = threading.Thread(target=io, daemon=True)
        self.io_thread.start()
        try:
            valid, reply = result.get(timeout=self.timeout)
        except queue.Empty:
            self.uncertain = True
            raise UnknownOutcome('RESPONSE_DEADLINE') from None
        if not valid:
            self.uncertain = True
            raise UnknownOutcome('CHANNEL_INTERRUPTED')
        return reply

    def exchange(self, request):
        if not isinstance(request, dict): raise ValueError('REQUEST_SCHEMA')
        encoded = json.dumps(request, allow_nan=False).encode('utf-8')
        if len(encoded) > LIMIT: raise ValueError('REQUEST_LIMIT')
        if not self.lock.acquire(blocking=False): raise RuntimeError('REQUEST_IN_PROGRESS')
        try:
            if self.closed or self.uncertain: raise UnknownOutcome('CHANNEL_UNUSABLE')
            reply = self._transaction(encoded + b'\n')
            if 'error' not in reply and (reply.get('contract') != 'mock-ui.v1'
                    or reply.get('project_id') != request.get('project_id')
                    or type(reply.get('request_generation')) is not int
                    or reply.get('request_generation') != request.get('request_generation')):
                self.uncertain = True
                raise UnknownOutcome('RESPONSE_MISMATCH')
            return reply
        finally:
            self.lock.release()

    def close(self):
        if self.closed: return
        self.closed = True
        # Kill only this owned mock child if IO is uncertain/in flight. Killing a
        # process does not settle prior admission or prove external cleanup.
        active = self.io_thread is not None and self.io_thread.is_alive()
        if self.process.poll() is None and (self.uncertain or active): self.process.kill()
        if not active: self.process.stdin.close()
        try:
            self.process.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.wait(timeout=3)
        if self.io_thread is not None: self.io_thread.join(timeout=3)
        self.process.stdin.close(); self.process.stdout.close()
