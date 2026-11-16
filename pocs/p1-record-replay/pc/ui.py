"""Desktop-owned input only. One worker serializes all Appium calls."""
import argparse, base64, math, pathlib, queue, re, struct, threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox
import xml.etree.ElementTree as ET
from .adapter import Appium, Uncertain
from .core import Engine, Lease, Journal, atomic
from . import protocol as p

class Window:
    def __init__(self,root,args):
        self.root=root; self.args=args; self.tasks=queue.Queue(); self.answers=queue.Queue()
        self.busy=False; self.closing=False; self.connected=False; self.frame=None; self.image=None; self.start_point=None
        self.adapter=Appium(args.device,args.package,args.server,session_create_timeout=args.session_create_timeout); self.engine=Engine(self.adapter,args.output,args.allow_coordinates)
        self.lease=Lease(args.device)
        root.title('Finsec P1 · SYNTHETIC INPUT ONLY'); root.geometry('1050x820')
        controls=ttk.Frame(root,padding=10); controls.pack(side='right',fill='y')
        self.status=tk.StringVar(value='Disconnected. User PC/physical touches are not recorded.')
        ttk.Label(controls,text=args.device+'\n'+args.package).pack(anchor='w')
        self.replay_disabled=[]
        for label,fn in [('Connect / launch (no reset)',self.connect),('RESET fixture (outside recording)',lambda:self.maintenance('reset')),('Toggle FLAG_SECURE (outside recording)',lambda:self.maintenance('secure_toggle')),('RECORD',self.record),('STOP recording',self.stop),('Replay JSON',self.replay),('Cancel run',self.cancel)]:
            button=ttk.Button(controls,text=label,command=fn); button.pack(fill='x',pady=3)
            if label!='Cancel run': self.replay_disabled.append(button)
        ttk.Separator(controls).pack(fill='x',pady=10)
        ttk.Label(controls,text='Explicit postcondition (required)').pack(anchor='w')
        self.postid=tk.StringVar(value='screen_state'); self.posttext=tk.StringVar(value='menu')
        ttk.Combobox(controls,textvariable=self.postid,values=sorted(p.IDS),state='readonly').pack(fill='x')
        ttk.Entry(controls,textvariable=self.posttext).pack(fill='x')
        ttk.Label(controls,text='Exact text; blank = existence only').pack(anchor='w')
        ttk.Label(controls,text='Text target resource ID').pack(anchor='w',pady=(12,0))
        self.textid=tk.StringVar(value='username'); self.literal=tk.StringVar(value='qa-user')
        ttk.Combobox(controls,textvariable=self.textid,values=['username','password','recipient','amount'],state='readonly').pack(fill='x')
        ttk.Combobox(controls,textvariable=self.literal,values=sorted(p.PUBLIC_TEXT),state='readonly').pack(fill='x')
        for label,fn in [('Send public fixture text',self.text_input),('Back',lambda:self.input({'type':'back'})),('Wait for condition',lambda:self.input({'type':'wait'}))]:
            button=ttk.Button(controls,text=label,command=fn); button.pack(fill='x',pady=3); self.replay_disabled.append(button)
        self.visible=tk.BooleanVar(value=False)
        ttk.Checkbutton(controls,text='I can see this frame clearly\n(required for coordinate input)',variable=self.visible).pack(anchor='w',pady=10)
        ttk.Label(controls,text='Click = tap; drag = swipe\nNo physical-touch capture.\nNetwork collection: none\nBlack image cause: unknown\nScreenshot pixels are not interpreted.\nStop closes input immediately.\nTransport uncertainty requires recovery.',wraplength=310).pack(anchor='w')
        ttk.Label(controls,textvariable=self.status,wraplength=315).pack(anchor='w',pady=12)
        self.canvas=tk.Canvas(root,bg='#1f2937',highlightthickness=0); self.canvas.pack(side='left',fill='both',expand=True)
        self.canvas.bind('<ButtonPress-1>',self.press); self.canvas.bind('<ButtonRelease-1>',self.release)
        root.protocol('WM_DELETE_WINDOW',self.close)
        threading.Thread(target=self.worker,daemon=True).start(); root.after(50,self.drain); root.after(800,self.poll)
    def worker(self):
        while True:
            fn,done=self.tasks.get()
            try: result=fn(); self.answers.put((done,result,None))
            except Exception as e: self.answers.put((done,None,e))
    def submit(self,fn,done=None):
        if self.busy or self.closing: self.status.set('Busy; duplicate/queued operation rejected'); return False
        self.busy=True; self.tasks.put((fn,done)); return True
    def drain(self):
        try:
            while True:
                done,result,error=self.answers.get_nowait(); self.busy=False
                if error:
                    self.status.set(type(error).__name__+': '+str(error))
                    self.abort('Operation/observation failed: '+str(error))
                    if isinstance(error,Uncertain):
                        self.lease.poison(str(error)); self.connected=False
                        self.abort('Transport outcome unknown')
                elif done: done(result)
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
    def connect(self):
        if self.connected: self.status.set('Already connected'); return
        def work():
            self.lease.acquire()
            try: self.adapter.open()
            except Exception:
                try: self.adapter.close()
                except Exception: self.lease.poison('Session cleanup failed')
                if self.adapter.uncertain: self.lease.poison('Session creation outcome unknown')
                self.lease.release(clean=not self.adapter.uncertain and not self.adapter.session); raise
        def done(_): self.connected=True; self.status.set('Connected. Reset explicitly, then RECORD. Build hash verified.')
        self.submit(work,done)
    def ready(self):
        if not self.connected: self.status.set('Connect selected device first'); return False
        if self.busy: self.status.set('Busy; duplicate operation rejected'); return False
        return True
    def maintenance(self,name):
        if not self.ready(): return
        if self.engine.mode!='idle': self.status.set('Maintenance blocked during active/partial run. Reconnect after review.'); return
        def work():
            j=Journal(self.args.output,'maintenance'); self.adapter.foreground()
            elements=self.adapter.elements(p.PREFIX+name)
            if len(elements)!=1: raise RuntimeError('Maintenance locator not unique')
            j.write('intent',operation=name); self.adapter.click(elements[0]); j.write('result',status='dispatch_acknowledged')
        self.submit(work,lambda _:self.status.set('Maintenance dispatched; initial state will be checked before record/replay.'))
    def record(self):
        if self.ready(): self.submit(self.engine.start,lambda _:self.status.set('Recording · '+str(self.engine.j.path)))
    def stop(self):
        if self.engine.mode!='recording': self.status.set('No active recording'); return
        # Stop marks the boundary now; current action is conservatively incomplete if still running.
        if self.busy:
            self.engine.stop_requested(); self.status.set('STOP requested: active action drains as incomplete'); return
        self.engine.stop_requested()
        self.submit(self.engine.finish,lambda _:self.status.set('Saved '+str(self.engine.j.path/'route.json')))
    def cancel(self):
        if self.engine.mode in ['recording','replaying']:
            self.engine.stop_requested(); self.status.set('Cancellation requested; waiting for finite transport completion')
            if not self.busy: self.abort('User cancelled recording')
    def post(self):
        c={'id':p.PREFIX+self.postid.get()}
        if self.posttext.get(): c['text']=self.posttext.get()
        return c
    def input(self,a):
        if not self.ready(): return
        if self.engine.mode!='recording': self.status.set('Manual input requires RECORD; unavailable during replay'); return
        a.update(timeout=5,post=self.post())
        self.submit(lambda:self.engine.record_action(a),lambda _:self.status.set('Recorded step '+str(len(self.engine.steps))))
    def text_input(self):
        name=self.textid.get(); value=self.literal.get()
        # Text entry postcondition is exact observed public value, independent of screen dropdown.
        if not self.ready() or self.engine.mode!='recording': self.status.set('Text requires active recording'); return
        a={'type':'text','locator':p.PREFIX+name,'text':value,'timeout':5,'post':{'id':p.PREFIX+name,'text':value}}
        self.submit(lambda:self.engine.record_action(a),lambda _:self.status.set('Recorded text step '+str(len(self.engine.steps))))
    def replay(self):
        if not self.ready() or self.engine.mode!='idle': self.status.set('Replay requires idle connection; review incomplete run first'); return
        path=filedialog.askopenfilename(filetypes=[('Route JSON','*.json')])
        if not path:return
        try: route=p.load(path)
        except Exception as e:self.status.set(str(e));return
        self.submit(lambda:self.engine.replay(route),lambda result:self.status.set('Replay '+result['status']+' · '+str(self.engine.j.path/'result.json')+' '+result.get('reason','')))
    def poll(self):
        if self.connected and not self.busy and not self.closing and self.start_point is None and not self.visible.get():
            def work():
                self.adapter.foreground(); g=self.adapter.geometry(); result={'geometry':g}
                for name,fn in [('png',self.adapter.screenshot),('xml',self.adapter.source)]:
                    try: result[name]=fn()
                    except Uncertain: raise
                    except Exception as e:result[name+'_error']=str(e)
                return result
            self.submit(work,self.render)
        if not self.closing:self.root.after(900,self.poll)
    def render(self,f):
        self.frame=f; self.canvas.delete('all'); self.visible.set(False)
        if 'png' not in f:
            self.image=None; self.canvas.create_text(25,30,anchor='nw',fill='white',text='Screenshot unavailable. Cause not inferred.\n'+f.get('png_error',''));return
        try:
            iw,ih=struct.unpack('>II',f['png'][16:24]); cw=max(self.canvas.winfo_width(),1); ch=max(self.canvas.winfo_height(),1)
            original=tk.PhotoImage(data=base64.b64encode(f['png']))
            factor=max(1,math.ceil(max(iw/cw,ih/ch))); self.image=original.subsample(factor)
            self.canvas.create_image(cw/2,ch/2,image=self.image)
            f['display']=(cw,ch,self.image.width(),self.image.height()); f['pixels']=(iw,ih)
            if f['geometry']['width']!=iw or f['geometry']['height']!=ih:
                f['mapping_error']='Screenshot/window geometry differs; input blocked'
        except Exception as e:self.image=None;self.status.set('Image unavailable: '+str(e))
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
                hits=[]; x=start[0]*g['width']; y=start[1]*g['height']
                for node in ET.fromstring(self.frame.get('xml','<empty/>')).iter():
                    rid=node.get('resource-id',''); b=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.get('bounds',''))
                    if b and rid.startswith(p.PREFIX) and rid[len(p.PREFIX):] in p.IDS:
                        l,t,r,bottom=map(int,b.groups())
                        if l<=x<r and t<=y<bottom:hits.append(((r-l)*(bottom-t),rid))
                if hits:a['locator']=min(hits)[1]
                else:a.update(point=start,geometry=g)
            if 'point' in a and (not self.args.allow_coordinates or not self.visible.get()):raise ValueError('Coordinates require --allow-coordinates and visible-frame confirmation')
            self.input(a)
        except Exception as e:self.status.set(str(e))
    def close(self):
        if self.closing:return
        self.engine.stop_requested(); self.closing=True; self.status.set('Draining and closing owned session...')
        def cleanup():
            self.abort('Window closed')
            try:self.adapter.close()
            except Exception as e:self.lease.poison('Cleanup not confirmed: '+str(e))
            if self.adapter.uncertain:self.lease.poison('Transport uncertainty; manually stop Appium before recovery')
            self.lease.release(clean=not self.adapter.uncertain and not self.adapter.session)
        self.tasks.put((cleanup,lambda _:self.root.destroy()))
        def drain_close():
            self.drain()
            if self.root.winfo_exists():self.root.after(100,drain_close)
        self.root.after(100,drain_close)

def main():
    parser=argparse.ArgumentParser(description='Synthetic Appium PC recorder; no physical touch capture')
    parser.add_argument('--device',required=True); parser.add_argument('--package',required=True,choices=[p.PACKAGE])
    parser.add_argument('--server',default='http://127.0.0.1:4723'); parser.add_argument('--output',default='outputs')
    parser.add_argument('--session-create-timeout',type=int,default=90,metavar='SECONDS',help='Session creation transport timeout, 30-300 seconds (default: 90); ordinary requests remain 20 seconds')
    parser.add_argument('--allow-coordinates',action='store_true',help='Enable at most three exact-geometry coordinate actions; only on visibly observed frames')
    args=parser.parse_args()
    if not 30<=args.session_create_timeout<=300: parser.error('--session-create-timeout must be from 30 to 300 seconds')
    root=tk.Tk(); Window(root,args); root.mainloop()
if __name__=='__main__':main()
