"""Deterministic supervisor around cooperative fake providers and real P2/P3 code.

P3 runs in an owned executor; cancelling its asyncio wrapper does NOT terminate the
thread. Such futures are never cancelled and a surviving future quarantines lease.
This is a synthetic lifecycle test, not a device/process isolation boundary.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
from pathlib import Path
import time
from uuid import uuid4

from .contracts import LIMITATIONS, Plan, ContractError, digest, empty_result, utc
from .history import History, atomic_json
from .lease import LeaseError, LeaseStore
from .p2_adapter import P2Adapter
from .p3_adapter import run_check, snapshot
from .providers import FakeProvider


class StopRun(Exception):
    def __init__(self, code, status='failed', recovery=False):
        super().__init__(code)
        self.code, self.status, self.recovery = code, status, recovery


@dataclass
class Handle:
    run_id: str
    session_id: str
    plan: Plan
    output: Path
    started: float = field(default_factory=time.monotonic)
    started_at: str = field(default_factory=utc)
    state: str = 'created'
    task: object = None
    token: object = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    events: list = field(default_factory=list)
    resources: list = field(default_factory=list)
    uncancellable: list = field(default_factory=list)
    providers: list = field(default_factory=list)
    streams: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    result: dict | None = None
    error_code: str | None = None
    storage_error: bool = False
    contract: dict | None = None
    p2: object = None
    p2_report: dict | None = None
    current_index: int | None = None
    recovery_required: bool = False


class Supervisor:
    def __init__(self, root, *, history_factory=History, p2_factory=P2Adapter,
                 p3_runner=run_check, provider_factory=FakeProvider):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.boot_epoch = str(uuid4())
        self.session_id = 'synthetic-session-' + str(uuid4())
        self.lease = LeaseStore(self.root / 'lease.sqlite')
        self.history = history_factory(self.root / 'history.sqlite')
        self.p2_factory, self.p3_runner, self.provider_factory = p2_factory, p3_runner, provider_factory
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='p4-synthetic-p3')
        self.commands = {}
        self.handles = {}

    def start(self, plan):
        if not isinstance(plan, Plan):
            raise ContractError('PLAN_REQUIRED')
        plan.validate()
        fingerprint = digest(plan.snapshot())
        if plan.command_id in self.commands:
            previous, handle = self.commands[plan.command_id]
            if previous != fingerprint:
                raise ContractError('COMMAND_CONFLICT')
            return handle
        run_id = 'synthetic-run-' + str(uuid4())
        output = self.root / run_id
        output.mkdir()
        handle = Handle(run_id, self.session_id, plan, output)
        handle.rows = [empty_result(i, run_id, self.session_id, 'RUN_NOT_STARTED') for i in plan.items]
        self.commands[plan.command_id] = fingerprint, handle
        self.handles[run_id] = handle
        handle.task = asyncio.create_task(self._execute(handle), name=run_id)
        return handle

    def cancel(self, run_id):
        handle = self.handles[run_id]
        if handle.state in {'finalizing', 'completed', 'failed', 'cancelled', 'finalizing_failed'}:
            return {'run_id': run_id, 'state': handle.state, 'cancel_requested': handle.cancel_event.is_set()}
        if not handle.cancel_event.is_set():
            handle.cancel_event.set()
            self._state(handle, 'cancelling')
            if handle.token and self.lease.inspect()['lifecycle'] != 'recovery_required':
                self.lease.begin_cleanup(handle.token)
        return {'run_id': run_id, 'state': handle.state, 'cancel_requested': True}

    def events_after(self, run_id, after_seq=0):
        # Return copies: a viewer cannot mutate the supervisor's event state.
        return json.loads(json.dumps([e for e in self.handles[run_id].events if e['seq'] > after_seq]))

    def _emit(self, h, kind, payload=None, *, item=None, source='supervisor', tool_call_id=None):
        event = dict(schema_version='1.0', synthetic=True, event_id=str(uuid4()),
                     session_id=h.session_id, run_id=h.run_id, item_id=item.item_id if item else None,
                     check_id=item.check_id if item else None, tool_call_id=tool_call_id,
                     seq=len(h.events) + 1, timestamp=utc(), source=source, type=kind,
                     verdict=None, payload=payload or {})
        h.events.append(event)
        try:
            with (h.output / 'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        except OSError:
            h.storage_error = True

    def _state(self, h, state):
        h.state = state
        self._emit(h, 'run_state', {'state': state})

    def _check(self, h, item_started=None):
        if h.cancel_event.is_set():
            raise StopRun('RUN_CANCELLED', 'cancelled')
        now = time.monotonic()
        if now - h.started > h.plan.run_timeout:
            raise StopRun('RUN_TIMEOUT', 'timed_out')
        if item_started is not None and now - item_started > h.plan.item_timeout:
            raise StopRun('ITEM_TIMEOUT', 'timed_out')

    async def _watch(self, h, future, role, *, job=None, item_started=None):
        began = time.monotonic()
        while True:
            self._check(h, item_started)
            if future.done():
                if future.cancelled():
                    raise StopRun(role + '_EXIT')
                try:
                    return future.result()
                except (Exception, asyncio.CancelledError) as exc:
                    raise StopRun(role + '_ERROR') from exc
            now = time.monotonic()
            if job is not None:
                if now - job.heartbeat > h.plan.heartbeat_timeout:
                    raise StopRun(role + '_HEARTBEAT_LOST', 'timed_out')
                if now - job.last_progress > h.plan.progress_timeout:
                    raise StopRun(role + '_HANG', 'timed_out')
            elif now - began > h.plan.tool_timeout:
                raise StopRun('TOOL_TIMEOUT', 'timed_out')
            await asyncio.sleep(0.005)

    async def _stream(self, h, provider, job, item, token):
        async for event in provider.stream_events(job.job_id):
            if not h.cancel_event.is_set() and h.state == 'running' and h.token:
                try:
                    self.lease.authorize(token, 'p3.check' if item else 'p2.capture')
                except LeaseError:
                    continue
                self._emit(h, 'provider_event', event, item=item, source='fake_provider')

    async def _provider_call(self, h, role, phase, operation, item, item_started):
        # Track the RPC itself: a provider can stall before returning a job or result.
        future = asyncio.create_task(operation)
        h.resources.append(future)
        self._emit(h, 'provider_call_started', {'role': role, 'phase': phase}, item=item)
        try:
            result = await self._watch(h, future, role.upper() + '_' + phase.upper(),
                                       item_started=item_started)
        except StopRun as exc:
            code = role.upper() + '_' + phase.upper() + '_TIMEOUT' if exc.code == 'TOOL_TIMEOUT' else exc.code
            self._emit(h, 'provider_call_stopped', {'role': role, 'phase': phase,
                       'reason_code': code}, item=item)
            # Failed admission may have created work without returning its handle.
            # A retry could duplicate it; keep the lease blocked for explicit recovery.
            raise StopRun(code, exc.status, recovery=phase == 'start' or exc.recovery) from exc
        self._emit(h, 'provider_call_finished', {'role': role, 'phase': phase}, item=item)
        return result

    async def _provider(self, h, role, behavior, item=None, item_started=None):
        self._check(h, item_started)
        provider = self.provider_factory(behavior=behavior, name=h.plan.provider_name,
                                         cancellation=h.plan.cancellation_supported,
                                         delay=0.4 if behavior == 'ignores_cancel' else 0.02)
        caps = provider.capabilities()
        if (not all(caps.get(k) for k in ('cancellation', 'structured_output', 'streaming', 'local_only'))
                or caps.get('gateway_enforcement') != 'fake_cooperative'):
            raise StopRun('PROVIDER_CAPABILITY_UNAVAILABLE')
        context = {'role': role, 'selected_items': [i.item_id for i in h.plan.items]}
        if item:
            context.update(item_id=item.item_id, variant=item.variant)
        job = await self._provider_call(h, role, 'start',
            provider.start_job(context, ('p3.check',) if item else ()), item, item_started)
        h.providers.append((provider, job))
        h.resources.append(job.task)
        h.streams.append(asyncio.create_task(self._stream(h, provider, job, item, h.token)))
        self._emit(h, 'provider_started', {'role': role, 'job_id': job.job_id,
                   'capabilities': caps}, item=item, source='fake_provider')
        await self._watch(h, job.task, role.upper(), job=job, item_started=item_started)
        result = await self._provider_call(h, role, 'result',
            provider.get_result(job.job_id), item, item_started)
        if result is None:
            raise StopRun(role.upper() + '_EXIT')
        return result

    async def _tool(self, h, item, item_started, attempt_id):
        self.lease.authorize(h.token, 'p3.check')
        tool_call_id = 'synthetic-tool-' + str(uuid4())
        self._emit(h, 'tool_started', {'operation': 'p3.check'}, item=item, tool_call_id=tool_call_id)
        if item.tool_fault == 'disconnect':
            raise StopRun('DEVICE_DISCONNECTED', recovery=True)
        if item.tool_fault == 'error':
            raise StopRun('TOOL_ERROR')
        if item.tool_fault == 'timeout':
            future = asyncio.create_task(asyncio.sleep(h.plan.tool_timeout + 1))
        else:
            concurrent = self.executor.submit(self.p3_runner, item.variant, h.output / item.item_id,
                                              run_id=h.run_id, session_id=h.session_id,
                                              attempt_id=attempt_id, device_id=h.plan.device_id,
                                              expected_snapshot=h.contract,
                                              cleanup_fault=item.cleanup_fault)
            future = asyncio.wrap_future(concurrent)
            h.uncancellable.append(future)
        h.resources.append(future)
        report = await self._watch(h, future, 'TOOL', item_started=item_started)
        self._emit(h, 'tool_finished', {'operation': 'p3.check', 'source': 'real_p3_synthetic'},
                   item=item, tool_call_id=tool_call_id)
        return report

    async def _execute(self, h):
        status, code = 'completed', 'RUN_COMPLETED'
        cleanup = {'status': 'completed', 'reason_code': 'NO_RESOURCES'}
        try:
            self._state(h, 'preflight')
            preflight_error = None
            try:
                h.contract = snapshot()
            except Exception:
                preflight_error = 'PREFLIGHT_CONTRACT_ERROR'
            provider_caps = self.provider_factory(name=h.plan.provider_name,
                               cancellation=h.plan.cancellation_supported).capabilities()
            atomic_json(h.output / 'run.json', dict(schema_version='1.0', synthetic=True,
                        run_id=h.run_id, session_id=h.session_id, plan=h.plan.snapshot(),
                        config_hash=digest(h.plan.snapshot()), contract_snapshot=h.contract,
                        provider_snapshot=provider_caps, started_at=h.started_at,
                        limitations=LIMITATIONS, route={'status': 'unavailable', 'reason': 'P1_NOT_INTEGRATED'}))
            self._check(h)
            if preflight_error:
                raise StopRun(preflight_error)
            if not provider_caps.get('cancellation'):
                raise StopRun('PROVIDER_CAPABILITY_UNAVAILABLE')
            h.token = self.lease.acquire(h.run_id, self.boot_epoch)
            if h.token is None:
                raise StopRun('DEVICE_BUSY_OR_RECOVERY_REQUIRED')
            self._state(h, 'preparing')
            self._check(h)
            self.lease.authorize(h.token, 'p2.capture')
            h.p2 = self.p2_factory(h.output, h.run_id, h.session_id)
            capture = asyncio.create_task(h.p2.capture(proxy_on=h.plan.proxy_on))
            h.resources.append(capture)
            try:
                h.p2_report = await self._watch(h, capture, 'PROXY')
            except StopRun as exc:
                if exc.code == 'PROXY_ERROR':
                    self._emit(h, 'proxy_error', {'reason_code': exc.code})
                raise
            self._emit(h, 'recording_sealed', {'recording_id': h.p2_report['recording_id'],
                       'coverage': h.p2_report['network_coverage']})
            self._state(h, 'running')
            main = await self._provider(h, 'main', h.plan.main_behavior)
            if main != {'selected_items': [i.item_id for i in h.plan.items]}:
                raise StopRun('MAIN_SCOPE_VIOLATION', recovery=True)
            for index, item in enumerate(h.plan.items):
                self._check(h)
                h.current_index = index
                item_started = time.monotonic()
                attempt_id = 'synthetic-attempt-' + str(uuid4())
                h.token = self.lease.activate_attempt(h.token, attempt_id)
                self._emit(h, 'item_running', {'attempt_id': attempt_id,
                           'generation': h.token.generation}, item=item)
                proposal = await self._provider(h, 'item', item.provider_behavior, item, item_started)
                if proposal != {'operation': 'p3.check', 'variant': item.variant}:
                    raise StopRun('ITEM_SCOPE_VIOLATION', recovery=True)
                report = await self._tool(h, item, item_started, attempt_id)
                raw = report['result']
                row = empty_result(item, h.run_id, h.session_id, raw['reason_code'], raw['execution_status'])
                row.update(attempt_id=attempt_id, verdict=raw['verdict'],
                           verdict_label={'pass': '양호', 'fail': '취약', 'inconclusive': '판단 불가능'}[raw['verdict']],
                           reason=raw['reason'], evidence_refs=report['evidence_refs'],
                           tested_scope=raw['tested_scope'], p3=report, cleanup_status=raw['cleanup_status'],
                           limitations=list(dict.fromkeys([*LIMITATIONS, *raw['limitations']])))
                h.rows[index] = row
                self.lease.begin_cleanup(h.token)
                self._emit(h, 'item_cleaning', {'status': raw['cleanup_status']}, item=item)
                next_token = self.lease.finish_item(h.token, terminated=True, cleanup_status=raw['cleanup_status'])
                if next_token is None:
                    h.recovery_required = True
                    raise StopRun('CLEANUP_' + raw['cleanup_status'].upper(), recovery=True)
                h.token = next_token
                self._emit(h, 'item_terminal', {'execution_status': row['execution_status']}, item=item)
                h.current_index = None
                if raw['execution_status'] != 'completed':
                    raise StopRun('P3_EXECUTION_' + raw['execution_status'].upper())
        except asyncio.CancelledError:
            # Internal task cancellation is also a stop, never a completed run.
            h.cancel_event.set()
            status, code = 'cancelled', 'SUPERVISOR_CANCELLED'
            self._state(h, 'cancelling')
            if h.current_index is not None and h.rows[h.current_index]['p3'] is None:
                h.rows[h.current_index] = empty_result(h.plan.items[h.current_index], h.run_id,
                                                      h.session_id, code, 'cancelled')
        except StopRun as exc:
            code = exc.code
            status = 'cancelled' if exc.status == 'cancelled' else 'failed'
            h.recovery_required |= exc.recovery
            if h.current_index is not None and h.rows[h.current_index]['p3'] is None:
                item = h.plan.items[h.current_index]
                h.rows[h.current_index] = empty_result(item, h.run_id, h.session_id, code, exc.status)
            self._emit(h, 'execution_stopped', {'reason_code': code, 'execution_status': exc.status})
        except OSError:
            status, code = 'failed', 'STORAGE_ERROR'
            h.storage_error = True
        except Exception as exc:
            status, code = 'failed', 'SUPERVISOR_ERROR'
            # Record type only: provider/tool exceptions are untrusted data, not arbitrary log text.
            self._emit(h, 'execution_stopped', {'reason_code': code, 'error_type': type(exc).__name__})
            if h.current_index is not None and h.rows[h.current_index]['p3'] is None:
                h.rows[h.current_index] = empty_result(h.plan.items[h.current_index], h.run_id,
                                                      h.session_id, code, 'failed')
        finally:
            if h.token:
                try:
                    cleanup = await self._cleanup(h)
                except (Exception, asyncio.CancelledError) as exc:
                    # Leave any durable active/cleaning lease blocked when proof fails.
                    cleanup = {'status': 'unknown', 'reason_code': 'CLEANUP_EXCEPTION',
                               'error_type': type(exc).__name__, 'terminated': False}
                    try:
                        if self.lease.inspect()['lifecycle'] != 'recovery_required':
                            self.lease.begin_cleanup(h.token)
                            self.lease.release(h.token, terminated=False, cleanup_status='unknown')
                    except Exception:
                        pass  # DB may itself be unavailable; no safe release was issued.
                if cleanup['status'] != 'completed':
                    h.recovery_required = True
                    if status == 'completed':
                        status, code = 'failed', 'CLEANUP_' + cleanup['status'].upper()
            for index, row in enumerate(h.rows):
                if row['reason_code'] == 'RUN_NOT_STARTED':
                    h.rows[index] = empty_result(h.plan.items[index], h.run_id, h.session_id,
                                                'RUN_CANCELLED_BEFORE_START' if status == 'cancelled' else code)
            self._state(h, 'finalizing')
            final = dict(schema_version='1.0', synthetic=True, run_id=h.run_id, session_id=h.session_id,
                         execution_status=status, reason_code=code,
                         selected_item_ids=[i.item_id for i in h.plan.items], items=h.rows,
                         verdict_counts={v: sum(r['verdict'] == v for r in h.rows)
                                         for v in ('pass', 'fail', 'inconclusive')},
                         cleanup_status=cleanup['status'], cleanup=cleanup,
                         recovery_required=h.recovery_required, p2=h.p2_report,
                         started_at=h.started_at, ended_at=utc(),
                         duration_monotonic_ms=round((time.monotonic() - h.started) * 1000, 3),
                         finalized=True, finalization_version='1.0', limitations=LIMITATIONS)
            try:
                if h.storage_error:
                    raise OSError('LIVE_EVENT_STORAGE_FAILED')
                self.history.finalize(final, h.output, h.contract)
                h.result = final
                self._state(h, status)
            except Exception as exc:
                h.error_code = 'FINALIZATION_FAILED'
                self._state(h, 'finalizing_failed')
                self._emit(h, 'finalization_error', {'reason_code': h.error_code, 'error_type': type(exc).__name__})
        return h.result

    async def _cleanup(self, h):
        # Recovery state from an item cleanup failure must not be accidentally cleared.
        lease_state = self.lease.inspect()
        if lease_state['lifecycle'] != 'recovery_required':
            self.lease.begin_cleanup(h.token)
        cancel_requests = [asyncio.create_task(provider.cancel(job.job_id))
                           for provider, job in h.providers if not job.task.done()]
        h.resources.extend(cancel_requests)
        if cancel_requests:
            await asyncio.wait(cancel_requests, timeout=h.plan.cancel_grace)
        cancel_failed = any(f.done() and (f.cancelled() or f.exception() is not None)
                            for f in cancel_requests)
        pending = [f for f in h.resources if not f.done()]
        if pending:
            _, pending_set = await asyncio.wait(pending, timeout=h.plan.cancel_grace)
            for future in pending_set:
                if future not in h.uncancellable:
                    future.cancel()
            if pending_set:
                await asyncio.wait(pending_set, timeout=h.plan.cancel_grace)
        terminated = all(f.done() for f in h.resources)
        for future in h.resources:
            if future.done() and not future.cancelled():
                future.exception()  # retrieve failures without making them security verdicts
        cleanup = {'status': 'completed', 'reason_code': 'ALL_TRACKED_WORK_STOPPED'}
        if h.p2:
            task = asyncio.create_task(h.p2.cleanup())
            h.resources.append(task)
            done, _ = await asyncio.wait([task], timeout=h.plan.cleanup_timeout)
            if done:
                try:
                    cleanup = task.result()
                except asyncio.CancelledError:
                    terminated = False
                    cleanup = {'status': 'unknown', 'reason_code': 'PROXY_CLEANUP_CANCELLED'}
                except Exception:
                    cleanup = {'status': 'failed', 'reason_code': 'PROXY_CLEANUP_ERROR'}
            else:
                terminated = False
                cleanup = {'status': 'unknown', 'reason_code': 'PROXY_CLEANUP_TIMEOUT'}
        for stream in h.streams:
            if not stream.done():
                stream.cancel()
        if h.streams:
            await asyncio.gather(*h.streams, return_exceptions=True)
        if cancel_failed:
            cleanup = dict(cleanup, status='failed', reason_code='PROVIDER_CANCEL_ERROR')
        if not terminated or h.recovery_required:
            unknown = not terminated or not any(row['cleanup_status'] == 'failed' for row in h.rows)
            cleanup = dict(cleanup, status='unknown' if unknown else 'failed',
                           reason_code='WORKER_STILL_ALIVE' if not terminated else 'RECOVERY_REQUIRED')
        if lease_state['lifecycle'] != 'recovery_required':
            self.lease.release(h.token, terminated=terminated, cleanup_status=cleanup['status'])
        self._emit(h, 'cleanup_finished', {'status': cleanup['status'], 'terminated': terminated,
                   'recovery_required': cleanup['status'] != 'completed'})
        return dict(cleanup, terminated=terminated)

    async def close(self):
        # Test/CLI teardown only; never clears persisted quarantine.
        pending = [f for h in self.handles.values() for f in h.resources if not f.done()]
        if pending:
            await asyncio.wait(pending, timeout=2)
        self.executor.shutdown(wait=False, cancel_futures=False)
