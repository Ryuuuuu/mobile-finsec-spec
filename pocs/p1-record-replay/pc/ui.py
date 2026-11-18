"""Desktop-owned input only. One worker serializes all Appium calls."""
import argparse, base64, math, pathlib, queue, re, struct, subprocess, sys, threading, time, tkinter as tk
from tkinter import ttk, filedialog, messagebox
import xml.etree.ElementTree as ET
from .adapter import Appium, Uncertain, TargetNotForeground
from .core import Engine, Lease, Journal, atomic
from . import protocol as p

def tap_resource(xml,x,y,package):
    hits=[]
    for node in ET.fromstring(xml).iter():
        # Resource identity alone does not make a container an input target.
        if node.get('clickable')!='true' or node.get('enabled')=='false':continue
        rid=node.get('resource-id','')
        try:p.resource(rid,package)
        except ValueError:continue
        bounds=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.get('bounds',''))
        if bounds:
            l,t,r,b=map(int,bounds.groups())
            if l<=x<r and t<=y<b:hits.append(((r-l)*(b-t),rid))
    return min(hits)[1] if hits else None

class Window:
    def __init__(self,root,args):
        self.root=root; self.args=args; self.tasks=queue.Queue(); self.answers=queue.Queue()
        self.busy=False; self.observing=False; self.pending_input=None
        self.closing=False; self.connected=False; self.frame=None; self.image=None; self.start_point=None
        self.adapter=Appium(args.device,args.package,args.server,session_create_timeout=args.session_create_timeout); self.engine=Engine(self.adapter,args.output,args.allow_coordinates)
        self.lease=getattr(args,'device_lease',None) or Lease(args.device)
        self.generic=args.package!=p.PACKAGE
        root.title('Finsec P1 · SELECTED APP QA'); root.geometry('1050x820')
        controls=ttk.Frame(root,padding=10); controls.pack(side='right',fill='y')
        self.status=tk.StringVar(value='Disconnected. User PC/physical touches are not recorded.')
        self.preview_status=tk.StringVar(value='Preview disconnected. Connect to view the selected app.')
        ttk.Label(controls,text=args.device+'\n'+args.package).pack(anchor='w')
        self.replay_disabled=[]
        self.observer_process=None
        ttk.Button(controls,text='Independent read-only observation',command=self.observe_device).pack(fill='x')
        if self.generic:ttk.Button(controls,text='Launch selected app (no session)',command=self.launch).pack(fill='x')
        for label,fn in [('Connect (no reset)',self.connect),('RESET fixture (outside recording)',lambda:self.maintenance('reset')),('Toggle FLAG_SECURE (outside recording)',lambda:self.maintenance('secure_toggle')),('RECORD',self.record),('STOP recording',self.stop),('Replay JSON',self.replay),('Cancel run',self.cancel)]:
            if self.generic and (label.startswith('RESET') or label.startswith('Toggle')):continue
            button=ttk.Button(controls,text=label,command=fn); button.pack(fill='x',pady=3)
            if label!='Cancel run': self.replay_disabled.append(button)
        ttk.Separator(controls).pack(fill='x',pady=10)
        ttk.Label(controls,text='Initial at RECORD / next action postcondition').pack(anchor='w')
        self.postid=tk.StringVar(value='' if self.generic else 'screen_state'); self.posttext=tk.StringVar(value='' if self.generic else 'menu')
        self.post_selector=ttk.Combobox(controls,textvariable=self.postid,values=[] if self.generic else sorted(p.IDS),state='normal' if self.generic else 'readonly');self.post_selector.pack(fill='x')
        ttk.Entry(controls,textvariable=self.posttext).pack(fill='x')
        ttk.Label(controls,text='Exact text; blank = existence only').pack(anchor='w')
        ttk.Label(controls,text='Text target resource ID').pack(anchor='w',pady=(12,0))
        self.textid=tk.StringVar(value='' if self.generic else 'username'); self.literal=tk.StringVar(value='' if self.generic else 'qa-user')
        self.text_selector=ttk.Combobox(controls,textvariable=self.textid,values=[] if self.generic else ['username','password','recipient','amount'],state='normal' if self.generic else 'readonly');self.text_selector.pack(fill='x')
        ttk.Combobox(controls,textvariable=self.literal,values=[] if self.generic else sorted(p.PUBLIC_TEXT),state='normal' if self.generic else 'readonly').pack(fill='x')
        for label,fn in [('Send non-secret test text',self.text_input),('Back',lambda:self.input({'type':'back'})),('Wait for condition',lambda:self.input({'type':'wait'}))]:
            button=ttk.Button(controls,text=label,command=fn); button.pack(fill='x',pady=3); self.replay_disabled.append(button)
        self.visible=tk.BooleanVar(value=False)
        ttk.Checkbutton(controls,text='I can see this frame clearly\n(required for coordinate input)',variable=self.visible).pack(anchor='w',pady=10)
        ttk.Label(controls,text='Click = tap; drag = swipe\nNo physical-touch capture.\nNetwork collection: none\nBlack image cause: unknown\nScreenshot pixels are not interpreted.\nStop closes input immediately.\nTransport uncertainty requires recovery.',wraplength=310).pack(anchor='w')
        ttk.Label(controls,textvariable=self.status,wraplength=315).pack(anchor='w',pady=12)
        ttk.Label(controls,textvariable=self.preview_status,wraplength=315).pack(anchor='w')
        self.canvas=tk.Canvas(root,bg='#1f2937',highlightthickness=0); self.canvas.pack(side='left',fill='both',expand=True)
        self.canvas.bind('<ButtonPress-1>',self.press); self.canvas.bind('<ButtonRelease-1>',self.release)
        root.protocol('WM_DELETE_WINDOW',self.close)
        threading.Thread(target=self.worker,daemon=True).start(); root.after(50,self.drain); root.after(800,self.poll)
    def observe_device(self):
        if self.observer_process and self.observer_process.poll() is None:
            self.status.set('Independent observer already open');return
        command=[sys.executable,'-m','pc.observe','--device',self.args.device,'--package',self.args.package]
        if getattr(self.args,'scrcpy',None):command.extend(['--scrcpy',self.args.scrcpy])
        try:
            self.observer_process=subprocess.Popen(command,cwd=pathlib.Path(__file__).resolve().parent.parent)
            self.status.set('Observer opens separately; its clicks are NOT recorded. Close its own window to stop it.')
        except OSError as e:self.status.set('Observer could not start: '+str(e))
    def clear_preview(self,reason):
        # Invalidate both pixels and their input mapping; never leave stale input targets.
        self.frame=None; self.image=None; self.start_point=None; self.visible.set(False)
        self.canvas.delete('all')
        self.canvas.create_text(25,30,anchor='nw',fill='white',text=reason,
                                width=max(100,self.canvas.winfo_width()-50))
        self.preview_status.set(reason)
    def worker(self):
        while True:
            fn,done=self.tasks.get()
            try: result=fn(); self.answers.put((done,result,None))
            except Exception as e: self.answers.put((done,None,e))
    def submit(self,fn,done=None):
        if self.busy and self.observing and self.pending_input is None and not self.closing:
            self.pending_input=(fn,done)
            self.status.set('Input accepted; waiting for the current preview request.')
            return True
        if self.busy or self.closing: self.status.set('Busy; duplicate/queued operation rejected'); return False
        self.busy=True; self.tasks.put((fn,done)); return True
    def drain(self):
        try:
            while True:
                done,result,error=self.answers.get_nowait(); self.busy=False
                was_observing=self.observing; self.observing=False
                pending=self.pending_input; self.pending_input=None
                if error:
                    reason=('Preview paused: target app is not foreground. Return to '+getattr(getattr(self,'args',None),'package',p.PACKAGE)+'.'
                            if isinstance(error,TargetNotForeground) else 'Preview unavailable: '+str(error))
                    self.clear_preview(reason)
                    self.status.set(type(error).__name__+': '+str(error))
                    self.abort('Operation/observation failed: '+str(error))
                    if isinstance(error,Uncertain):
                        self.lease.poison(str(error)); self.connected=False
                        self.abort('Transport outcome unknown')
                else:
                    if not was_observing:self.visible.set(False)
                    if done: done(result)
                    if pending and not self.closing:self.submit(*pending)
        except queue.Empty: pass
        if not self.closing:
            for button in self.replay_disabled: button.state(['disabled'] if self.engine.mode=='replaying' else ['!disabled'])
            self.root.after(50,self.drain)
    def abort(self,reason):
        if self.engine.j and self.engine.mode not in ['idle','incomplete','failed']:
            self.engine.mode='incomplete'
            try:
                self.engine.j.write('gap',reason=reason)
                if hasattr(self.engine,'record'):
                    self.engine.record['status']='incomplete'; atomic(self.engine.j.path/'route.json',self.engine.record)
            except OSError: pass
    def launch(self):
        if self.engine.mode!='idle':self.status.set('Launch blocked during active or partial run');return
        if not messagebox.askyesno('Launch selected app',self.adapter.package+' will open without reset. Continue?'):return
        def work():
            if self.connected:return self.adapter.launch()
            self.lease.acquire()
            try:return self.adapter.launch()
            finally:self.lease.release(clean=True)
        self.submit(work,lambda v:self.status.set(v))
    def resource_id(self,value):
        return value if self.adapter.package!=p.PACKAGE else p.PREFIX+value
    def connect(self):
        if self.connected: self.status.set('Already connected'); return
        if self.adapter.package!=p.PACKAGE and not getattr(self.adapter,'security_approved',False):
            def reviewed(report):
                warning='Target: '+report['package']+'\nLauncher: '+report['launcher']+'\nApp data will not be reset. Preview reads screen/XML in memory; routes store text and IDs locally. Use only authorized non-sensitive QA.\n\nAppium may install helpers, change three hidden API policies and allow helper mock location. These settings will be restored and verified on close. Do you approve these temporary changes and preview access?'
                if messagebox.askyesno('Review session effects',warning):
                    try:
                        folder=pathlib.Path(self.args.output);folder.mkdir(parents=True,exist_ok=True)
                        self.baseline_path=folder/('security-baseline-'+str(time.time_ns())+'.json')
                        atomic(self.baseline_path,report)
                        self.adapter.approve_security(report);self.connect()
                    except Exception as e:self.status.set('Preflight blocked: '+str(e))
            self.submit(self.adapter.preflight,reviewed); return
        self.clear_preview('Connecting; waiting for a fresh frame.')
        def work():
            self.lease.acquire()
            try: self.adapter.open()
            except Exception:
                try: self.adapter.close()
                except Exception: self.lease.poison('Session cleanup failed')
                if self.adapter.uncertain: self.lease.poison('Session creation outcome unknown')
                self.lease.release(clean=not self.adapter.uncertain and not self.adapter.session); raise
        def done(_): self.connected=True; self.status.set('Connected. Open '+self.adapter.package+' to view it. Build hash verified; reset remains explicit.')
        self.submit(work,done)
    def ready(self):
        if not self.connected: self.status.set('Connect selected device first'); return False
        if self.busy and (not self.observing or self.pending_input is not None): self.status.set('Busy; duplicate operation rejected'); return False
        return True
    def maintenance(self,name):
        if self.adapter.package!=p.PACKAGE: self.status.set('Fixture maintenance unavailable for selected app'); return
        if not self.ready(): return
        if self.engine.mode!='idle': self.status.set('Maintenance blocked during active/partial run. Reconnect after review.'); return
        def work():
            j=Journal(self.args.output,'maintenance'); self.adapter.foreground()
            elements=self.adapter.elements(p.PREFIX+name)
            if len(elements)!=1: raise RuntimeError('Maintenance locator not unique')
            j.write('intent',operation=name); self.adapter.click(elements[0]); j.write('result',status='dispatch_acknowledged')
        self.submit(work,lambda _:self.status.set('Maintenance dispatched; initial state will be checked before record/replay.'))
    def record(self):
        if self.engine.mode!='idle':self.status.set('Recording/replay already active or incomplete; no new recording started');return
        if self.adapter.package!=p.PACKAGE:
            try:
                self.engine.initial_condition=self.post(); p.condition(self.engine.initial_condition,self.adapter.package)
            except ValueError as e:self.status.set(str(e));return
        if self.ready(): self.submit(self.engine.start,lambda _:self.status.set('Recording · '+str(self.engine.j.path)))
    def stop(self):
        if self.engine.mode!='recording': self.status.set('No active recording'); return
        # Stop marks the boundary now; current action is conservatively incomplete if still running.
        if self.busy and not self.observing:
            self.engine.stop_requested(); self.status.set('STOP requested: active action drains as incomplete'); return
        # Preview reads are not input: discard undispatched input, then finish after the read.
        if self.observing:self.pending_input=None
        self.engine.stop_requested()
        self.submit(self.engine.finish,lambda _:self.status.set('Saved '+str(self.engine.j.path/'route.json')))
    def cancel(self):
        if self.engine.mode in ['recording','replaying']:
            self.engine.stop_requested(); self.status.set('Cancellation requested; waiting for finite transport completion')
            if not self.busy: self.abort('User cancelled recording')
    def post(self):
        c={'id':self.resource_id(self.postid.get())}
        if self.posttext.get(): c['text']=self.posttext.get()
        return c
    def input(self,a):
        if not self.ready(): return
        if self.engine.mode!='recording': self.status.set('Manual input requires RECORD; unavailable during replay'); return
        a.update(timeout=5,post=self.post())
        self.submit(lambda:self.engine.record_action(a),lambda _:self.status.set('Recorded step '+str(len(self.engine.steps))))
    def text_input(self):
        name=self.textid.get(); value=self.literal.get()
        if self.adapter.package!=p.PACKAGE and not messagebox.askyesno('Local plaintext route','This text and postcondition will be stored locally in plaintext. Confirm it is non-secret authorized test data.'):return
        # Text entry postcondition is exact observed public value, independent of screen dropdown.
        if not self.ready() or self.engine.mode!='recording': self.status.set('Text requires active recording'); return
        a={'type':'text','locator':self.resource_id(name),'text':value,'timeout':5,'post':{'id':self.resource_id(name),'text':value}}
        self.submit(lambda:self.engine.record_action(a),lambda _:self.status.set('Recorded text step '+str(len(self.engine.steps))))
    def replay(self):
        if not self.ready() or self.engine.mode!='idle': self.status.set('Replay requires idle connection; review incomplete run first'); return
        path=filedialog.askopenfilename(filetypes=[('Route JSON','*.json')])
        if not path:return
        try: route=p.load(path)
        except Exception as e:self.status.set(str(e));return
        if route['package_id']!=self.adapter.package:self.status.set('Selected package mismatch');return
        if self.adapter.package!=p.PACKAGE and not messagebox.askyesno('Replay review',str(len(route['actions']))+' actions in '+route['package_id']+'. No automatic reset. Manually restore the recorded initial state. Actions may change app/server data and cannot be undone. Review the local route first. Proceed?'):return
        self.submit(lambda:self.engine.replay(route),lambda result:self.status.set('Replay '+result['status']+' · '+str(self.engine.j.path/'result.json')+' '+result.get('reason','')))
    def poll(self):
        if self.connected and self.visible.get():
            self.preview_status.set('Preview held for coordinate input. Uncheck the frame confirmation to resume updates.')
        if self.connected and not self.busy and not self.closing and self.start_point is None and not self.visible.get():
            def work():
                self.adapter.foreground(); g=self.adapter.geometry(); result={'geometry':g}
                for name,fn in [('png',self.adapter.screenshot),('xml',self.adapter.source)]:
                    try: result[name]=fn()
                    except Uncertain: raise
                    except Exception as e:result[name+'_error']=str(e)
                # The foreground can change while screenshot/source requests are in flight.
                self.adapter.foreground()
                result['received_at']=time.strftime('%H:%M:%S')
                return result
            if self.submit(work,self.render):self.observing=True
        if not self.closing:self.root.after(900,self.poll)
    def render(self,f):
        # A hold selected during an in-flight observation applies to the displayed frame.
        if self.visible.get() and self.frame is not None and 'png' in f:
            self.preview_status.set('Preview held for coordinate input. Uncheck the frame confirmation to resume updates.')
            return
        self.clear_preview('Waiting for a fresh frame.')
        if 'png' not in f:
            self.clear_preview('Screenshot unavailable. Cause not inferred.\n'+f.get('png_error',''));return
        try:
            iw,ih=struct.unpack('>II',f['png'][16:24]); cw=max(self.canvas.winfo_width(),1); ch=max(self.canvas.winfo_height(),1)
            original=tk.PhotoImage(data=base64.b64encode(f['png']))
            factor=max(1,math.ceil(max(iw/cw,ih/ch))); self.image=original.subsample(factor)
            self.canvas.delete('all')
            self.canvas.create_image(cw/2,ch/2,image=self.image)
            self.frame=f
            if getattr(self,'generic',False):
                ids=[]
                for n in ET.fromstring(f.get('xml','<empty/>')).iter():
                    rid=n.get('resource-id','')
                    try:p.resource(rid,self.adapter.package)
                    except ValueError:continue
                    ids.append(rid)
                self.post_selector['values']=sorted(set(ids));self.text_selector['values']=sorted(set(ids))
            f['display']=(cw,ch,self.image.width(),self.image.height()); f['pixels']=(iw,ih)
            if f['geometry']['width']!=iw or f['geometry']['height']!=ih:
                f['mapping_error']='Screenshot/window geometry differs; input blocked'
            secure='unknown'
            try:
                states=[n.get('text') for n in ET.fromstring(f.get('xml','<empty/>')).iter()
                        if n.get('resource-id')==p.PREFIX+'secure_state']
                if len(states)==1 and states[0] in ('secure:on','secure:off'):secure=states[0]
            except ET.ParseError:pass
            message='Frame received '+f.get('received_at','unknown time')+'; fixture '+secure+'.'
            if secure=='secure:on':message+=' FLAG_SECURE is ON; app pixels may be blank. No capture bypass.'
            if 'xml' not in f:message+=' UI hierarchy unavailable.'
            self.preview_status.set(message)
        except Exception as e:
            self.clear_preview('Image unavailable: '+str(e));self.status.set('Image unavailable: '+str(e))
    def point(self,event):
        if not self.frame or not self.image or 'display' not in self.frame:raise ValueError('No screenshot')
        if 'mapping_error' in self.frame:raise ValueError(self.frame['mapping_error'])
        cw,ch,iw,ih=self.frame['display']
        # PhotoImage has integral subsampling, not stretched to fill the canvas.
        point=[(event.x-(cw-iw)/2)/iw,(event.y-(ch-ih)/2)/ih]
        if any(v<0 or v>=1 for v in point):raise ValueError('Outside image')
        return point
    def press(self,event):
        try:self.start_point=self.point(event)
        except ValueError as e:self.start_point=None;self.status.set(str(e))
    def release(self,event):
        if self.start_point is None:return
        try:
            end=self.point(event); start=self.start_point; self.start_point=None
            g=self.frame['geometry']; a={'type':'tap'}
            swipe=abs(end[0]-start[0])+abs(end[1]-start[1])>.035
            if swipe:a={'type':'swipe','point':start,'end':end,'geometry':g}
            else:
                rid=tap_resource(self.frame.get('xml','<empty/>'),start[0]*g['width'],start[1]*g['height'],self.adapter.package)
                if rid:a['locator']=rid
                else:a.update(point=start,geometry=g)
            if 'point' in a and (not self.args.allow_coordinates or not self.visible.get()):raise ValueError('Coordinates require --allow-coordinates and visible-frame confirmation')
            self.input(a)
        except Exception as e:self.status.set(str(e))
    def close(self):
        if self.closing:return
        self.engine.stop_requested(); self.closing=True; self.status.set('Draining and closing owned session...')
        self.clear_preview('Preview stopped; closing the session.')
        def cleanup():
            self.abort('Window closed')
            try:
                self.adapter.close()
                if hasattr(self,'baseline_path') and not hasattr(self.adapter,'security_baseline'):
                    atomic(self.baseline_path.with_suffix('.restored.json'),{'status':'verified','baseline':self.baseline_path.name})
            except Exception as e:self.lease.poison('Cleanup not confirmed: '+str(e))
            if self.adapter.uncertain:self.lease.poison('Transport uncertainty; manually stop Appium before recovery')
            finish=getattr(type(self.lease),'finish',None)
            clean=not self.adapter.uncertain and not self.adapter.session
            if finish:finish(self.lease,clean=clean)
            else:self.lease.release(clean=clean)
        finished=False
        def finish_close(_):
            nonlocal finished
            finished=True
            self.root.destroy()
        self.tasks.put((cleanup,finish_close))
        def drain_close():
            self.drain()
            # destroy also removes Tk's winfo command; use Python completion state.
            if not finished:self.root.after(100,drain_close)
        self.root.after(100,drain_close)

