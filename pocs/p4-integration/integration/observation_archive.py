"""Private completed fixed-fixture reports only; no replay restoration."""
import json, os, re
from datetime import datetime,timezone
from pathlib import Path
from .observation_poc import digest

LIMIT=131072
HEX=re.compile(r'[a-f0-9]{64}')
RUN=re.compile(r'[a-f0-9]{32}')

def publication_time():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

def archive_payload(envelope):
    if set(envelope)!= {'payload','checksum'}:raise ValueError('REPORT_ENVELOPE_INVALID')
    p=envelope['payload'];fields={'contract','run_id','plan_hash','result','matching_report'}
    if p['contract']=='synthetic-completed-report.v2':
        fields.add('saved_at')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z',p['saved_at']):raise ValueError('REPORT_DATE_INVALID')
        datetime.fromisoformat(p['saved_at'].replace('Z','+00:00'))
    elif p['contract']!='synthetic-completed-report.v1':raise ValueError('REPORT_VERSION_INVALID')
    if set(p)!=fields or digest(p)!=envelope['checksum']:raise ValueError('REPORT_CORRUPT')
    return p

def history(root):
    folder=Path(root)/'completed-reports'
    if folder.is_symlink() or folder.is_junction():raise ValueError('REPORT_PATH_INVALID')
    if not folder.exists():return dict(status='ok',history=[])
    items=[]
    with os.scandir(folder) as entries:
        for count,entry in enumerate(entries):
            if count>=100:return dict(status='HISTORY_LIMIT',history=[])
            path=Path(entry.path)
            if path.suffix!='.json' or not RUN.fullmatch(path.stem):continue
            item=dict(run_id=path.stem,plan_hash=None,saved_at=None,available=False,reason='REPORT_UNAVAILABLE')
            try:
                if not entry.is_file(follow_symlinks=False) or path.is_symlink() or path.is_junction():raise ValueError('REPORT_PATH_INVALID')
                with path.open('rb') as f:data=f.read(LIMIT+1)
                if len(data)>LIMIT:raise ValueError('REPORT_LIMIT')
                p=archive_payload(json.loads(data))
                validate(p['result'],p['matching_report'],path.stem,p['plan_hash'])
                if p['run_id']!=path.stem:raise ValueError('REPORT_ASSOCIATION_MISMATCH')
                item.update(plan_hash=p['plan_hash'],saved_at=p.get('saved_at'),available=True,reason='AVAILABLE')
            except (OSError,ValueError,KeyError,TypeError,AttributeError,RecursionError):pass
            items.append(item)
    items.sort(key=lambda i:(i['saved_at'] or '',i['run_id']),reverse=True)
    return dict(status='ok',history=items)

