"""Sequential existing CombinedRun replay; no automatic reset or recovery."""
import copy
import hashlib
import json
import threading
from .core import Journal, atomic
from . import protocol


class CancellationScope:
    """Per-route clear cannot erase the enclosing queue cancellation."""
    def __init__(self, inner, outer):
        self.inner, self.outer = inner, outer
    def clear(self):
        self.inner.clear()
    def set(self):
        self.inner.set()
    def is_set(self):
        return self.outer.is_set() or self.inner.is_set()
    def wait(self, timeout=None):
        return self.is_set() or self.inner.wait(timeout)


class ReplayQueue:
    def __init__(self, combined, output):
        self.combined = combined
        self.output = output
        self.guard = threading.Lock()
        self.cancelled = threading.Event()
        self.running = False
        self.blocked = False
        self.journal = None
        self.prepare = None  # Explicit owner-supplied QA preparation only.
        self.on_state = None

    def cancel(self):
        self.cancelled.set()
        self.combined.engine.stop_requested()

    def run(self, routes, *, reset_cancel=True):
        if not self.guard.acquire(blocking=False):
            raise RuntimeError('Replay queue already running')
        original_cancel = self.combined.engine.cancel
        try:
            if self.blocked:
                raise RuntimeError('Queue storage outcome requires review; no automatic retry')
            if self.combined.state != 'idle' or self.combined.engine.mode != 'idle':
                raise RuntimeError('Replay queue requires reconciled idle state')
            if not routes or len(routes) > 100:
                raise ValueError('Select 1 to 100 ordered routes')
            routes = copy.deepcopy(routes)
            for route in routes:
                protocol.route(route)
            if reset_cancel:self.cancelled.clear()
            self.combined.engine.cancel = CancellationScope(original_cancel, self.cancelled)
            self.running = True
            self.journal = Journal(self.output, 'replay-queue')
            result = dict(schema_version=1, queue_id=self.journal.id, status='running',
                          policy='stop_remaining_pending_product_decision', entries=[])
            for route in routes:
                digest = hashlib.sha256(json.dumps(route, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                result['entries'].append(dict(source_recording_id=route['recording_id'], source_sha256=digest, status='not_run'))
            def save():
                try:
                    atomic(self.journal.path/'queue.json', result)
                except OSError:
                    self.blocked = True
                    raise
                if self.on_state is not None:self.on_state(copy.deepcopy(result))
            save()  # Do not dispatch if the ordered intent cannot be persisted.
            for index, route in enumerate(routes):
                if self.cancelled.is_set():
                    result['status'] = 'cancelled'
                    break
                entry = result['entries'][index]
                entry['status'] = 'preparing'
                save()
                previous = self.combined.j
                try:
                    if self.prepare is not None:
                        self.prepare(index, route)
                    if self.cancelled.is_set():
                        raise InterruptedError('Queue cancelled before route dispatch')
                    entry['status'] = 'running'
                    save()
                    replay = self.combined.replay(route)
                    entry.update(status=replay['status'], replay_run_id=replay['run_id'])
                    entry.update(combined_id=self.combined.link['combined_id'],
                                 network_recording_id=self.combined.link['network_recording_id'])
                    if self.cancelled.is_set() or replay['status'] != 'succeeded' or self.combined.state != 'idle':
                        result['status'] = 'cancelled' if self.cancelled.is_set() else 'partial'
                        save()
                        break
                    save()  # Persist terminal route/P2 linkage before admitting next.
                except Exception as error:
                    entry['status'] = 'incomplete'
                    entry['reason'] = type(error).__name__
                    if self.combined.j is not None and self.combined.j is not previous:
                        entry['combined_id'] = self.combined.j.id
                        for field in ('network_recording_id', 'input_recording_id'):
                            if field in self.combined.link:
                                entry[field] = self.combined.link[field]
                    result['status'] = 'cancelled' if self.cancelled.is_set() else 'partial'
                    save()
                    break
            else:
                result['status'] = 'succeeded'
            save()
            return result
        finally:
            if self.cancelled.is_set():
                original_cancel.set()
            self.combined.engine.cancel = original_cancel
            self.running = False
            self.guard.release()