def main():
    parser=argparse.ArgumentParser(description='Selected installed-app QA recorder; no physical touch capture')
    parser.add_argument('--device',required=True); parser.add_argument('--package',type=p.package_name)
    parser.add_argument('--server',default='http://127.0.0.1:4723'); parser.add_argument('--output',default='outputs')
    parser.add_argument('--session-create-timeout',type=int,default=90,metavar='SECONDS',help='Session creation transport timeout, 30-300 seconds (default: 90); ordinary requests remain 20 seconds')
    parser.add_argument('--allow-coordinates',action='store_true',help='Enable at most three exact-geometry coordinate actions; only on visibly observed frames')
    parser.add_argument('--scrcpy',help='Official scrcpy executable for independent read-only observation')
    parser.add_argument('--launch-only',action='store_true',help='Resolve and start launcher via ADB; no Appium session or screenshots')
    parser.add_argument('--list-apps',action='store_true',help='List installed user-app package IDs via ADB; no session')
    args=parser.parse_args()
    if args.list_apps:
        a=Appium(args.device,args.package or p.PACKAGE,args.server)
        print(a.adb('shell','pm','list','packages','-3'));return
    if not args.package:parser.error('--package is required except with --list-apps')
    if args.launch_only:
        lease=Lease(args.device);lease.acquire()
        try:print(Appium(args.device,args.package,args.server).launch())
        finally:lease.release(clean=True)
        return
    if not 30<=args.session_create_timeout<=300: parser.error('--session-create-timeout must be from 30 to 300 seconds')
    root=tk.Tk(); Window(root,args); root.mainloop()
if __name__=='__main__':main()
