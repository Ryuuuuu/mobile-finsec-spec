"""Read-only Android observations, never a CHK-07 security verdict."""
import argparse,datetime,hashlib,json,pathlib,subprocess,sys,time,uuid

PROPERTIES=('ro.build.version.sdk','ro.build.version.release','ro.build.version.security_patch',
    'ro.build.type','ro.build.tags','ro.debuggable','ro.secure','ro.boot.verifiedbootstate',
    'ro.boot.flash.locked','ro.boot.vbmeta.device_state')
COMMANDS=(('transport',('get-state',)),)+tuple((p,('shell','getprop',p)) for p in PROPERTIES)+(('shell_identity',('shell','id')),('selinux',('shell','getenforce')))

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def invoke(adb,device,command):
    if tuple(command) not in {c for _,c in COMMANDS}:raise ValueError('Command outside read-only allowlist')
    result=subprocess.run([adb,'-s',device,*command],capture_output=True,timeout=5,check=False)
    if result.returncode:raise OSError('adb command failed')
    if len(result.stdout)>4096:raise ValueError('output limit')
    return result.stdout.decode('utf-8',errors='strict').strip()

def shared_lease(device):
    sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'p1-record-replay'))
    from pc.core import Lease
    return Lease(device)

def collect(adb,device,output,runner=invoke,lease_factory=shared_lease):
    output=pathlib.Path(output);output.mkdir(parents=True,exist_ok=False)
    report={'contract':'android.readonly.v1','synthetic':False,'run_id':str(uuid.uuid4()),
        'started_utc':utc(),'execution_status':'not_run','verdict':'inconclusive',
        'reason_codes':['no_trusted_stock_and_tampered_attestation','no_protected_service_oracle','no_causal_block_reason'],
        'observations':[],'cleanup':{'device_changes':'none','lease':'not_acquired'},
        'limitations':['Self-reported properties may be spoofed; they are not attestation.',
            'ADB shell identity is not application identity.','No app was launched or evaluated.']}
    lease=None;acquired=False;started=time.monotonic()
    try:
        lease=lease_factory(device);lease.acquire();acquired=True
        report['cleanup']['lease']='held'
        for key,command in COMMANDS:
            if time.monotonic()-started>=60:report['execution_status']='timed_out';break
            before=time.monotonic();entry={'name':key,'source':'adb_readonly','command':list(command),'timestamp_utc':utc()}
            try:
                value=runner(adb,device,command)
                if not isinstance(value,str) or len(value.encode('utf-8'))>4096:raise ValueError('output limit')
                entry.update(status='observed' if value else 'unknown',value=value,sha256=hashlib.sha256(value.encode('utf-8')).hexdigest())
                if key=='transport' and value!='device':
                    entry['status']='unavailable';report['execution_status']='not_run'
            except subprocess.TimeoutExpired:entry['status']='timed_out';report['execution_status']='timed_out'
            except (OSError,ValueError):entry['status']='tool_error';report['execution_status']='not_run' if key=='transport' else 'failed'
            entry['duration_ms']=round((time.monotonic()-before)*1000,3);report['observations'].append(entry)
            if entry['status'] in ('unavailable','timed_out','tool_error'):break
        else:report['execution_status']='completed'
    except KeyboardInterrupt:report['execution_status']='cancelled'
    except (OSError,RuntimeError):
        report['execution_status']='failed' if acquired else 'not_run'
        report['reason_codes'].append('observation_failed' if acquired else 'lease_unavailable_or_recovery_required')
    finally:
        if acquired:
            try:lease.release(clean=True);report['cleanup']['lease']='released'
            except (OSError,RuntimeError):report['cleanup']['lease']='unknown';report['execution_status']='failed'
    report['finished_utc']=utc();report['duration_ms']=round((time.monotonic()-started)*1000,3)
    data=json.dumps(report,indent=2,ensure_ascii=False).encode('utf-8')
    with (output/'result.json').open('xb') as stream:stream.write(data)
    if report['execution_status']=='completed':
        (output/'COMPLETE').write_text(hashlib.sha256(data).hexdigest(),encoding='ascii')
    return report

