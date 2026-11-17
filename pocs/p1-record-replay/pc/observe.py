"""Independent, read-only scrcpy viewer and volatile target lifecycle observations."""
import argparse
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from .protocol import package_name


def viewer_command(executable, device):
    return [executable, '--serial', device, '--no-control', '--no-audio',
            '--window-title', 'P1 OBSERVE ONLY - input is NOT recorded',
            '--window-height', '700']


def target_state(processes, activities, package):
    # Filter in memory; never expose unrelated process/package names in the UI.
    identities=[]
    for line in processes.splitlines():
        fields=line.split()
        if len(fields)==2 and fields[0].isdigit() and (fields[1]==package or fields[1].startswith(package+':')):
            identities.append(fields[0])
    resumed=[line for line in activities.splitlines() if 'mResumedActivity:' in line or 'topResumedActivity=' in line]
    foreground=None if not resumed else any(re.search(r'(?<![\w.])'+re.escape(package)+r'/', line) for line in resumed)
    return {'pids':tuple(sorted(identities)), 'foreground':foreground}


class Viewer:
    def __init__(self, executable, device, adb):
        self.executable=executable; self.device=device; self.adb=adb; self.process=None
    def start(self):
        if self.process and self.process.poll() is None:return
        env=dict(os.environ, ADB=self.adb)
        # Logs can contain device identities: discard, do not persist implicitly.
        self.process=subprocess.Popen(viewer_command(self.executable,self.device),env=env,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
    def status(self):
        if not self.process:return 'Viewer stopped'
        code=self.process.poll()
        return 'Viewer process running; pixel freshness unknown' if code is None else 'Viewer exited (code '+str(code)+'); restart is manual'


class Observer:
    def __init__(self,root,args):
        self.root=root;self.args=args;self.events=queue.Queue();self.closed=threading.Event()
        self.viewer=Viewer(args.scrcpy,args.device,args.adb);self.previous=object();self.last_sample=None
        root.title('P1 independent observation');root.geometry('650x480')
        ttk.Label(root,text='READ ONLY / NO RECORDING\nWhole-device view may reveal private content.\nUse P1 recorder canvas for recorded input; this viewer never injects input.',wraplength=620).pack(pady=10)
        self.status=tk.StringVar(value='Viewer stopped');ttk.Label(root,textvariable=self.status,wraplength=620).pack()
        self.target=tk.StringVar(value='Target observation pending');ttk.Label(root,textvariable=self.target).pack()
        ttk.Button(root,text='Start / restart read-only viewer',command=self.start).pack()
        ttk.Button(root,text='Hide / stop viewer',command=self.viewer.stop).pack()
        ttk.Button(root,text='Mark my launch / stop intervention',command=lambda:self.log('User intervention marked; cause not inferred')).pack()
        self.timeline=tk.Text(root,height=14,state='disabled');self.timeline.pack(fill='both',expand=True)
        root.protocol('WM_DELETE_WINDOW',self.close)
        threading.Thread(target=self.sample,daemon=True).start();root.after(100,self.drain)
        self.start()
    def start(self):
        try:self.viewer.start();self.log('Viewer requested; independent of Appium and target lifetime')
        except OSError:self.log('Viewer could not start; check official installation path')
    def log(self,text):
        self.timeline.configure(state='normal');self.timeline.insert('end',time.strftime('%H:%M:%S')+' '+text+'\n')
        if int(self.timeline.index('end-1c').split('.')[0])>200:self.timeline.delete('1.0','2.0')
        self.timeline.see('end');self.timeline.configure(state='disabled')
    def adb(self,*args):
        return subprocess.check_output([self.args.adb,'-s',self.args.device,'shell',*args],timeout=5,
            stderr=subprocess.DEVNULL,text=True,encoding='utf-8',errors='replace',
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    def sample(self):
        while not self.closed.is_set():
            try:
                state=target_state(self.adb('ps','-A','-o','PID,NAME'),self.adb('dumpsys','activity','activities'),self.args.package)
                self.events.put((time.monotonic(),state))
            except (OSError,subprocess.SubprocessError):self.events.put((time.monotonic(),None))
            self.closed.wait(1)
    def drain(self):
        if self.closed.is_set():return
        try:
            while True:
                stamp,state=self.events.get_nowait();self.last_sample=stamp
                if state is None:
                    label='Observation gap; target state unknown'
                else:
                    fg={True:'yes',False:'no',None:'unknown'}[state['foreground']]
                    label='Target processes: '+str(len(state['pids']))+'; foreground: '+fg
                self.target.set(label)
                if state!=self.previous:
                    self.log(label+'; exit cause unknown');self.previous=state
        except queue.Empty:pass
        age='pending' if self.last_sample is None else str(round(time.monotonic()-self.last_sample,1))+'s'
        self.status.set(self.viewer.status()+' | observation age '+age)
        self.root.after(200,self.drain)
    def close(self):
        self.closed.set();self.viewer.stop();self.root.destroy()


def main():
    parser=argparse.ArgumentParser(description='Independent read-only observer. No Appium, no recording, no settings changes.')
    parser.add_argument('--device',required=True);parser.add_argument('--package',required=True,type=package_name)
    parser.add_argument('--scrcpy',default=shutil.which('scrcpy'));parser.add_argument('--adb',default=shutil.which('adb'))
    args=parser.parse_args()
    if not args.scrcpy or not args.adb:parser.error('Install official scrcpy and adb, or supply their executable paths')
    root=tk.Tk();root.title('P1 observation consent');root.geometry('650x120');root.update()
    if not messagebox.askyesno('Whole-device observation', 'Show the whole device in a separate read-only window? No audio or file recording. Other apps/notifications may be visible. Close this observer to stop its viewer. Closing P1 input does not close it.',parent=root):root.destroy();return
    root.deiconify();Observer(root,args);root.mainloop()


if __name__=='__main__':main()
