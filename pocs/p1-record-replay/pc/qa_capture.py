"""Owned single-capture P1 window launched from the native Record tab."""
import argparse,datetime,json,os,sys,uuid
from pathlib import Path
from .core import atomic
from .qa_queue_stdio import adb_run,PACKAGE

def run(config,folder):
    import tkinter as tk
    from .combined_ui import CombinedWindow,NetworkController
    from device_resources import Reservation
    class CaptureReservation(Reservation):
        def finish(self,clean=False):pass  # Keep ownership through receipt restoration.
    folder=Path(folder);folder.mkdir(exist_ok=True)
    device=config['device'];adb=config['adb'];backup=None;window=None;root=None;errors=[];operation_error=None;owner=NetworkController()
    reservation=CaptureReservation(device);reservation.acquire()
    os.environ['PATH']=str(Path(adb).parent)+os.pathsep+os.environ.get('PATH','')
    def command(*args,**kw):return adb_run(adb,device,*args,**kw)
    try:
        from .adapter import Appium
        preflight=Appium(device,PACKAGE,config['appium']);baseline=preflight.preflight()
        if config.get('allow_existing_appium_settings') is not True or set(baseline['hidden_api'].values())!={'1'} or 'allow' not in baseline['helper_mock_location']:raise RuntimeError('Existing approved baseline required')
        atomic(folder/'baseline.json',baseline)
        backup=command('exec-out','run-as',PACKAGE,'cat','files/receipt.json');(folder/'original-receipt.json').write_bytes(backup)
        if (folder/'cancel').exists():raise InterruptedError('Cancelled before fixture')
        network=owner.start(folder,config['pki'],True)
        args=argparse.Namespace(device=device,package=PACKAGE,server=config['appium'],output=folder,
             session_create_timeout=90,allow_coordinates=True,server_jar=config['server_jar'],adb=adb,reservation=reservation)
        root=tk.Tk();window=CombinedWindow(root,args,network)
        window.adapter.approve_security(baseline);window.prepare_fixture('wss')
        root.title('Finsec native Record - ONE QA capture; STOP saves and returns')
        def watch():
            if window.closing:return
            if (folder/'cancel').exists():window.close();return
            record=getattr(window.engine,'record',{})
            if record.get('status')=='completed' and window.sync.terminated and not window.busy:
                window.close();return
            root.after(200,watch)
        root.after(200,watch);root.mainloop()
    except Exception as error:
        operation_error=type(error).__name__
        if window is not None and not window.closing:
            window.close();root.mainloop()
    finally:
        # Window.close normally drains these first. Retain uncertainty, never kill.
        if window is not None:
            try:
                window.sync.abort('Capture owner exit');window.video.close();window.adapter.close()
            except Exception as error:errors.append('session_'+type(error).__name__)
        try:owner.close()
        except Exception as error:errors.append('network_'+type(error).__name__)
        try:
            if window is not None and hasattr(window,'reverse_mapping'):window.reverse_mapping.close()
        except Exception as error:errors.append('reverse_'+type(error).__name__)
        try:
            if backup is not None:
                if window is not None and window.adapter.uncertain:raise RuntimeError('Uncertain input session')
                command('shell','am','force-stop',PACKAGE)
                command('shell','-T','run-as',PACKAGE,'sh','-c',"'cat > files/receipt.json'",input=backup)
                if command('exec-out','run-as',PACKAGE,'cat','files/receipt.json')!=backup:raise RuntimeError('Receipt mismatch')
        except Exception as error:errors.append('receipt_'+type(error).__name__)
        if reservation.lease.quarantine.exists():errors.append('existing_cleanup_quarantine')
        if errors:reservation.poison('Capture needs reconciliation; backup retained')
        reservation.end(clean=not errors)
        if root is not None:
            try:root.destroy()
            except tk.TclError:pass
    result=dict(contract='qa-capture-result.v1',execution_status='interrupted',cleanup_verified=not errors,items=[],completion={'selected':1,'completed':0},errors=errors,operation_error=operation_error)
    candidates=[]
    for path in folder.glob('*/route.json'):
        route=json.loads(path.read_text(encoding='utf-8'))
        if route.get('status')=='completed' and route.get('actions'):candidates.append(path)
    if not errors and not operation_error and len(candidates)==1 and not (folder/'cancel').exists():
        path=candidates[0];route=json.loads(path.read_text(encoding='utf-8'));link=json.loads((path.parent/'combined-link.json').read_text(encoding='utf-8'))
        if link['status']=='completed' and link['network_stop']['network_coverage']=='complete_for_supported_scope':
            now=datetime.datetime.now(datetime.timezone.utc).isoformat()
            result.update(execution_status='completed',completion={'selected':1,'completed':1},
                saved_recording=dict(ref='capture-'+uuid.uuid4().hex,name='QA capture '+now,recorded_at=now,path=str(path.resolve())),
                items=[dict(item_id='QA capture',execution_status='completed',reason='PC_GUI_RECORD_NO_INSPECTION',
                    recording_context=dict(recording_id=route['recording_id'],route_status='complete',packet_status=link['network_stop']['network_coverage']))])
    atomic(folder/'capture-result.json',result)

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'p2-proxy-relay'))
    run(json.loads(a.config.read_text(encoding='utf-8')),a.output)
if __name__=='__main__':main()