def validate(output):
    output=pathlib.Path(output);path=output/'result.json';marker=output/'COMPLETE'
    if path.is_symlink() or marker.is_symlink() or path.stat().st_size>131072:raise ValueError('Unsafe report')
    raw=path.read_bytes()
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate key')
            result[key]=value
        return result
    def constant(value):raise ValueError('Nonfinite value')
    report=json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
    if report.get('contract')!='android.readonly.v1' or report.get('synthetic') is not False or report.get('verdict')!='inconclusive':raise ValueError('Invalid observation contract/verdict')
    required={'no_trusted_stock_and_tampered_attestation','no_protected_service_oracle','no_causal_block_reason'}
    if not required.issubset(report.get('reason_codes',[])):raise ValueError('Missing verdict limits')
    status=report['execution_status'];observations=report['observations']
    if status not in ('completed','not_run','failed','cancelled','timed_out') or not isinstance(observations,list) or len(observations)>len(COMMANDS):raise ValueError('Invalid execution')
    for i,entry in enumerate(observations):
        key,command=COMMANDS[i]
        if entry.get('name')!=key or entry.get('command')!=list(command) or entry.get('source')!='adb_readonly':raise ValueError('Unexpected observation order/command')
        state=entry.get('status')
        if state not in ('observed','unknown','unavailable','tool_error','timed_out'):raise ValueError('Invalid observation state')
        if state=='unavailable' and key!='transport':raise ValueError('Invalid unavailable observation')
        if key=='transport' and state=='unknown':raise ValueError('Unknown transport cannot proceed')
        if state in ('tool_error','timed_out','unavailable') and i!=len(observations)-1:raise ValueError('Observations after terminal error')
        if state in ('observed','unknown','unavailable'):
            value=entry.get('value')
            if not isinstance(value,str) or len(value.encode('utf-8'))>4096 or entry.get('sha256')!=hashlib.sha256(value.encode('utf-8')).hexdigest():raise ValueError('Observation integrity failure')
            if state=='unknown' and value or state=='observed' and not value:raise ValueError('Empty observation status mismatch')
            if key=='transport' and ((state=='observed' and value!='device') or (state=='unavailable' and value=='device')):raise ValueError('Transport state mismatch')
        elif 'value' in entry or 'sha256' in entry:raise ValueError('Error must not contain raw command output')
    if report['cleanup'].get('device_changes')!='none':raise ValueError('Read-only contract changed')
    if report['cleanup'].get('lease') not in ('not_acquired','released','unknown'):raise ValueError('Invalid cleanup state')
    if report['cleanup']['lease']=='unknown' and status!='failed':raise ValueError('Unconfirmed cleanup cannot succeed')
    if status=='not_run' and (len(observations)>1 or observations and observations[0]['status'] not in ('unavailable','tool_error')):raise ValueError('Not-run state contradicts observations')
    if status=='completed':
        if len(observations)!=len(COMMANDS) or any(e['status'] not in ('observed','unknown') for e in observations) or report['cleanup'].get('lease')!='released':raise ValueError('Incomplete collection marked completed')
        if marker.read_text(encoding='ascii')!=hashlib.sha256(raw).hexdigest():raise ValueError('Completion integrity failure')
    elif marker.exists():raise ValueError('Noncompleted collection has completion marker')
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb',default='adb');parser.add_argument('--device')
    parser.add_argument('--output',type=pathlib.Path,required=True);parser.add_argument('--validate',action='store_true');args=parser.parse_args()
    if args.validate:
        try:validate(args.output)
        except (OSError,ValueError,KeyError,TypeError):print('Report validation failed.',file=sys.stderr);return 2
        print('Report valid; CHK-07 remains inconclusive.');return 0
    if not args.device:parser.error('--device is required for collection')
    try:report=collect(args.adb,args.device,args.output)
    except OSError:print('Output unavailable; choose a new private directory.',file=sys.stderr);return 2
    print(json.dumps({'execution_status':report['execution_status'],'verdict':report['verdict'],'observations':len(report['observations'])}))
    return {'completed':0,'not_run':5,'timed_out':3,'cancelled':4}.get(report['execution_status'],2)
if __name__=='__main__':raise SystemExit(main())
