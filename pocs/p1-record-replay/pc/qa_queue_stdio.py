"""Opt-in disposable network QA device owner, invoked via private native pipes."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid
from .adapter import Appium
from .core import Engine,atomic
from .combined import CombinedRun
from .combined_ui import NetworkController
from .replay_queue import ReplayQueue
from .qa_queue_api import QueueAPI,serve

PACKAGE='dev.finsec.qa.network'

def adb_run(adb,device,*args,**kw):
    # Only serve() owns the native request pipe; explicit input gets its own pipe.
    if 'input' not in kw:kw['stdin']=subprocess.DEVNULL
    return subprocess.run([adb,'-s',device,*args],capture_output=True,check=True,timeout=20,**kw).stdout

def execute(config,routes,cancel,emit):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'p2-proxy-relay'))
    from device_resources import Reservation,OwnedReverse
    if config.get('allow_existing_appium_settings') is not True:raise RuntimeError('Explicit existing-settings approval required')
    device=config['device'];adb=config['adb'];output=Path(config['output'])/('device-'+uuid.uuid4().hex);output.mkdir()
    os.environ['PATH']=str(Path(adb).parent)+os.pathsep+os.environ.get('PATH','')
    def run(*args,**kw):
        return adb_run(adb,device,*args,**kw)
    owner=NetworkController();reservation=Reservation(device);mapping=None;adapter=None;backup=None;queue=None;result=None;errors=[];operation_error=None
    reservation.acquire()
    try:
        if cancel.is_set():raise InterruptedError('Cancelled before preparation')
        adapter=Appium(device,PACKAGE,config['appium'],session_create_timeout=90)
        baseline=adapter.preflight();atomic(output/'baseline.json',baseline)
        if set(baseline['hidden_api'].values())!={'1'} or 'allow' not in baseline['helper_mock_location']:raise RuntimeError('Existing security baseline differs; manual approval required')
        if any(r['device_id']!=device or r['target']!=baseline['target'] for r in routes):raise RuntimeError('Recorded device/APK mismatch')
        backup=run('exec-out','run-as',PACKAGE,'cat','files/receipt.json');(output/'original-receipt.json').write_bytes(backup)
        network=owner.start(output,config['pki'],True)
        mapping=OwnedReverse(adb,device,network.port);port=mapping.allocate()
        if cancel.is_set():raise InterruptedError('Cancelled before session')
        adapter.approve_security(baseline);adapter.open();emit('qa_session_connected')
        engine=Engine(adapter,output);combined=CombinedRun(engine,network,output);combined.preflight=mapping.verify
        queue=ReplayQueue(combined,output);queue.cancelled=cancel
        def prepare(index,route):
            if cancel.is_set():raise InterruptedError('Cancelled before fixture preparation')
            token='qa-'+uuid.uuid4().hex[:12]
            mapping.verify()
            run('shell','am','start','-S','-n',PACKAGE+'/.MainActivity','--es','protocol','wss','--ei','port',port,'--es','token',token,'--ez','interactive','true')
            emit('route_'+str(index+1)+'_fixture_ready')
        queue.prepare=prepare
        seen=set()
        def state(value):
            for i,entry in enumerate(value['entries']):
                event='route_'+str(i+1)+'_'+entry['status']
                if event not in seen:seen.add(event);emit(event)
        queue.on_state=state
        result=queue.run(routes,reset_cancel=False)
    except Exception as error:
        operation_error=type(error).__name__
    finally:
        emit('qa_cleanup_started')
        try:
            if adapter is not None:adapter.close()
        except Exception as error:errors.append('session_'+type(error).__name__)
        try:owner.close()
        except Exception as error:errors.append('network_'+type(error).__name__)
        try:
            if mapping is not None:mapping.close()
        except Exception as error:errors.append('reverse_'+type(error).__name__)
        try:
            if backup is not None:
                if adapter is not None and adapter.uncertain:raise RuntimeError('Uncertain session; receipt backup retained')
                run('shell','am','force-stop',PACKAGE)
                run('shell','-T','run-as',PACKAGE,'sh','-c',"'cat > files/receipt.json'",input=backup)
                if run('exec-out','run-as',PACKAGE,'cat','files/receipt.json')!=backup:raise RuntimeError('Receipt restoration mismatch')
        except Exception as error:errors.append('receipt_'+type(error).__name__)
        if errors:reservation.poison('Native QA queue needs review; private evidence retained')
        reservation.end(clean=not errors)
    cleanup=not errors
    atomic(output/'cleanup.json',dict(verified=cleanup,errors=errors,operation_error=operation_error))
    items=[]
    if result is not None:
        db=network.db
        with sqlite3.connect('file:'+db.as_posix()+'?mode=ro',uri=True) as connection:
            for entry in result['entries']:
                network_id=entry.get('network_recording_id');record=None;count=0
                if network_id:
                    row=connection.execute('select data from recordings where id=?',(network_id,)).fetchone()
                    record=json.loads(row[0]) if row else None
                    count=connection.execute('select count(*) from packets where recording_id=?',(network_id,)).fetchone()[0]
                items.append(dict(item_id='QA route',execution_status=entry['status'],reason='REPLAY_ONLY_NO_INSPECTION',
                    replay_run_id=entry.get('replay_run_id'),network_recording_id=network_id,packet_count=count,
                    recording_context=dict(recording_id=entry['source_recording_id'],route_status=entry['status'],packet_status=record.get('network_coverage') if record else 'not_collected')))
    return dict(contract='qa-queue-result.v1',real_device=True,cleanup_verified=cleanup,
                execution_status='completed' if cleanup and result and result['status']=='succeeded' else 'interrupted',
                completion=dict(selected=len(routes),completed=sum(i['execution_status']=='succeeded' for i in items)),items=items)

def capture(config,folder,cancel,emit):
    import time
    output=folder/'capture';output.mkdir()
    private_config=folder/'capture-config.json';atomic(private_config,config)
    if cancel.is_set():return dict(execution_status='interrupted',cleanup_verified=True,items=[],completion={})
    with (folder/'capture-stderr.log').open('w',encoding='utf-8') as errors:
        child=subprocess.Popen([sys.executable,'-m','pc.qa_capture','--config',str(private_config),'--output',str(output)],
            cwd=Path(__file__).resolve().parent.parent,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=errors)
        emit('capture_window_opening')
        while child.poll() is None:
            if cancel.is_set() and not (output/'cancel').exists():
                (output/'cancel').write_text('cancel');emit('capture_cancel_requested')
            time.sleep(.1)
        path=output/'capture-result.json'
        if child.returncode!=0 or not path.exists():raise RuntimeError('Capture exit requires reconciliation')
        emit('capture_window_closed');return json.loads(path.read_text(encoding='utf-8'))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);args=parser.parse_args()
    if args.config.stat().st_size>65536:raise ValueError('Configuration limit')
    config=json.loads(args.config.read_text(encoding='utf-8'))
    api=QueueAPI(config,execute,capture);serve(api,sys.stdin,sys.stdout)

if __name__=='__main__':main()