def validate(result, matching, run_id, plan_hash):
    if not RUN.fullmatch(run_id) or not HEX.fullmatch(plan_hash):raise ValueError('REPORT_ID_INVALID')
    if result.get('run_id')!=run_id or result.get('plan_hash')!=plan_hash:raise ValueError('REPORT_ASSOCIATION_MISMATCH')
    if result.get('finalization')!='completed' or result.get('replay_status')!='completed':raise ValueError('REPORT_NOT_COMPLETED')
    version=result.get('contract')
    if version not in ('synthetic-observation.v1','synthetic-observation.v2'):raise ValueError('REPORT_VERSION_INVALID')
    required={'contract','run_id','attempt_id','review_timing','plan_hash','replay_status','rows','checks','real_reviewer','finalization'}
    allowed=required|{'applicability','observation_metadata_hash'}
    if not required<=set(result)<=allowed:raise ValueError('REPORT_FIELDS_INVALID')
    # This is deliberately not a general report importer. Reject text outside bounded fixture tokens.
    def bounded(value,depth=0):
        if depth>12:raise ValueError('REPORT_LIMIT')
        if isinstance(value,dict):
            if len(value)>30:raise ValueError('REPORT_LIMIT')
            for k,v in value.items():bounded(k,depth+1);bounded(v,depth+1)
        elif isinstance(value,(list,tuple)):
            if len(value)>20:raise ValueError('REPORT_LIMIT')
            for v in value:bounded(v,depth+1)
        elif isinstance(value,str):
            if not re.fullmatch(r'[A-Za-z0-9_./-]{0,160}',value):raise ValueError('REPORT_NON_FIXTURE_TEXT')
        elif value is not None and type(value) not in (int,bool):raise ValueError('REPORT_VALUE_INVALID')
    bounded(result);bounded(matching)
    checks=result.get('checks',{});rows=result.get('rows',[])
    expected={'mock-check'} if version.endswith('v1') else {'before-check','after-check'}
    if set(checks)!=expected or len(rows)!=2*len(expected):raise ValueError('REPORT_INCOMPLETE')
    identities=set()
    for row in rows:
        required_row={'checkpoint','collection','review','evidence_ref','verdict','reason','enforcement_verified'}
        if not required_row<=set(row)<=required_row|{'row_kind','applicability','applicability_reason'}:raise ValueError('REPORT_ROW_INVALID')
        c=row['checkpoint'];key=(c['check_id'],c['occurrence'])
        if set(c)!={'checkpoint_id','check_id','recording_id','route_version','route_hash','occurrence','step_id','phase','expected'}:raise ValueError('REPORT_CHECKPOINT_INVALID')
        if key in identities or key[0] not in expected or type(key[1]) is not int or key[1] not in (0,1):raise ValueError('REPORT_ROW_INVALID')
        identities.add(key)
        if c['recording_id']!='route-A' or not re.fullmatch(r'v[1-9][0-9]{0,5}',c['route_version']) or not HEX.fullmatch(c['route_hash']):raise ValueError('REPORT_ROUTE_INVALID')
        if c.get('step_id') not in (None,'tap') or c.get('phase') not in (None,'before_dispatch','after_postcondition'):raise ValueError('REPORT_STEP_INVALID')
        if not row.get('reason') or row.get('verdict')!='inconclusive':raise ValueError('REPORT_ROW_INVALID')
        if row['evidence_ref'] is not None and not re.fullmatch(r'evidence/[a-f0-9]{64}\.json',row['evidence_ref']):raise ValueError('REPORT_EVIDENCE_REFERENCE_INVALID')
        if (row['collection']=='SEALED') != (row['evidence_ref'] is not None):raise ValueError('REPORT_EVIDENCE_REFERENCE_INVALID')
    for check,c in checks.items():
        fields={'routes_expected','routes_with_evidence','verdict','reason'}
        if not fields<=set(c)<=fields|{'routes_unknown','routes_not_applicable'} or c['verdict']!='inconclusive' or c['reason']!='OBSERVATION_ONLY_OR_GAPS':raise ValueError('REPORT_CHECK_INVALID')
        selected=[r for r in rows if r['checkpoint']['check_id']==check]
        if c.get('routes_expected')!=2 or c.get('routes_with_evidence')!=sum(r.get('collection')=='SEALED' for r in selected):raise ValueError('REPORT_COVERAGE_INVALID')
    if matching is not None:
        if version.endswith('v1') or digest(matching)!=result.get('observation_metadata_hash'):raise ValueError('REPORT_TIMING_MISMATCH')
        if set(matching)!={'contract','metadata_hash','rules','rows'} or matching.get('contract')!='synthetic-timing-match.v1' or len(matching.get('rows',[]))!=4 or len(matching['rules'])!=2:raise ValueError('REPORT_TIMING_INCOMPLETE')
        seen=set()
        for m in matching['rows']:
            key=(m['check_id'],m['occurrence'])
            if key in seen or key not in identities:raise ValueError('REPORT_TIMING_INCOMPLETE')
            seen.add(key)
            c=next(r['checkpoint'] for r in rows if (r['checkpoint']['check_id'],r['checkpoint']['occurrence'])==key)
            if any(m[k]!=c[k] for k in ('recording_id','route_version','route_hash')):raise ValueError('REPORT_TIMING_MISMATCH')
            if m['status'] not in ('MATCHED','UNMATCHED','AMBIGUOUS'):raise ValueError('REPORT_TIMING_INVALID')
            count=m['candidate_count']
            if type(count) is not int or not 0<=count<=200 or (m['status']=='MATCHED' and count!=1) or (m['status']=='UNMATCHED' and count!=0) or (m['status']=='AMBIGUOUS' and count<2):raise ValueError('REPORT_TIMING_INVALID')
    return dict(status='ok',result=result,matching_report=matching,
                historical_detail='AVAILABLE' if matching is not None else 'HISTORICAL_TIMING_UNAVAILABLE')

def save_completed(root,result,matching):
    run,plan=result['run_id'],result['plan_hash']
    validate(result,matching,run,plan)
    payload=dict(contract='synthetic-completed-report.v2',saved_at=publication_time(),run_id=run,plan_hash=plan,result=result,matching_report=matching)
    data=json.dumps(dict(payload=payload,checksum=digest(payload)),sort_keys=True).encode()
    if len(data)>LIMIT:raise ValueError('REPORT_LIMIT')
    folder=Path(root)/'completed-reports';folder.mkdir(exist_ok=True)
    target=folder/(run+'.json');temporary=folder/(run+'.tmp')
    if target.exists():raise ValueError('REPORT_ALREADY_PUBLISHED')
    created=False
    try:
        with temporary.open('xb') as f:
            created=True
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(temporary,target)
    finally:
        if created and temporary.exists():temporary.unlink()

def load_completed(root,run_id,plan_hash):
    if not isinstance(run_id,str) or not RUN.fullmatch(run_id) or not isinstance(plan_hash,str) or not HEX.fullmatch(plan_hash):raise ValueError('REPORT_ID_INVALID')
    path=Path(root)/'completed-reports'/(run_id+'.json')
    legacy=not path.exists()
    if legacy:path=Path(root)/run_id/'result.json'
    if path.is_symlink() or path.parent.is_symlink() or path.parent.is_junction():raise ValueError('REPORT_PATH_INVALID')
    with path.open('rb') as f:data=f.read(LIMIT+1)
    if len(data)>LIMIT:raise ValueError('REPORT_LIMIT')
    envelope=json.loads(data)
    if legacy:return validate(envelope,None,run_id,plan_hash)
    p=archive_payload(envelope)
    if p['run_id']!=run_id or p['plan_hash']!=plan_hash:raise ValueError('REPORT_ASSOCIATION_MISMATCH')
    return dict(validate(p['result'],p['matching_report'],run_id,plan_hash),saved_at=p.get('saved_at'))
