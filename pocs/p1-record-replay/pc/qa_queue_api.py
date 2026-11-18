"""Private-pipe QA queue API. No general apps, model or inspection skills."""
import copy
import datetime
import hashlib
import json
import pathlib
import re
import threading
import uuid
from .core import atomic
from . import protocol

class QueueAPI:
    def __init__(self, config, backend):
        self.root = pathlib.Path(config['output']); self.root.mkdir(parents=True, exist_ok=True)
        self.backend = backend; self.config = config; self.lock = threading.RLock()
        self.jobs = {}; self.commands = {}; self.thread = None; self.current = None
        self.catalog = {}
        for entry in config['routes']:
            ref = entry['ref']
            if not re.fullmatch(r'[a-z0-9-]{1,60}', ref) or ref in self.catalog: raise ValueError('Invalid route reference')
            path = pathlib.Path(entry['path'])
            if path.stat().st_size > 1024*1024: raise ValueError('Route size limit')
            route = protocol.load(path)
            if route['package_id'] != 'dev.finsec.qa.network': raise ValueError('Disposable network QA only')
            self.catalog[ref] = dict(entry, route=route)
        # A previous admission is never auto-resubmitted after restart.
        for path in self.root.glob('api-*/admission.json'):
            admission = json.loads(path.read_text(encoding='utf-8'))
            self.commands[admission['command_id']] = (admission['digest'], path.parent.name)
            final=path.parent/'native-result.json'
            if not final.exists() or json.loads(final.read_text(encoding='utf-8')).get('cleanup_verified') is not True:self.current='recovery_required'

    def emit(self, job, kind):
        with self.lock:
            job['events'].append(dict(seq=len(job['events'])+1, type=kind))

    def operation(self, op, args):
        with self.lock:
            if op == 'recordings':
                return dict(status='ok', recordings=[dict(ref=ref, selectable=True,
                    display_name=e['name'], recorded_at=e['recorded_at'],
                    recording=dict(recording_id=e['route']['recording_id'], route_status='complete', packet_status='source_not_loaded'))
                    for ref,e in self.catalog.items()])
            if op == 'submit':
                request = args['request']; command = request['command_id']; refs = request['recording_refs']
                if not re.fullmatch(r'[A-Za-z0-9-]{1,100}', command) or not isinstance(refs,list) or not 1<=len(refs)<=100 or any(r not in self.catalog for r in refs): raise ValueError('Invalid selection')
                digest = hashlib.sha256(json.dumps(refs).encode()).hexdigest()
                if command in self.commands:
                    old, key = self.commands[command]
                    return dict(data=dict(status='conflict' if old!=digest else 'duplicate' if key in self.jobs else 'recovery_required', execution_id=key))
                if self.current is not None: return dict(data=dict(status='busy'))
                key = 'api-'+uuid.uuid4().hex; folder=self.root/key; folder.mkdir()
                atomic(folder/'admission.json', dict(command_id=command,digest=digest,recording_refs=refs))
                job=dict(id=key,status='in_progress',events=[],cancel=threading.Event(),result=None)
                self.jobs[key]=job; self.commands[command]=(digest,key); self.current=key
                routes=[copy.deepcopy(self.catalog[r]['route']) for r in refs]
                self.thread=threading.Thread(target=self.work,args=(job,routes,folder),daemon=False);self.thread.start()
                return dict(data=dict(status='accepted',execution_id=key))
            if op in ('progress','cancel'):
                job=self.jobs[args['execution_id']]
                if op=='cancel': job['cancel'].set();return dict(data=dict(status='requested'))
                cursor=args.get('cursor',0)
                if type(cursor)!=int or not 0<=cursor<=len(job['events']): raise ValueError('Invalid cursor')
                events=job['events'][cursor:cursor+64]
                return dict(execution=dict(status=job['status'],execution_status=job.get('execution_status'),cleanup_verified=(job['result'] or {}).get('cleanup_verified')),
                    run_id=job['id'],events=events,next_cursor=cursor+len(events),has_more=cursor+len(events)<len(job['events']),resync_required=False,delivery_error=None)
            if op=='history':
                rows=[]
                for path in self.root.glob('api-*/native-result.json'):
                    r=json.loads(path.read_text(encoding='utf-8'));rows.append(dict(run_id=path.parent.name,started_at=r['started_at'],execution_status=r['execution_status']))
                return dict(status='ok',runs=sorted(rows,key=lambda r:r['started_at'],reverse=True))
            if op=='result':
                key=args['run_id']
                if not re.fullmatch(r'api-[a-f0-9]{32}',key):raise ValueError('Invalid result reference')
                path=self.root/key/'native-result.json'
                return dict(status='ok',result=json.loads(path.read_text(encoding='utf-8'))) if path.exists() else dict(status='missing')
            raise ValueError('Unsupported operation')

    def work(self, job, routes, folder):
        started=datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            self.emit(job,'qa_preparing')
            result=self.backend(self.config,routes,job['cancel'],lambda kind:self.emit(job,kind))
            result['started_at']=started
            atomic(folder/'native-result.json',result)
            self.emit(job,'qa_finalized_after_cleanup_attempt')
            with self.lock:
                job.update(status='finished',execution_status=result['execution_status'],result=result)
                # Unconfirmed cleanup blocks new work, even if a result was saved.
                if result.get('cleanup_verified') is True:self.current=None
        except Exception as error:
            with self.lock:job.update(status='failed',execution_status='interrupted')
            self.emit(job,'qa_unresolved_'+type(error).__name__)
            # Retain admission/current ownership, no automatic retry.

    def close(self):
        with self.lock:
            if self.current in self.jobs:self.jobs[self.current]['cancel'].set()
        if self.thread is not None:self.thread.join()

def serve(api, input_stream, output_stream):
    def send(value):
        output_stream.write(json.dumps(value,allow_nan=False)+'\n');output_stream.flush()
    send(dict(contract='qa-device-stdio.v1',status='ready',real_device=True))
    try:
        while True:
            line=input_stream.readline(65537)
            if not line:break
            if len(line)>65536 or not line.endswith('\n'):raise ValueError('Frame limit')
            request=json.loads(line)
            if request['contract']!='qa-device-request.v1' or request['project_id']!='qa-device-queue' or type(request['request_generation']) is not int:raise ValueError('Scope/version mismatch')
            response=dict(contract='qa-device-ui.v1',project_id='qa-device-queue',request_generation=request['request_generation'])
            try:response.update(api.operation(request['operation'],request['arguments']))
            except (ValueError,KeyError,TypeError):response.update(status='invalid_request')
            send(response)
    finally:api.close()
