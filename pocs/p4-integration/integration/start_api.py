"""Model-independent in-process start API using authoritative MOCK inventory only."""
import asyncio
from copy import deepcopy
import hashlib,json,re
from uuid import uuid4


def validate_request(request):
    if (not isinstance(request,dict) or set(request)!={'contract','command_id','device_id','platform','items','inventory_revision'}
            or request['contract']!='structural-start.v1' or request['platform'] not in ('aos','ios')
            or not isinstance(request['items'],list) or not 1<=len(request['items'])<=10
            or not all(isinstance(i,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',i) for i in request['items'])
            or len(set(request['items']))!=len(request['items'])
            or not isinstance(request['command_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',request['command_id'])
            or not isinstance(request['device_id'],str) or len(request['device_id'])>100
            or type(request['inventory_revision']) is not int or request['inventory_revision']<0):
        raise ValueError('INVALID_START_REQUEST')


def preflight(request,inventory,catalog,lease_state='free'):
    validate_request(request)
    reasons=[];rows=[]
    if request['inventory_revision']!=inventory.get('revision'):reasons.append('STALE_SELECTION')
    device=inventory.get('devices',{}).get(request['device_id'])
    if device is None:reasons.append('DEVICE_MISSING')
    else:
        if request['device_id']!='synthetic-device-p4':reasons.append('DEVICE_EXECUTOR_UNSUPPORTED')
        if device.get('platform')!=request['platform']:reasons.append('PLATFORM_MISMATCH')
        if device.get('connection')!='connected':reasons.append('DEVICE_UNAVAILABLE')
        if device.get('authorized') is not True:reasons.append('DEVICE_NOT_AUTHORIZED')
    if lease_state!='free':reasons.append('DEVICE_BUSY_OR_RECOVERY')
    for item in request['items']:
        spec=catalog.get(item);missing=[]
        if spec is None:missing=['ITEM_UNKNOWN']
        else:
            if request['platform'] not in spec.get('platforms',[]):missing.append('ITEM_PLATFORM_UNSUPPORTED')
            if spec.get('common_skill') is not True:missing.append('COMMON_SKILL_MISSING')
            if request['platform'] not in spec.get('platform_skills',[]):missing.append('PLATFORM_SKILL_MISSING')
            for cap in spec.get('requires',[]):
                if not device or device.get('capabilities',{}).get(cap) is not True:missing.append('CAPABILITY_MISSING:'+cap)
        rows.append(dict(item_id=item,enabled=not reasons and not missing,reasons=list(reasons)+missing))
    return dict(contract='structural-preflight.v1',synthetic=True,enabled=not reasons and all(r['enabled'] for r in rows),
                reasons=reasons,items=rows,inventory_revision=inventory.get('revision'))


class StartAPI:
    def __init__(self,supervisor,inventory,catalog):
        self.supervisor=supervisor;self.inventory=deepcopy(inventory);self.catalog=deepcopy(catalog)
        self.commands={};self.jobs={}
    def inspect(self,request):
        return preflight(request,self.inventory,self.catalog,self.supervisor.lease.inspect()['lifecycle'])
    def submit(self,request):
        validate_request(request)
        digest=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        key=request['command_id']
        if key in self.commands:
            old,jid=self.commands[key]
            if old!=digest:return dict(status='conflict',reason='COMMAND_PAYLOAD_CHANGED')
            return dict(status='duplicate',execution_id=jid)
        checked=self.inspect(request)
        if not checked['enabled']:return dict(status='not_run',preflight=checked)
        if len(self.jobs)>=100:return dict(status='not_run',reason='COMMAND_CACHE_LIMIT')
        request=deepcopy(request);jid='synthetic-api-'+uuid4().hex
        def available():
            # Recheck authoritative mock selection after lease and while running.
            return preflight(request,self.inventory,self.catalog)['enabled']
        task=asyncio.create_task(self.supervisor.run(request['items'],request['platform'],availability=available))
        self.jobs[jid]=task;self.commands[key]=(digest,jid)
        return dict(status='accepted',execution_id=jid)
    async def wait(self,execution_id):return deepcopy(await asyncio.shield(self.jobs[execution_id]))
    def status(self,execution_id):
        task=self.jobs.get(execution_id)
        if task is None:return dict(status='not_found')
        if not task.done():return dict(status='in_progress',execution_id=execution_id)
        if task.cancelled() or task.exception() is not None:return dict(status='error',execution_id=execution_id,reason='EXECUTION_OR_STORAGE_ERROR')
        result=task.result()
        return dict(status='finished',execution_id=execution_id,run_id=result['run_id'],execution_status=result['execution_status'])
