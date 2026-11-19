import contextlib, copy, datetime, hashlib, json, os, pathlib, threading, time, uuid
from . import protocol as p
from .adapter import Uncertain

def uid(): return str(uuid.uuid4())
def atomic(path,data):
    tmp=path.with_suffix('.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

class Lease:
    """Cross-process OS lock plus persistent uncertainty quarantine. Never auto-cleared."""
    @staticmethod
    def permission_error(path):
        return RuntimeError('Cannot access device lease: '+str(path)+'. Run all recorder processes under the same Windows user and check that user\'s folder permissions. Do not delete markers or use another lock directory to bypass this error.')
    def __init__(self,device):
        root=pathlib.Path.home()/'.mobile-finsec-poc'
        try: root.mkdir(exist_ok=True)
        except PermissionError as e: raise self.permission_error(root) from e
        self.path=root/(hashlib.sha256(device.encode()).hexdigest()+'.lock'); self.handle=None
        self.quarantine=self.path.with_suffix('.quarantine'); self.active=self.path.with_suffix('.active')
    def acquire(self):
        try:
            if self.quarantine.exists() or self.active.exists(): raise RuntimeError('Device busy or recovery required: confirm Appium stopped before clearing markers: '+str(self.path.parent))
        except PermissionError as e: raise self.permission_error(self.path.parent) from e
        try:
            self.handle=self.path.open('a+b'); self.handle.seek(0)
            if self.path.stat().st_size==0: self.handle.write(b'0'); self.handle.flush(); self.handle.seek(0)
        except OSError as e:
            if self.handle: self.handle.close(); self.handle=None
            if isinstance(e,PermissionError): raise self.permission_error(self.path) from e
            raise
        try:
            if os.name=='nt':
                import msvcrt; msvcrt.locking(self.handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl; fcntl.flock(self.handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.handle.close(); self.handle=None; raise RuntimeError('Device busy in another process')
        try:
            if self.quarantine.exists() or self.active.exists(): self.release(); raise RuntimeError('Device requires recovery')
            atomic(self.active,{'pid':os.getpid(),'device':self.path.stem,'status':'active_or_unclean_exit'})
        except OSError as e:
            self.release() # Preserve any markers; do not leak the OS lock on failed setup.
            if isinstance(e,PermissionError): raise self.permission_error(self.active) from e
            raise
    def poison(self,reason): atomic(self.quarantine,{'reason':reason,'time':datetime.datetime.now(datetime.timezone.utc).isoformat()})
    def release(self,clean=False):
        if self.handle:
            try:
                if clean and not self.quarantine.exists(): self.active.unlink(missing_ok=True)
            finally:
                self.handle.close(); self.handle=None

class Journal:
    def __init__(self,root,kind):
        self.id=uid(); self.path=pathlib.Path(root)/self.id; self.path.mkdir(parents=True)
        (self.path/'evidence').mkdir(); self.start=time.monotonic(); self.kind=kind; self.sequence=0
        self.write('started',kind=kind,status='incomplete')
    def write(self,event,**data):
        self.sequence+=1
        obj={'schema_version':1,'session_id':self.id,'event_id':uid(),'sequence':self.sequence,'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed':time.monotonic()-self.start,'event':event,**data}
        with (self.path/'events.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(obj,ensure_ascii=False,allow_nan=False)+'\n'); f.flush(); os.fsync(f.fileno())

class Engine:
    def __init__(self,adapter,output,allow_coordinates=False,initial_condition=None):
        self.initial_condition=initial_condition; self.fixture=adapter.package==p.PACKAGE
        self.a=adapter; self.output=output; self.allow_coordinates=allow_coordinates; self.mode='idle'
        self.cancel=threading.Event(); self.guard=threading.Lock(); self.steps=[]; self.fallbacks=0; self.j=None
        self.replay_observer=None  # Trusted host boundary only; never an agent/tool callback.
    @contextlib.contextmanager
    def operation(self):
        if not self.guard.acquire(blocking=False): raise RuntimeError('Busy: operation already running')
        try: yield
        finally: self.guard.release()
    def condition(self,c,timeout):
        end=time.monotonic()+timeout
        while True:
            if self.cancel.is_set(): raise InterruptedError('Cancelled')
            self.a.foreground(); matches=self.a.elements(c['id'])
            if len(matches)>1: raise RuntimeError('Ambiguous checkpoint')
            if len(matches)==1 and ('text' not in c or self.a.text(matches[0])==c['text']): return
            if time.monotonic()>=end: raise TimeoutError('Postcondition/initial-state not observed: '+str(c))
            self.cancel.wait(.15)
    def initial(self):
        if not self.fixture:
            p.condition(self.initial_condition,self.a.package)
            self.condition(self.initial_condition,3)
            return 'unknown'
        self.a.foreground(); self.condition({'id':p.PREFIX+'initial_state','text':'reset:0::'},3)
        for name in ['username','password']:
            self.condition({'id':p.PREFIX+name,'text':''},3)
        matches=self.a.elements(p.PREFIX+'secure_state')
        if len(matches)!=1: raise RuntimeError('Secure setting unobservable')
        secure=self.a.text(matches[0])
        if secure not in ['secure:on','secure:off']: raise RuntimeError('Unknown secure mode')
        return secure
    def evidence(self,action_id,phase):
        if not self.fixture:return {'input':'not_probed','hierarchy':'not_saved','screen':'not_saved','refs':{}}
        result={'input':'not_probed','hierarchy':'unavailable','screen':'unavailable','refs':{}}
        for kind,fn,extension in [('hierarchy',self.a.source,'xml'),('screen',self.a.screenshot,'png')]:
            try:
                data=fn()
                if not data: raise RuntimeError('Empty observation')
                rel='evidence/'+action_id+'-'+phase+'.'+extension
                (self.j.path/rel).write_bytes(data.encode() if isinstance(data,str) else data)
                result[kind]='available_uninterpreted' if kind=='screen' else 'available'
                result['refs'][kind]=rel
            except Uncertain: raise
            except Exception as e: result[kind+'_reason']=str(e)
        return result
    def start(self):
        with self.operation():
            if self.mode!='idle': raise RuntimeError('Busy: recording/replay already active')
            self.mode='preparing'; self.cancel.clear(); self.steps=[]; self.fallbacks=0
            self.j=Journal(self.output,'recording')
            try:
                secure=self.initial(); target=self.a.target()
                self.record={'schema_version':1 if self.fixture else 2,'recording_id':self.j.id,'status':'incomplete','device_id':self.a.device,'package_id':self.a.package,'target':target,'initial':{'id':p.PREFIX+'initial_state','text':'reset:0::'} if self.fixture else copy.deepcopy(self.initial_condition),'secure':secure,'network_coverage':'none','actions':self.steps}
                self.j.write('ready',target=target,secure=secure,network_coverage='none'); self.mode='recording'
            except Exception as e:
                self.mode='failed'; self.j.write('failed',reason=str(e)); raise
    def stop_requested(self): self.cancel.set()
    def resolve(self,a):
        if 'locator' in a:
            matches=self.a.elements(a['locator'])
            if len(matches)>1: raise RuntimeError('Ambiguous locator; fallback forbidden')
            if len(matches)==1: return matches[0]
            if 'point' not in a: raise RuntimeError('Locator missing')
        if a['type'] in ['tap','swipe']:
            if not self.allow_coordinates or self.fallbacks>=3: raise RuntimeError('Coordinate fallback disabled or limit reached')
            if self.a.geometry()!=a['geometry']: raise RuntimeError('Geometry/rotation mismatch')
            # A screenshot response alone does not prove visible content. UI must explicitly enable coordinates.
            if not self.a.screenshot(): raise RuntimeError('Coordinate input requires screenshot availability')
            self.fallbacks+=1
        return None
    def execute(self,a,action_id):
        p.action(a,self.a.package)
        if self.cancel.is_set(): raise InterruptedError('Cancelled before dispatch')
        self.a.foreground(); before=self.evidence(action_id,'before')
        target=self.resolve(a)
        if not self.fixture and a['type']=='text':self.a.check_text_target(target)
        self.a.foreground()
        if self.cancel.is_set(): raise InterruptedError('Cancelled before intent')
        self.j.write('intent',action_id=action_id,action=a,before=before) # fsync before any device input
        if self.cancel.is_set(): raise InterruptedError('Cancelled before dispatch')
        if self.mode=='replaying' and self.replay_observer is not None:
            self.replay_observer(action_id,'before_dispatch')
        if self.cancel.is_set(): raise InterruptedError('Cancelled after observation')
        self.j.write('dispatch',action_id=action_id)
        try:
            t=a['type']
            if t=='tap' and target: self.a.click(target)
            elif t=='text': self.a.enter(target,a['text'])
            elif t=='back': self.a.back()
            elif t in ['tap','swipe']:
                g=a['geometry']; xy=lambda pt:[int(pt[0]*g['width']),int(pt[1]*g['height'])]
                self.a.gesture(xy(a['point']),xy(a['end']) if t=='swipe' else None)
            self.condition(a['post'],a['timeout'])
            if self.mode=='replaying' and self.replay_observer is not None:
                self.replay_observer(action_id,'after_postcondition')
            after=self.evidence(action_id,'after'); after['input']='not_applicable' if t=='wait' else 'dispatch_acknowledged_and_postcondition_observed'
            if self.cancel.is_set():raise InterruptedError('Cancelled during final observation')
            self.j.write('result',action_id=action_id,status='succeeded',after=after)
        except Exception as e:
            try: self.j.write('result',action_id=action_id,status='incomplete' if isinstance(e,(Uncertain,InterruptedError,OSError)) else 'failed',reason=str(e))
            except OSError: pass
            raise
    def record_action(self,a):
        with self.operation():
            if self.mode!='recording' or self.cancel.is_set(): raise RuntimeError('Not accepting recording input')
            if len(self.steps)>=100: raise RuntimeError('Maximum 100 steps')
            aid=uid()
            try: self.execute(a,aid); self.steps.append({'action_id':aid,'action':copy.deepcopy(a)})
            except Exception as e:
                self.mode='incomplete'; self.record['status']='incomplete'
                try: self.j.write('gap',reason=str(e)); atomic(self.j.path/'route.json',self.record)
                except OSError: pass
                raise
    def finish(self):
        with self.operation():
            if self.mode=='idle': return
            if self.mode!='recording': raise RuntimeError('Partial recording cannot be completed')
            self.mode='stopping'
            try:
                self.record['status']='completed' if self.steps else 'incomplete'
                if self.steps: p.route(self.record)
                self.j.write('finished',status=self.record['status'])
                atomic(self.j.path/'route.json',self.record); self.mode='idle'
            except Exception: self.mode='incomplete'; raise
    def replay(self,route):
        with self.operation():
            if self.mode!='idle': raise RuntimeError('Busy: manual input disabled during replay')
            p.route(route); self.mode='replaying'; self.cancel.clear(); self.fallbacks=0
            self.j=Journal(self.output,'replay')
            result={'schema_version':1,'run_id':self.j.id,'recording_id':route['recording_id'],'status':'incomplete','steps':[{'action_id':s['action_id'],'status':'not_run'} for s in route['actions']]}
            try:
                if self.a.package!=route['package_id']: raise RuntimeError('Selected package mismatch')
                if not self.fixture:self.initial_condition=copy.deepcopy(route['initial'])
                if self.a.device!=route['device_id']: raise RuntimeError('Explicit recorded device mismatch')
                if self.a.target()!=route['target']: raise RuntimeError('Installed APK build mismatch')
                if self.initial()!=route['secure']: raise RuntimeError('Secure mode differs from recording')
                for i,s in enumerate(route['actions']):
                    result['steps'][i]['status']='incomplete'
                    self.execute(s['action'],s['action_id']); result['steps'][i]['status']='succeeded'
                if self.cancel.is_set():raise InterruptedError('Cancelled before replay finalization')
                result['status']='succeeded'
            except Exception as e:
                result['reason']=str(e); result['status']='incomplete' if isinstance(e,(InterruptedError,Uncertain,OSError)) else 'failed'
                for step in result['steps']:
                    if step['status']=='incomplete': step['status']=result['status']; step['reason']=str(e)
            finally:
                try:
                    self.j.write('finished',status=result['status'],reason=result.get('reason'))
                    atomic(self.j.path/'result.json',result)
                except OSError: self.mode='incomplete'; raise
                self.mode='idle' if result['status']=='succeeded' else 'incomplete'
            return result
