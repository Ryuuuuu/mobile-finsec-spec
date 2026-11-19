"""Trusted P1 host -> fixed synthetic observation reviewer bridge.

No device discovery, model, raw image/packet reader or agent tools. The state
reader is host-owned QA instrumentation, not supplied reviewer code. Its actual
device implementation is deliberately not provided by this POC.
"""
import asyncio
import copy
from .observation_poc import Route, Scene, digest


def bound_route(route, occurrence):
    return Route(route['recording_id'],str(route['schema_version']),occurrence,
                 tuple(s['action_id'] for s in route['actions']),digest(route))


class P1ObservationBridge:
    def __init__(self, owner, queue, state_reader):
        self.owner, self.queue, self.state_reader = owner, queue, state_reader
        self.result = None

    def cancel(self):
        self.owner.cancel.set()
        self.queue.cancel()

    async def run(self, routes):
        owner, queue = self.owner, self.queue
        routes = copy.deepcopy(routes)
        if tuple(bound_route(r,i) for i,r in enumerate(routes)) != owner.plan.routes:
            raise ValueError('P1_SOURCE_VERSION_MISMATCH')
        if owner.started or owner.slot.busy or queue.running:
            raise RuntimeError('BUSY_OR_ALREADY_STARTED')
        engine=queue.combined.engine
        if engine.replay_observer is not None:
            raise RuntimeError('OBSERVER_ALREADY_OWNED')
        loop=asyncio.get_running_loop(); current=[None]
        original_prepare=queue.prepare
        owner.started, owner.slot.busy = True, True
        owner.replay_status, owner.phase = 'running','replaying'

        def prepare(index,route):
            if original_prepare is not None:original_prepare(index,route)
            current[0]=index

        def observe(step_id,phase):
            index=current[0]
            cps=[c for c in owner.plan.checkpoints if c.occurrence==index
                 and c.recording_id==routes[index]['recording_id']
                 and c.step_id==step_id and c.phase==phase]
            if not cps:return
            # Freeze the allowlisted QA state on the replay thread at this boundary.
            # Reader must be cooperative/bounded; arbitrary blocking readers are unsupported.
            try:state=self.state_reader(engine.a)
            except Exception:
                async def acquisition_failed():
                    for cp in cps:
                        key=owner.key(cp)
                        owner.event('checkpoint_reached',key=key,phase=phase)
                        owner.rows[key].update(collection='EVIDENCE_INSUFFICIENT',
                                               reason='HOST_ACQUISITION_ERROR')
                        owner.event('evidence_gap',key=key,reason='HOST_ACQUISITION_ERROR')
                asyncio.run_coroutine_threadsafe(acquisition_failed(),loop).result(timeout=.5)
                raise
            scene=Scene(before=state,after=state)
            for cp in cps:
                future=asyncio.run_coroutine_threadsafe(owner.capture(cp,scene),loop)
                try:future.result(timeout=owner.plan.capture_timeout+0.5)
                except BaseException:
                    future.cancel()
                    raise  # Fail closed; no next input after uncertain host acquisition.
            if owner.cancel.is_set():queue.cancel()

        queue.prepare=prepare; engine.replay_observer=observe
        try:
            owner.event('p1_plan_validated', plan_hash=owner.plan.content_hash)
            # Reviews run on the loop while the existing P1 queue owns input order.
            worker=asyncio.create_task(asyncio.to_thread(queue.run,routes))
            try:self.result=await asyncio.shield(worker)
            except asyncio.CancelledError:
                self.cancel()
                await worker  # Do not release ownership while P1 still has input work.
                raise
            owner.replay_status={'succeeded':'completed','cancelled':'cancelled'}.get(self.result['status'],'failed')
            owner.event('p1_replay_finished',status=owner.replay_status,
                        queue_id=self.result['queue_id'],entries=self.result['entries'])
        except BaseException:
            owner.phase='finalizing_failed'
            for task in owner.tasks:task.cancel()
            await asyncio.gather(*owner.tasks,return_exceptions=True)
            raise
        finally:
            queue.prepare=original_prepare;engine.replay_observer=None
            owner.slot.busy=False
        return await owner.finalize_reviews()
