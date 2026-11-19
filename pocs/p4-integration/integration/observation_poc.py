"""Synthetic observation contract exerciser; NOT an executable agent sandbox.

Only fixed QA states and a fixed fake reviewer are accepted. No provider, plugin,
callback, device, shell or network interface is exposed. Real reviewers stay
unavailable until isolation is independently established.
"""
import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import uuid


STATES = frozenset(('QA_READY', 'QA_SENT', 'QA_OTHER'))
PHASES = frozenset(('before_dispatch', 'after_postcondition'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', value):
        raise ValueError('INVALID_SYNTHETIC_IDENTIFIER')


@dataclass(frozen=True)
class Route:
    recording_id: str
    version: str
    occurrence: int
    steps: tuple[str, ...]
    source_hash: str = ''

    @property
    def content_hash(self):
        return digest(dict(recording_id=self.recording_id, version=self.version,
                           steps=self.steps, source_hash=self.source_hash))


@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str
    check_id: str
    recording_id: str
    route_version: str
    route_hash: str
    occurrence: int
    step_id: str
    phase: str
    expected: str


@dataclass(frozen=True)
class Applicability:
    check_id: str
    recording_id: str
    occurrence: int
    status: str
    reason: str


APPLICABILITY_REASONS = {'applicable': 'QA_REQUIRED',
                         'not_applicable': 'QA_NOT_APPLICABLE', 'unknown': 'QA_SCOPE_UNKNOWN'}


@dataclass(frozen=True)
class Plan:
    routes: tuple[Route, ...]
    checkpoints: tuple[Checkpoint, ...]
    capture_timeout: float = 0.02
    review_timeout: float = 0.1
    schema_version: int = 1
    selected_check_ids: tuple[str, ...] = ()
    applicability: tuple[Applicability, ...] = ()
    observation_metadata_hash: str = ''

    @property
    def content_hash(self):
        value = asdict(self)
        if self.schema_version == 1:
            # Preserve existing approved v1 plan hashes exactly.
            value.pop('selected_check_ids'); value.pop('applicability'); value.pop('observation_metadata_hash')
        return digest(value)

    def validate(self, approved_hash):
        if type(self.schema_version) is not int or self.schema_version not in (1,2) or approved_hash != self.content_hash:
            raise ValueError('VERSION_OR_APPROVAL_MISMATCH')
        if not isinstance(self.routes, tuple) or not isinstance(self.checkpoints, tuple):
            raise ValueError('IMMUTABLE_PLAN_REQUIRED')
        if not 0 < self.capture_timeout <= 1 or not 0 < self.review_timeout <= 30:
            raise ValueError('INVALID_DEADLINE')
        if not 1 <= len(self.routes) <= 10 or not (1 if self.schema_version==1 else 0) <= len(self.checkpoints) <= 100:
            raise ValueError('PLAN_LIMIT')
        routes = {}
        for route in self.routes:
            for value in (route.recording_id, route.version, *route.steps):
                identifier(value)
            if (type(route.occurrence) is not int or route.occurrence < 0
                    or not isinstance(route.steps, tuple) or not 1 <= len(route.steps) <= 20
                    or len(set(route.steps)) != len(route.steps)):
                raise ValueError('INVALID_ROUTE')
            key = (route.recording_id, route.occurrence)
            if route.source_hash and not re.fullmatch(r'[0-9a-f]{64}',route.source_hash):
                raise ValueError('INVALID_SOURCE_HASH')
            if key in routes:
                raise ValueError('DUPLICATE_ROUTE_INSTANCE')
            routes[key] = route
        matrix = {}
        if self.schema_version == 1:
            if self.selected_check_ids != () or self.applicability != () or self.observation_metadata_hash:
                raise ValueError('V1_APPLICABILITY_UNSUPPORTED')
        else:
            if self.observation_metadata_hash and not re.fullmatch(r'[0-9a-f]{64}',self.observation_metadata_hash):
                raise ValueError('INVALID_OBSERVATION_METADATA_HASH')
            if (type(self.selected_check_ids) is not tuple or not 1 <= len(self.selected_check_ids) <= 10
                    or type(self.applicability) is not tuple or len(self.applicability) > 100):
                raise ValueError('APPLICABILITY_LIMIT_OR_MUTABILITY')
            for check in self.selected_check_ids: identifier(check)
            if len(set(self.selected_check_ids)) != len(self.selected_check_ids):
                raise ValueError('DUPLICATE_SELECTED_CHECK')
            for cell in self.applicability:
                if type(cell) is not Applicability or type(cell.occurrence) is not int:
                    raise ValueError('INVALID_APPLICABILITY')
                identifier(cell.check_id); identifier(cell.recording_id)
                if type(cell.status) is not str or type(cell.reason) is not str:
                    raise ValueError('INVALID_APPLICABILITY')
                key = (cell.check_id, cell.recording_id, cell.occurrence)
                if (cell.check_id not in self.selected_check_ids or (cell.recording_id,cell.occurrence) not in routes
                        or cell.status not in APPLICABILITY_REASONS or cell.reason != APPLICABILITY_REASONS[cell.status]):
                    raise ValueError('INVALID_APPLICABILITY')
                if key in matrix: raise ValueError('DUPLICATE_APPLICABILITY')
                matrix[key] = cell
            expected = {(c,rid,occ) for c in self.selected_check_ids for rid,occ in routes}
            if set(matrix) != expected: raise ValueError('INCOMPLETE_APPLICABILITY')
        keys = set()
        for cp in self.checkpoints:
            for value in (cp.checkpoint_id, cp.check_id, cp.step_id):
                identifier(value)
            route = routes.get((cp.recording_id, cp.occurrence))
            if (route is None or cp.route_hash != route.content_hash
                    or cp.route_version != route.version or cp.step_id not in route.steps):
                raise ValueError('CHECKPOINT_ROUTE_MISMATCH')
            if cp.phase not in PHASES or cp.expected not in STATES:
                raise ValueError('UNSUPPORTED_OBSERVATION')
            if self.schema_version == 2:
                cell = matrix.get((cp.check_id,cp.recording_id,cp.occurrence))
                if type(cp.occurrence) is not int or cell is None or cell.status != 'applicable':
                    raise ValueError('CHECKPOINT_APPLICABILITY_CONTRADICTION')
            key = (cp.check_id, cp.recording_id, cp.occurrence, cp.checkpoint_id)
            if key in keys:
                raise ValueError('DUPLICATE_CHECKPOINT')
            keys.add(key)


@dataclass(frozen=True)
class Scene:
    before: str = 'QA_READY'
    after: str = 'QA_SENT'
    capture_delay: float = 0
    missing: bool = False
    input_failed: bool = False


@dataclass(frozen=True)
class Snapshot:
    key: str
    observed_state: str
    content_hash: str


@dataclass(frozen=True)
class FakeReview:
    delay: float = 0
    error: bool = False


async def _fixed_fake_review(snapshot, configuration):
    """Data-only fake: no owner, file path, event writer or execution capability."""
    if type(snapshot) is not Snapshot:
        raise ValueError('FIXED_SNAPSHOT_REQUIRED')
    await asyncio.sleep(configuration.delay)
    return 'REVIEW_ERROR' if configuration.error else 'OBSERVATION_ONLY'


class SyntheticDeviceSlot:
    """Only in-process ownership for this synthetic runner; not an OS device lock."""
    busy = False


class ObservationPOC:
    def __init__(self, root, plan, approved_hash, slot, review=FakeReview()):
        plan.validate(approved_hash)
        if type(review) is not FakeReview or not 0 <= review.delay <= 10:
            raise ValueError('REAL_REVIEWER_UNAVAILABLE')
        self.plan, self.slot, self.review = plan, slot, review
        self.run_id, self.attempt_id = uuid.uuid4().hex, uuid.uuid4().hex
        self.root = Path(root) / self.run_id
        self.root.mkdir(parents=True, exist_ok=False)
        self.root.joinpath('evidence').mkdir()
        self.rows = {self.key(cp): dict(checkpoint=asdict(cp), collection='STEP_NOT_REACHED',
                     review='NOT_REVIEWED', evidence_ref=None, verdict='inconclusive',
                     reason='STEP_NOT_REACHED', enforcement_verified=False)
                     for cp in plan.checkpoints}
        self.events, self.snapshots, self.tasks = [], {}, []
        self.cancel = asyncio.Event()
        self.review_lock = asyncio.Lock()
        self.replay_status, self.phase = 'not_started', 'created'
        self.final = None
        self.started = False

    def key(self, cp):
        return digest(dict(project='synthetic-qa', run=self.run_id, attempt=self.attempt_id,
                           plan=self.plan.content_hash, **asdict(cp), evidence_kind='qa_state'))

    def event(self, kind, **fields):
        event = dict(sequence=len(self.events)+1, event=kind, **fields)
        # Failure to persist an execution event aborts the synthetic replay.
        with (self.root/'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, sort_keys=True)+'\n')
        self.events.append(event)

    def seal(self, key, state):
        if key not in self.rows or state not in STATES:
            raise ValueError('EVIDENCE_SCOPE_OR_PRIVACY_REJECTED')
        snapshot = Snapshot(key, state, digest(dict(state=state)))
        if key in self.snapshots:
            if snapshot != self.snapshots[key]:
                raise ValueError('EVIDENCE_CONFLICT')
            return False
        if self.final is not None or self.phase in ('cancelled', 'finalizing_failed'):
            raise ValueError('SEALED_RUN')
        path = self.root/'evidence'/(key+'.json')
        with path.open('x', encoding='utf-8') as stream:
            json.dump(asdict(snapshot), stream)
        self.snapshots[key] = snapshot
        self.rows[key].update(collection='SEALED', evidence_ref='evidence/'+path.name,
                              review='REVIEW_PENDING', reason='REVIEW_PENDING')
        self.event('evidence_sealed', key=key)
        return True

    async def capture(self, cp, scene):
        key = self.key(cp)
        self.event('checkpoint_reached', key=key, phase=cp.phase)
        try:
            # Models a bounded snapshot acquisition BEFORE the next input.
            await asyncio.wait_for(asyncio.sleep(scene.capture_delay), self.plan.capture_timeout)
            state = scene.before if cp.phase == 'before_dispatch' else scene.after
            reason = ('EVIDENCE_PRIVACY_EXCLUDED' if state not in STATES else
                      'EVIDENCE_INSUFFICIENT' if scene.missing else
                      'STATE_MISMATCH' if state != cp.expected else None)
            if reason is None:
                if self.seal(key, state):
                    queued_at = asyncio.get_running_loop().time()
                    deadline = queued_at + self.plan.review_timeout
                    self.event('review_queued', key=key, queued_at_monotonic=queued_at,
                               deadline_monotonic=deadline)
                    self.tasks.append(asyncio.create_task(self.review_one(self.snapshots[key], deadline)))
                return
        except asyncio.TimeoutError:
            reason = 'CAPTURE_TIMEOUT'
        self.rows[key].update(collection=reason, reason=reason)
        self.event('evidence_gap', key=key, reason=reason)

    def accept_review(self, snapshot, reason):
        if snapshot.key not in self.snapshots or self.snapshots[snapshot.key] != snapshot:
            raise ValueError('REVIEW_SCOPE_MISMATCH')
        if self.final is not None or self.cancel.is_set():
            self.event('late_review_ignored', key=snapshot.key)
            return False
        if reason not in ('OBSERVATION_ONLY', 'REVIEW_TIMEOUT', 'REVIEW_QUEUE_EXPIRED', 'REVIEW_ERROR'):
            raise ValueError('INVALID_FAKE_RESULT')
        self.rows[snapshot.key].update(review=reason, reason=reason)
        self.event('review_finished', key=snapshot.key, reason=reason)
        return True

    async def review_one(self, snapshot, deadline):
        loop = asyncio.get_running_loop()
        started = False
        async def dispatch():
            nonlocal started
            async with self.review_lock:
                if loop.time() >= deadline:
                    return 'REVIEW_QUEUE_EXPIRED'
                self.event('review_started', key=snapshot.key, started_at_monotonic=loop.time())
                started = True
                if loop.time() >= deadline:
                    return 'REVIEW_TIMEOUT'
                return await _fixed_fake_review(snapshot, self.review)
        try:
            remaining = deadline - loop.time()
            reason = (await asyncio.wait_for(dispatch(), remaining)
                      if remaining > 0 else 'REVIEW_QUEUE_EXPIRED')
        except asyncio.TimeoutError:
            reason = 'REVIEW_TIMEOUT' if started else 'REVIEW_QUEUE_EXPIRED'
        self.accept_review(snapshot, reason)

    async def run(self, scenes):
        if self.started or self.slot.busy:
            raise RuntimeError('BUSY_OR_ALREADY_STARTED')
        # Copy fixture inputs before any await; no live caller-controlled objects.
        scenes = dict(scenes)
        if any(type(s) is not Scene or not 0 <= s.capture_delay <= 10 for s in scenes.values()):
            raise ValueError('SYNTHETIC_SCENE_REQUIRED')
        self.started, self.slot.busy = True, True
        self.replay_status, self.phase = 'running', 'replaying'
        try:
            self.event('plan_validated', plan_hash=self.plan.content_hash)
            for route in self.plan.routes:
                if self.cancel.is_set() or self.replay_status == 'failed':
                    break
                self.event('route_started', recording_id=route.recording_id, occurrence=route.occurrence)
                for step in route.steps:
                    if self.cancel.is_set():
                        break
                    scene = scenes.get((route.recording_id, route.occurrence, step))
                    if scene is None:
                        self.replay_status = 'failed'
                        self.event('input_fixture_missing', step=step)
                        break
                    cps = [c for c in self.plan.checkpoints if
                           (c.recording_id,c.occurrence,c.step_id)==(route.recording_id,route.occurrence,step)]
                    for cp in cps:
                        if cp.phase == 'before_dispatch':
                            await self.capture(cp, scene)
                    if self.cancel.is_set():
                        break
                    self.event('synthetic_input', recording_id=route.recording_id, step=step)
                    if scene.input_failed:
                        self.replay_status = 'failed'
                        self.event('input_failed', step=step)
                        break
                    for cp in cps:
                        if cp.phase == 'after_postcondition':
                            await self.capture(cp, scene)
                    await asyncio.sleep(0)
                self.event('route_ended', recording_id=route.recording_id)
            if self.cancel.is_set():
                self.replay_status = 'cancelled'
            elif self.replay_status != 'failed':
                self.replay_status = 'completed'
            self.event('replay_finished', status=self.replay_status)
        except BaseException:
            self.phase = 'finalizing_failed'
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            raise
        finally:
            self.slot.busy = False
        return await self.finalize_reviews()

    async def finalize_reviews(self):
        """Called by a trusted host only after replay and its ownership cleanup."""
        self.phase = 'review_pending'
        self.event('review_pending')
        if self.cancel.is_set():
            for task in self.tasks:
                task.cancel()
        outcomes = await asyncio.gather(*self.tasks, return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError):
                self.phase = 'finalizing_failed'
                raise outcome
        if self.cancel.is_set():
            for row in self.rows.values():
                if row['review'] == 'REVIEW_PENDING':
                    row.update(review='REVIEW_CANCELLED', reason='REVIEW_CANCELLED')
        for row in self.rows.values():
            if row['collection'] == 'STEP_NOT_REACHED':
                row['reason'] = 'STEP_NOT_REACHED_REPLAY_' + self.replay_status.upper()
        self.phase = 'finalizing'
        rows = list(self.rows.values())
        if self.plan.schema_version == 2:
            # Reporting-only rows: never enter replay checkpoints, capture or review tasks.
            for cell in self.plan.applicability:
                matching = [r for r in rows if (r['checkpoint']['check_id'],r['checkpoint']['recording_id'],
                            r['checkpoint']['occurrence']) == (cell.check_id,cell.recording_id,cell.occurrence)]
                if matching: continue
                route = next(r for r in self.plan.routes if (r.recording_id,r.occurrence)==(cell.recording_id,cell.occurrence))
                reason = {'applicable':'PLAN_CHECKPOINT_MISSING','not_applicable':'NOT_APPLICABLE',
                          'unknown':'APPLICABILITY_UNKNOWN'}[cell.status]
                rows.append(dict(row_kind='applicability_gap', applicability=cell.status,
                    applicability_reason=cell.reason,
                    checkpoint=dict(check_id=cell.check_id,recording_id=route.recording_id,
                        route_version=route.version,route_hash=route.content_hash,occurrence=route.occurrence,
                        checkpoint_id=None,step_id=None,phase=None,expected=None),
                    collection=reason,review='NOT_REVIEWED',evidence_ref=None,verdict='inconclusive',
                    reason=reason,enforcement_verified=False))
        checks = {}
        check_ids = (self.plan.selected_check_ids if self.plan.schema_version == 2
                     else {r['checkpoint']['check_id'] for r in rows})
        for check in sorted(check_ids):
            selected = [r for r in rows if r['checkpoint']['check_id']==check]
            expected = {(r['checkpoint']['recording_id'],r['checkpoint']['occurrence']) for r in selected}
            if self.plan.schema_version == 2:
                expected = {(c.recording_id,c.occurrence) for c in self.plan.applicability
                            if c.check_id==check and c.status=='applicable'}
            covered = {pair for pair in expected if all(r['collection']=='SEALED' for r in selected
                       if (r['checkpoint']['recording_id'],r['checkpoint']['occurrence'])==pair)}
            checks[check] = dict(routes_expected=len(expected), routes_with_evidence=len(covered),
                                 verdict='inconclusive', reason='OBSERVATION_ONLY_OR_GAPS')
            if self.plan.schema_version == 2:
                checks[check].update(routes_not_applicable=sum(c.check_id==check and c.status=='not_applicable' for c in self.plan.applicability),
                    routes_unknown=sum(c.check_id==check and c.status=='unknown' for c in self.plan.applicability))
        result = dict(contract='synthetic-observation.v'+str(self.plan.schema_version), run_id=self.run_id, attempt_id=self.attempt_id,
                      review_timing='enqueue-deadline.v1',
                      plan_hash=self.plan.content_hash, replay_status=self.replay_status,
                      rows=rows, checks=checks, real_reviewer='unavailable', finalization='completed')
        if self.plan.schema_version == 2:
            result['applicability'] = [asdict(c) for c in self.plan.applicability]
            result['observation_metadata_hash'] = self.plan.observation_metadata_hash
        try:
            self.event('finalization_ready')
            with (self.root/'result.tmp').open('x', encoding='utf-8') as stream:
                json.dump(result, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(self.root/'result.tmp', self.root/'result.json')
        except OSError:
            self.phase = 'finalizing_failed'
            raise
        self.final = json.loads(json.dumps(result))
        self.phase = 'finalized'
        return json.loads(json.dumps(result))
