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
        self.cleanup = None
        self.forced = False
        self.cleanup_lock = threading.Lock()
        self.io_thread = None
        # argv is supplied by a trusted launcher, never by a model or wire request.
        self.process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        try:
            ready = self._transaction(None)
            if not self.valid_handshake(ready):
                raise UnknownOutcome('INVALID_HANDSHAKE')
            self.ready = ready
        except Exception as exc:
            self.uncertain = True
            self.close()
            if not self.closed:
                exc.cleanup_client = self  # Caller retains a handle for cleanup retry.
            raise

    def valid_handshake(self, ready):
        return ready == {'contract': 'mock-stdio.v1', 'status': 'ready', 'synthetic': True}

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
        if not self.cleanup_lock.acquire(blocking=False):
            return {'status': 'cleanup_unconfirmed', 'reason': 'CLEANUP_IN_PROGRESS'}
        try:
            if self.closed: return dict(self.cleanup)
            was_uncertain = self.uncertain
            self.uncertain = True  # Close attempts disable new work, even if cleanup fails.
            active = self.io_thread is not None and self.io_thread.is_alive()
            def force():
                if self.process.poll() is None:
                    self.process.kill()
                    self.forced = True
            try:
                if was_uncertain or active: force()
                if not active: self.process.stdin.close()
                try:
                    self.process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    force(); self.process.wait(timeout=3)
                if self.io_thread is not None: self.io_thread.join(timeout=3)
                if self.io_thread is not None and self.io_thread.is_alive():
                    self.cleanup = {'status': 'cleanup_unconfirmed', 'reason': 'IO_STILL_ACTIVE'}
                    return dict(self.cleanup)
                self.process.stdin.close(); self.process.stdout.close()
            except (OSError, subprocess.TimeoutExpired):
                self.cleanup = {'status': 'cleanup_unconfirmed', 'reason': 'PROCESS_OR_PIPE_CLEANUP_FAILED'}
                return dict(self.cleanup)
            self.closed = True
            self.cleanup = {'status': 'closed', 'forced': self.forced,
                            'exit_code': self.process.returncode}
            return dict(self.cleanup)
        finally:
            self.cleanup_lock.release()
