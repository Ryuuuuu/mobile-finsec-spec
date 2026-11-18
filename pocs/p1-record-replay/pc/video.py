"""Video-only client for the pinned, unmodified scrcpy 5.0.1 server.

No control/audio sockets, implicit recording, capture bypass or settings writes.
Protocol reference: https://github.com/Genymobile/scrcpy/tree/v5.0.1
"""
import hashlib
import pathlib
import re
import secrets
import socket
import struct
import subprocess
import threading
import time

SERVER_SHA256='764eb6f79811d5211fe9df341120882ba9994c7a61b897d7bf3fb662e53bc536'

def header(data):
    if len(data)!=12:raise ValueError('Truncated packet header')
    flags,width,height=struct.unpack('>III',data)
    if flags & 0x80000000:
        if not 1<=width<=10000 or not 1<=height<=10000:raise ValueError('Invalid video dimensions')
        return ('session',width,height)
    pts,size=struct.unpack('>QI',data)
    if not 0<size<=16*1024*1024:raise ValueError('Invalid video packet size')
    return ('media',pts,size)

def recv_exact(sock,count,stop=None):
    data=bytearray()
    while len(data)<count:
        try:chunk=sock.recv(count-len(data))
        except socket.timeout:
            if stop is None or stop.is_set():raise
            continue # Static surfaces need not produce packets; keep partial bytes.
        if not chunk:raise EOFError('Video disconnected')
        data.extend(chunk)
    return bytes(data)

class Video:
    def __init__(self,device,server,adb='adb'):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',device):raise ValueError('Invalid device')
        if hashlib.sha256(pathlib.Path(server).read_bytes()).hexdigest()!=SERVER_SHA256:
            raise ValueError('Expected official scrcpy 5.0.1 server hash')
        self.device=device;self.server=str(server);self.adb=adb
        self.stop_event=threading.Event();self.lock=threading.Lock();self.latest=None
        self.error=None;self.generation=0;self.sock=None;self.port=None;self.process=None
        self.scid=secrets.randbelow(0x7fffffff);self.remote='/data/local/tmp/p1-video-%08x.jar'%self.scid
        self.thread=None
        self.phase='created'
    def command(self,*args):
        return [self.adb,'-s',self.device,*args]
    def run(self,*args):
        return subprocess.check_output(self.command(*args),stderr=subprocess.DEVNULL,timeout=15,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).decode().strip()
    def start(self):
        if self.thread:raise RuntimeError('Create a new Video after disconnect')
        self.thread=threading.Thread(target=self.receive,daemon=True);self.thread.start()
    def snapshot(self):
        with self.lock:return self.latest,self.error,self.generation
    def receive(self):
        try:
            import av
            self.phase='pushing server'
            self.run('push',self.server,self.remote)
            self.phase='forwarding video'
            self.port=int(self.run('forward','tcp:0','localabstract:scrcpy_%08x'%self.scid))
            self.process=subprocess.Popen(self.command('shell','CLASSPATH='+self.remote,'app_process','/',
                'com.genymobile.scrcpy.Server','5.0.1','scid=%08x'%self.scid,'tunnel_forward=true',
                'audio=false','control=false','send_device_meta=false','video_codec=h264',
                'cleanup=false','log_level=warn'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            deadline=time.monotonic()+15
            self.phase='connecting video'
            while not self.stop_event.is_set():
                try:
                    self.sock=socket.create_connection(('127.0.0.1',self.port),timeout=2)
                    if recv_exact(self.sock,1)!=b'\0':raise ValueError('Invalid server greeting')
                    break
                except (OSError,EOFError):
                    if self.sock:self.sock.close()
                    if time.monotonic()>=deadline:raise TimeoutError('Video startup timeout')
                    self.stop_event.wait(.15)
            if self.stop_event.is_set():return
            # Encoder startup can outlast a normal frame interval; UI freshness
            # remains independently bounded and never permits input while waiting.
            self.sock.settimeout(30)
            if recv_exact(self.sock,4)!=b'h264':raise ValueError('Expected H.264 stream')
            self.phase='decoding video'
            decoder=None;config=b'';dimensions=None
            while not self.stop_event.is_set():
                kind,first,second=header(recv_exact(self.sock,12,self.stop_event))
                if kind=='session':
                    dimensions=(first,second);decoder=av.CodecContext.create('h264','r');config=b''
                    with self.lock:self.generation+=1;self.latest=None
                    continue
                if decoder is None:raise ValueError('Missing video session metadata')
                packet=recv_exact(self.sock,second,self.stop_event)
                if first & (1<<62):config=packet;continue
                for frame in decoder.decode(av.Packet(config+packet)):
                    config=b''
                    if (frame.width,frame.height)!=dimensions:raise ValueError('Decoded dimensions mismatch')
                    decoded={'image':frame.to_image(),'at':time.monotonic(),'generation':self.generation,'size':dimensions}
                    with self.lock:self.latest=decoded
        except Exception as error:
            with self.lock:self.error=type(error).__name__+': video unavailable';self.latest=None
        finally:
            if self.sock:self.sock.close()
            if self.process:
                try:self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=3)
            if self.port:
                try:self.run('forward','--remove','tcp:'+str(self.port))
                except (OSError,subprocess.SubprocessError):pass
            try:self.run('shell','rm','-f',self.remote)
            except (OSError,subprocess.SubprocessError):pass
    def close(self):
        self.stop_event.set()
        if self.sock:
            try:self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        if self.thread:self.thread.join(timeout=20)
        if self.thread and self.thread.is_alive():raise RuntimeError('Video cleanup not confirmed')
