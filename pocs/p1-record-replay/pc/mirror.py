"""Continuous scrcpy video with P1-owned, journaled input (not SDL interception)."""
import argparse
import io
import math
import re
import xml.etree.ElementTree as ET
import pathlib
import time
import tkinter as tk
from tkinter import ttk,messagebox
from PIL import ImageTk,Image,ImageChops
from . import protocol as p
from .ui import Window
from .video import Video

def mapping(frame,geometry,now,generation):
    if frame is None or now-frame['at']>5:raise ValueError('Video stale; input blocked')
    if frame['generation']!=generation:raise ValueError('Video rotated/restarted; input blocked')
    if frame['size']!=(geometry['width'],geometry['height']):raise ValueError('Video/device dimensions differ; input blocked')

def content_region(xml,package,locator,size,status_bar=None):
    """Only an identified app target inside a unique Android content root may omit system bars."""
    def bounds(node):
        match=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.get('bounds',''))
        if not match:return None
        l,t,r,b=map(int,match.groups())
        return (l,t,r,b) if 0<=l<r<=size[0] and 0<=t<b<=size[1] else None
    if not locator:return None
    try:root=ET.fromstring(xml)
    except ET.ParseError:return None
    contents=[n for n in root.iter() if n.get('package')==package and n.get('resource-id')=='android:id/content']
    if len(contents)!=1:return None
    area=bounds(contents[0])
    targets=[n for n in contents[0].iter() if n.get('package')==package and n.get('resource-id')==locator and n.get('clickable')=='true' and n.get('enabled')!='false']
    if area is None or len(targets)!=1:return None
    if status_bar is not None:
        bar=status_bar
        if (not isinstance(bar,dict) or bar.get('visible') is not True or
            any(type(bar.get(k)) is not int for k in ('x','y','width','height')) or
            bar['x']!=0 or bar['y']!=0 or bar['width']!=size[0] or not 0<bar['height']<size[1]//4):return None
        area=(area[0],max(area[1],bar['height']),area[2],area[3])
    target=bounds(targets[0])
    if target is None or not (area[0]<=target[0]<target[2]<=area[2] and area[1]<=target[1]<target[3]<=area[3]):return None
    return area

def verify_pixels(displayed,png,region=None):
    current=Image.open(io.BytesIO(png)).convert('RGB')
    if current.size!=displayed.size:raise ValueError('Current screenshot dimensions differ')
    # Local block error, not a global average that would hide a changed button.
    if region is not None:
        l,t,r,b=region
        if not (0<=l<r<=current.width and 0<=t<b<=current.height):raise ValueError('Invalid comparison region')
        displayed=displayed.crop(region);current=current.crop(region)
    difference=ImageChops.difference(displayed.convert('RGB'),current)
    blocks=difference.resize((math.ceil(current.width/16),math.ceil(current.height/16)),Image.Resampling.BOX)
    score=max(high for low,high in blocks.getextrema())
    if score>12:raise ValueError('Displayed video differs from current screenshot; wait for video refresh')
    return score

class MirrorWindow(Window):
    def __init__(self,root,args):
        self.video=Video(args.device,args.server_jar,args.adb);self.metadata=None;self.video_frame=None
        self.gesture_frame=None;self.seen_generation=None
        super().__init__(root,args)
        root.title('Finsec P1 - SCRCPY VIDEO / RECORDED INPUT')
        controls=self.post_selector.master
        for child in controls.winfo_children():
            try:
                if str(child.cget('text')).startswith(('Independent read-only observation','Click = tap;')):child.pack_forget()
            except tk.TclError:pass
        ttk.Button(controls,text='Disconnect input; keep video',command=self.disconnect).pack(fill='x',before=controls.winfo_children()[0])
        ttk.Label(controls,text='Live scrcpy video: click/drag while RECORD.\nConfirm visible pixels for coordinates.\nNo audio/video file recording.\nOutside target: observation only.',wraplength=300).pack()
        self.video.start();root.after(100,self.video_tick)
    def clear_preview(self,reason):
        # Metadata failure disables input without destroying independent video.
        self.metadata=None;self.frame=None;self.start_point=None
        if hasattr(self,'visible'):self.visible.set(False)
        if hasattr(self,'preview_status'):self.preview_status.set(reason+'; video observation continues')
    def poll(self):
        if self.connected and not self.busy and not self.closing:
            def read():
                self.adapter.foreground();g=self.adapter.geometry();xml=self.adapter.source();bars=self.adapter.call('GET','/appium/device/system_bars');self.adapter.foreground()
                return {'geometry':g,'xml':xml,'status_bar':bars.get('statusBar'),'at':time.monotonic()}
            if self.submit(read,self.render):self.observing=True
        if not self.closing:self.root.after(700,self.poll)
    def render(self,metadata):
        self.metadata=metadata
    def video_tick(self):
        if self.closing:return
        video,error,generation=self.video.snapshot()
        if video is None or error:
            self.frame=None;self.video_frame=None;self.start_point=None;self.visible.set(False)
            self.canvas.delete('all');self.canvas.create_text(20,30,anchor='nw',fill='white',text=error or 'Waiting for fresh scrcpy video; input blocked')
        else:
            if generation!=self.seen_generation:
                self.start_point=None;self.visible.set(False);self.seen_generation=generation
            cw=max(1,self.canvas.winfo_width());ch=max(1,self.canvas.winfo_height())
            iw,ih=video['size'];scale=min(cw/iw,ch/ih);size=(max(1,int(iw*scale)),max(1,int(ih*scale)))
            self.image=ImageTk.PhotoImage(video['image'].resize(size));self.canvas.delete('all')
            self.canvas.create_image(cw/2,ch/2,image=self.image);self.video_frame=video
            self.frame=None
            if self.connected and self.metadata and time.monotonic()-self.metadata['at']<=2:
                try:
                    mapping(dict(video,at=time.monotonic()),self.metadata['geometry'],time.monotonic(),generation)
                    self.frame=dict(self.metadata,display=(cw,ch,*size),pixels=(iw,ih))
                except ValueError:pass
            age=round(time.monotonic()-video['at'],1)
            self.preview_status.set('Last video frame '+str(age)+'s ago; '+('input requires fresh screenshot verification' if self.frame else 'observation only; target/geometry not verified'))
        self.root.after(100,self.video_tick)
    def press(self,event):
        if not self.frame:self.status.set('Target input unavailable');return
        self.gesture_frame=self.video_frame;self.gesture_display=tuple(self.frame['display'])
        super().press(event)
    def release(self,event):
        try:
            if self.gesture_frame is None or not self.frame:raise ValueError('Input frame unavailable')
            if tuple(self.frame['display'])!=self.gesture_display:raise ValueError('Canvas resized during gesture; input blocked')
            _,error,generation=self.video.snapshot()
            if error:raise ValueError('Video disconnected')
            mapping(dict(self.gesture_frame,at=time.monotonic()),self.frame['geometry'],time.monotonic(),generation)
            super().release(event)
        except ValueError as error:self.start_point=None;self.status.set(str(error))
    def input(self,action):
        if not self.ready() or self.engine.mode!='recording':self.status.set('Input requires idle RECORD operation');return
        frame=self.gesture_frame if action['type'] in ('tap','swipe') else self.video_frame
        if frame is None:self.status.set('No input frame');return
        geometry=dict(self.metadata['geometry']) if self.metadata else None
        region=content_region(self.metadata['xml'],self.adapter.package,action.get('locator'),frame['size'],self.metadata.get('status_bar')) if self.metadata else None
        status_bar=self.metadata.get('status_bar') if self.metadata else None
        action.update(timeout=5,post=self.post())
        def dispatch():
            latest,error,generation=self.video.snapshot()
            if error or geometry is None:raise ValueError('Video/metadata unavailable before dispatch')
            self.adapter.foreground()
            if region is not None and self.adapter.call('GET','/appium/device/system_bars').get('statusBar')!=status_bar:raise ValueError('System bar geometry changed before dispatch')
            score=verify_pixels(frame['image'],self.adapter.screenshot(),region)
            verified_at=time.monotonic()
            _,error,generation=self.video.snapshot()
            if error:raise ValueError('Video disconnected during verification')
            mapping(dict(frame,at=verified_at),geometry,time.monotonic(),generation)
            if self.adapter.geometry()!=geometry:raise ValueError('Geometry/rotation changed before dispatch')
            self.engine.j.write('video_input',source='scrcpy-5.0.1',generation=generation,block_error=score,comparison_scope='app_content' if region else 'full_display')
            self.engine.record_action(action)
        self.submit(dispatch,lambda _:self.status.set('Recorded step '+str(len(self.engine.steps))))
    def disconnect(self):
        if self.busy or self.engine.mode!='idle':self.status.set('STOP recording and wait for idle before disconnect');return
        def work():
            self.adapter.close();self.lease.release(clean=not self.adapter.uncertain and not self.adapter.session)
        def done(_):self.connected=False;self.metadata=None;self.frame=None;self.status.set('Input disconnected; video remains live')
        self.submit(work,done)
    def close(self):
        if self.closing:return
        # Serialize video cleanup before Window's existing session cleanup.
        self.tasks.put((self.video.close,None))
        super().close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device',required=True);parser.add_argument('--package',required=True,type=p.package_name)
    parser.add_argument('--server-jar',required=True);parser.add_argument('--adb',default='adb')
    parser.add_argument('--server',default='http://127.0.0.1:4723');parser.add_argument('--output',default='outputs')
    parser.add_argument('--session-create-timeout',type=int,default=90);parser.add_argument('--allow-coordinates',action='store_true')
    args=parser.parse_args();root=tk.Tk();root.title('P1 continuous mirror');root.update()
    if not messagebox.askyesno('Whole-device video','Start continuous whole-device video in RAM? Other apps and notifications may appear. Only authorized selected-app input during RECORD is dispatched and stored. No audio or video file recording.',parent=root):root.destroy();return
    MirrorWindow(root,args);root.mainloop()

if __name__=='__main__':main()
