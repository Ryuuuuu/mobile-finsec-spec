"""Structural live log and sealed result history; no assessment implementation."""
from datetime import datetime,timezone
import hashlib,json,os
from pathlib import Path


def utc():return datetime.now(timezone.utc).isoformat()
def write_new(path,value):
    data=json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')
    with Path(path).open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    return data


class RunJournal:
    def __init__(self,output,run_id):
        self.output=Path(output);self.run_id=run_id;self.started_at=utc()
        write_new(self.output/'run-meta.json',dict(contract='structure-history.v1',run_id=run_id,started_at=self.started_at))
    def event(self,event):
        with (self.output/'live.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(event,timestamp=utc()),allow_nan=False)+'\n');stream.flush()
    def finalize(self,result):
        result.update(started_at=self.started_at,finished_at=utc())
        result['completion']=dict(completed=sum(r['execution_status']=='completed' for r in result['items']),
                                  selected=len(result['items']))
        temporary=self.output/'result.json.tmp'
        data=write_new(temporary,result);temporary.replace(self.output/'result.json')
        # Marker last: a result file alone never proves finalization succeeded.
        write_new(self.output/'finalized.json',dict(contract='structure-history.v1',run_id=self.run_id,
                   result_sha256=hashlib.sha256(data).hexdigest()))


def read_json(path,limit=2*1024*1024):
    path=Path(path)
    if path.is_symlink():raise ValueError('SYMLINK')
    with path.open('rb') as stream:data=stream.read(limit+1)
    if len(data)>limit:raise ValueError('LIMIT')
    return json.loads(data),data


def list_runs(root,date=None,limit=100):
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('INVALID_LIMIT')
    if date is not None:datetime.strptime(date,'%Y-%m-%d')
    rows=[];paths=list(Path(root).glob('synthetic-*'))
    if len(paths)>1000:raise ValueError('HISTORY_SCAN_LIMIT')
    for path in paths:
        if path.is_symlink() or not path.is_dir():continue
        row=dict(run_id=path.name,storage_status='unfinalized',execution_status=None,started_at=None,finished_at=None)
        try:
            meta,_=read_json(path/'run-meta.json',8192)
            if meta['contract']!='structure-history.v1' or meta['run_id']!=path.name:raise ValueError('META')
            row['started_at']=meta['started_at'];datetime.fromisoformat(meta['started_at'])
            if (path/'finalized.json').exists():
                marker,_=read_json(path/'finalized.json',8192);result,data=read_json(path/'result.json')
                if (marker.get('contract')!='structure-history.v1' or marker.get('run_id')!=path.name
                    or marker.get('result_sha256')!=hashlib.sha256(data).hexdigest()
                    or result.get('run_id')!=path.name or result.get('started_at')!=row['started_at']
                    or result.get('execution_status') not in ('completed','failed','cancelled','timed_out','not_run')):
                    raise ValueError('RESULT')
                row.update(storage_status='finalized',execution_status=result['execution_status'],
                           finished_at=result['finished_at'],completion=result['completion'],
                           recovery_required=result['recovery_required'])
        except (OSError,ValueError,KeyError,TypeError,AttributeError):row['storage_status']='corrupt'
        if date is None or row['started_at'] and row['started_at'].startswith(date+'T'):rows.append(row)
    rows.sort(key=lambda r:(r['started_at'] or '',r['run_id']),reverse=True)
    return rows[:limit]
