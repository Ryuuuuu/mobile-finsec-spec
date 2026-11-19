"""Fixed synthetic GPUI preview/approval exerciser; inherited pipes only."""
import argparse,asyncio,json,sys
from dataclasses import asdict
from pathlib import Path
from .observation_poc import Route,Checkpoint,Plan,Scene,FakeReview,ObservationPOC,SyntheticDeviceSlot,Applicability,digest
from .observation_matching import TimingRule,QAEvent,match_timing
from .observation_archive import save_completed,load_completed

LIMIT=262144


class ObservationAPI:
    def __init__(self,root,mode='v1'):
        if mode not in ('v1','v2'):raise ValueError('UNSUPPORTED_SYNTHETIC_MODE')
        self.mode=mode;self.matching=None;self.run_matching=None
        self.root=Path(root);self.revision=1;self.approved=None;self.owner=None;self.task=None
        self.slot=SyntheticDeviceSlot();self.error=None;self.archive_status='not_saved'
        self.make_plan()

    def make_plan(self):
        routes=tuple(Route('route-A','v'+str(self.revision),occurrence,('tap',)) for occurrence in (0,1))
        if self.mode=='v2':
            rules=(TimingRule('before-check','state','QA_READY','before_dispatch'),
                   TimingRule('after-check','event','QA_SUBMIT','after_postcondition'))
            cells=tuple(Applicability(rule.check_id,r.recording_id,r.occurrence,'applicable','QA_REQUIRED') for rule in rules for r in routes)
            def event(r,name,phase,state,label):
                return QAEvent(name,r.recording_id,r.version,r.content_hash,r.occurrence,'tap',phase,state,label)
            events=(event(routes[0],'ready','before_dispatch','QA_READY','QA_ENTER'),
                    event(routes[0],'sent-a','after_postcondition','QA_SENT','QA_SUBMIT'),
                    event(routes[0],'sent-b','after_postcondition','QA_SENT','QA_SUBMIT'),
                    event(routes[1],'sent','after_postcondition','QA_SENT','QA_SUBMIT'))
            self.matching=match_timing(routes,cells,rules,events)
            cps=tuple(Checkpoint('state',r['check_id'],r['recording_id'],r['route_version'],r['route_hash'],
                      r['occurrence'],r['step_id'],r['phase'],r['matched_state']) for r in self.matching['rows'] if r['status']=='MATCHED')
            self.plan=Plan(routes,cps,review_timeout=8,schema_version=2,
                           selected_check_ids=tuple(r.check_id for r in rules),applicability=cells,
                           observation_metadata_hash=digest(self.matching))
            return
        cps=tuple(Checkpoint('state','mock-check',r.recording_id,r.version,r.content_hash,r.occurrence,'tap','after_postcondition','QA_SENT') for r in routes)
        self.plan=Plan(routes,cps,review_timeout=8)

    def operation(self,op,args):
        if op=='load_completed':
            try:return load_completed(self.root,args.get('run_id'),args.get('plan_hash'))
            except (OSError,ValueError,KeyError,TypeError,AttributeError,RecursionError):return dict(status='COMPLETED_REPORT_UNAVAILABLE_OR_INVALID')
        if op=='preview':
            return dict(status='ok',revision=self.revision,plan_hash=self.plan.content_hash,
                        checkpoints=[asdict(c) for c in self.plan.checkpoints],
                        scenario=('v2 before-check 1/2; after-check 0/2 (synthetic)' if self.mode=='v2' else
                                  'Same route executions 1/2 complete' if self.revision%2 else 'Only execution 1 has evidence; execution 2 missing (synthetic)'),
                        plan_schema_version=self.plan.schema_version,matching_report=self.matching,
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
            self.run_matching=json.loads(json.dumps(self.matching))
            scenes={('route-A',0,'tap'):Scene(),('route-A',1,'tap'):Scene(missing=self.mode=='v2' or not self.revision%2)}
            self.error=None
            self.archive_status='not_saved'
            async def execute():
                try:
                    await self.owner.run(scenes)
                    if self.owner.final['replay_status']=='completed':
                        try:
                            save_completed(self.root,self.owner.final,self.run_matching)
                            self.archive_status='saved'
                        except (OSError,ValueError,KeyError,TypeError):self.archive_status='REPORT_ARCHIVE_FAILED'
                except Exception:self.error='EXECUTION_OR_STORAGE_ERROR'
            self.task=asyncio.create_task(execute())
            return dict(status='accepted',run_id=self.owner.run_id)
        if op=='status':
            if not self.owner:return dict(status='idle')
            return dict(status=self.error or self.owner.phase,replay=self.owner.replay_status,
                        rows=list(self.owner.rows.values()),final_available=self.owner.final is not None)
        if op=='result':
            if not self.owner or self.owner.final is None:return dict(status='not_finalized')
            return dict(status='ok',result=self.owner.final,matching_report=self.run_matching,archive_status=self.archive_status)
        if op=='cancel':
            if self.owner:self.owner.cancel.set()
            return dict(status='cancel_requested')
        return dict(status='UNKNOWN_OPERATION')

    async def close(self):
        if self.owner:self.owner.cancel.set()
        if self.task:await self.task


async def serve(root,mode='v1'):
    api=ObservationAPI(root,mode)
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
    parser.add_argument('--plan-mode',choices=('v1','v2'),default='v1')
    args=parser.parse_args();asyncio.run(serve(args.root,args.plan_mode))
