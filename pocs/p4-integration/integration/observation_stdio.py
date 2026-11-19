"""Fixed synthetic GPUI preview/approval exerciser; inherited pipes only."""
import argparse,asyncio,json,sys
from dataclasses import asdict
from pathlib import Path
from .observation_poc import Route,Checkpoint,Plan,Scene,FakeReview,ObservationPOC,SyntheticDeviceSlot

LIMIT=262144


class ObservationAPI:
    def __init__(self,root):
        self.root=Path(root);self.revision=1;self.approved=None;self.owner=None;self.task=None
        self.slot=SyntheticDeviceSlot();self.error=None
        self.make_plan()

    def make_plan(self):
        routes=tuple(Route('route-A','v'+str(self.revision),occurrence,('tap',)) for occurrence in (0,1))
        cps=tuple(Checkpoint('state','mock-check',r.recording_id,r.version,r.content_hash,r.occurrence,'tap','after_postcondition','QA_SENT') for r in routes)
        self.plan=Plan(routes,cps,review_timeout=8)

    def operation(self,op,args):
        if op=='preview':
            return dict(status='ok',revision=self.revision,plan_hash=self.plan.content_hash,
                        checkpoints=[asdict(c) for c in self.plan.checkpoints],
                        scenario='Same route executions 1/2 complete' if self.revision%2 else 'Only execution 1 has evidence; execution 2 missing (synthetic)',
                        capture_timeout=self.plan.capture_timeout,review_timeout=self.plan.review_timeout,
                        approved=self.approved==self.plan.content_hash)
        if op=='new_version':
            if self.task and not self.task.done():return dict(status='busy')
            self.revision+=1;self.approved=None;self.make_plan()
            return self.operation('preview',{})
        if op=='approve':
            if args.get('plan_hash')!=self.plan.content_hash:return dict(status='PLAN_VERSION_MISMATCH')
            self.approved=self.plan.content_hash
            return dict(status='approved',plan_hash=self.approved)
        if op=='start':
            if self.task and not self.task.done():return dict(status='busy')
            if args.get('plan_hash')!=self.plan.content_hash:return dict(status='PLAN_VERSION_MISMATCH')
            if self.approved!=self.plan.content_hash:return dict(status='PLAN_NOT_APPROVED')
            self.owner=ObservationPOC(self.root,self.plan,self.approved,self.slot,FakeReview(delay=9))
            scenes={('route-A',0,'tap'):Scene(),('route-A',1,'tap'):Scene(missing=not self.revision%2)}
            self.error=None
            async def execute():
                try:await self.owner.run(scenes)
                except Exception:self.error='EXECUTION_OR_STORAGE_ERROR'
            self.task=asyncio.create_task(execute())
            return dict(status='accepted',run_id=self.owner.run_id)
        if op=='status':
            if not self.owner:return dict(status='idle')
            return dict(status=self.error or self.owner.phase,replay=self.owner.replay_status,
                        rows=list(self.owner.rows.values()),final_available=self.owner.final is not None)
        if op=='result':
            if not self.owner or self.owner.final is None:return dict(status='not_finalized')
            return dict(status='ok',result=self.owner.final)
        if op=='cancel':
            if self.owner:self.owner.cancel.set()
            return dict(status='cancel_requested')
        return dict(status='UNKNOWN_OPERATION')

    async def close(self):
        if self.owner:self.owner.cancel.set()
        if self.task:await self.task


async def serve(root):
    api=ObservationAPI(root)
    print(json.dumps(dict(contract='observation-stdio.v1',status='ready',synthetic=True)),flush=True)
    try:
        while True:
            raw=await asyncio.to_thread(sys.stdin.buffer.readline,LIMIT+1)
            if not raw:break
            if len(raw)>LIMIT or not raw.endswith(b'\n'):break
            try:
                request=json.loads(raw)
                if request.get('contract')!='observation-request.v1' or request.get('project_id')!='synthetic-observation':raise ValueError()
                if type(request.get('request_generation')) is not int:raise ValueError()
                args=request.get('arguments',{})
                if not isinstance(args,dict):raise ValueError()
                data=api.operation(request.get('operation'),args)
                reply=dict(contract='observation-ui.v1',project_id='synthetic-observation',request_generation=request['request_generation'],**data)
            except Exception:break
            print(json.dumps(reply),flush=True)
    finally:await api.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True,type=Path)
    asyncio.run(serve(parser.parse_args().root))
