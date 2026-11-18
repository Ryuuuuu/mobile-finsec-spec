"""In-process UI projection for a mock client, not a GPUI or HTTP implementation."""
import hashlib,json,re
from .artifact_reader import bounded,read_artifacts
from .run_journal import list_runs,read_json

class UIBridge:
    def __init__(self,project_id,api):self.project_id=project_id;self.api=api
    def envelope(self,generation,**data):
        return dict(contract='mock-ui.v1',project_id=self.project_id,request_generation=generation,**data)
    def recording(self,ref,generation):
        files=self.api.recordings.get(ref)
        if files is None:return self.envelope(generation,status='missing')
        summary,_=read_artifacts(files['link'],files['route'],files['packets'])
        return self.envelope(generation,status='available',recording=summary)
    def progress(self,execution_id,generation,cursor=0):
        if type(cursor) is not int or cursor<0:raise ValueError('INVALID_CURSOR')
        state=self.api.status(execution_id);rid=state.get('run_id') or self.api.execution_runs.get(execution_id)
        busy=state['status']=='in_progress' or self.api.supervisor.lease.inspect()['lifecycle']!='free'
        device=self.api.inventory.get('devices',{}).get('synthetic-device-p4',{})
        input_ready=device.get('connection')=='connected' and device.get('authorized') is True and device.get('capabilities',{}).get('mock_input') is True
        base=dict(execution=state,run_id=rid,events=[],next_cursor=cursor,resync_required=False,has_more=False,delivery_error=None,
                  controls={'selection_enabled':not busy,'device_input_enabled':not busy and input_ready,'history_enabled':True,'reason':'RUN_ACTIVE_OR_RECOVERY' if busy else None})
        if rid is None:return self.envelope(generation,**base)
        try:
            raw=bounded(self.api.supervisor.root/rid/'live.jsonl',1024*1024)
            lines=raw.splitlines(keepends=True);events=[]
            for line in lines:
                if not line.endswith(b'\n'):break  # writer may be between append and flush
                event=json.loads(line)
                if not isinstance(event,dict) or type(event.get('seq')) is not int or event['seq']!=len(events)+1:raise ValueError('CURSOR_GAP')
                events.append(dict(event,event_id=rid+':'+str(event['seq'])))
            if cursor>len(events):base['resync_required']=True;base['next_cursor']=0
            else:
                page=[];size=0
                for event in events[cursor:]:
                    event_size=len(json.dumps(event,allow_nan=False).encode('utf-8'))
                    if event_size>64*1024:
                        if not page:base['delivery_error']='EVENT_LIMIT'
                        break
                    if len(page)>=64 or size+event_size>64*1024:break
                    page.append(event);size+=event_size
                next_cursor=cursor+len(page)
                base.update(events=page,next_cursor=next_cursor,
                            has_more=next_cursor<len(events) and base['delivery_error'] is None)
        except FileNotFoundError:pass
        except (OSError,ValueError,TypeError):base['resync_required']=True;base['next_cursor']=0
        return self.envelope(generation,**base)
    def history(self,generation,date=None):
        # Result-log tab excludes active, unsealed and corrupt entries.
        rows=[row for row in list_runs(self.api.supervisor.root,date=date) if row['storage_status']=='finalized']
        return self.envelope(generation,status='ok',runs=rows)
    def result(self,run_id,generation):
        if not isinstance(run_id,str) or not re.fullmatch(r'synthetic-[A-Za-z0-9-]{1,100}',run_id):
            return self.envelope(generation,status='invalid_selection')
        path=self.api.supervisor.root/run_id
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(self.api.supervisor.root.resolve()):raise ValueError('SCOPE')
            marker,_=read_json(path/'finalized.json',8192);result,data=read_json(path/'result.json')
            if marker.get('contract')!='structure-history.v1' or result.get('execution_status') not in ('completed','failed','cancelled','timed_out','not_run') or marker.get('run_id')!=run_id or result.get('run_id')!=run_id or marker.get('result_sha256')!=hashlib.sha256(data).hexdigest():
                raise ValueError('INTEGRITY')
            # Live events belong to check tab, never the result tab.
            result.pop('events',None)
            return self.envelope(generation,status='ok',run_id=run_id,result=result)
        except FileNotFoundError:return self.envelope(generation,status='not_finalized',run_id=run_id)
        except (OSError,ValueError,TypeError):return self.envelope(generation,status='corrupt',run_id=run_id)

class MockUIClient:
    def __init__(self,project_id):
        self.project_id=project_id;self.generation=0;self.tab='record';self.events={};self.result=None;self.run_id=None
    def select(self,tab,run_id=None):
        if tab not in ('record','check','results'):raise ValueError('INVALID_TAB')
        if self.generation>=2**53-1:raise ValueError('GENERATION_OVERFLOW')
        self.tab=tab;self.generation+=1;self.events={};self.result=None;self.run_id=run_id
        return self.generation
    def apply(self,response):
        if not isinstance(response,dict) or response.get('contract')!='mock-ui.v1':return False
        if response.get('project_id')!=self.project_id or type(response.get('request_generation')) is not int or response.get('request_generation')!=self.generation:return False
        rid=response.get('run_id')
        if self.run_id is not None and rid!=self.run_id:return False
        if rid is not None:self.run_id=rid
        if self.tab=='check':
            if response.get('resync_required'):self.events={};return False
            for event in response.get('events',[]):self.events[event['event_id']]=event
        elif self.tab=='results' and response.get('status')=='ok':self.result=response.get('result')
        return True
