"""Read-only Android observations, never a CHK-07 security verdict."""
import argparse,datetime,hashlib,json,pathlib,subprocess,sys,time,uuid

PROPERTIES=('ro.build.version.sdk','ro.build.version.release','ro.build.version.security_patch',
    'ro.build.type','ro.build.tags','ro.debuggable','ro.secure','ro.boot.verifiedbootstate',
    'ro.boot.flash.locked','ro.boot.vbmeta.device_state')
COMMANDS=(('transport',('get-state',)),)+tuple((p,('shell','getprop',p)) for p in PROPERTIES)+(('shell_identity',('shell','id')),('selinux',('shell','getenforce')))

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def invoke(adb,device,command):
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
    except (OSError,RuntimeError):report['reason_codes'].append('lease_unavailable_or_recovery_required')
    finally:
        if acquired:
            try:lease.release(clean=True);report['cleanup']['lease']='released'
            except OSError:report['cleanup']['lease']='unknown';report['execution_status']='failed'
    report['finished_utc']=utc();report['duration_ms']=round((time.monotonic()-started)*1000,3)
    data=json.dumps(report,indent=2,ensure_ascii=False).encode('utf-8')
    with (output/'result.json').open('xb') as stream:stream.write(data)
    if report['execution_status']=='completed':
        (output/'COMPLETE').write_text(hashlib.sha256(data).hexdigest(),encoding='ascii')
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb',default='adb');parser.add_argument('--device',required=True)
    parser.add_argument('--output',type=pathlib.Path,required=True);args=parser.parse_args()
    try:report=collect(args.adb,args.device,args.output)
    except OSError:print('Output unavailable; choose a new private directory.',file=sys.stderr);return 2
    print(json.dumps({'execution_status':report['execution_status'],'verdict':report['verdict'],'observations':len(report['observations'])}))
    return {'completed':0,'not_run':5,'timed_out':3,'cancelled':4}.get(report['execution_status'],2)
if __name__=='__main__':raise SystemExit(main())
