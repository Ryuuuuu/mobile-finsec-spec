"""QA-only integrated GUI. P2 runs independently on an owned asyncio loop."""
import argparse,asyncio,pathlib,sys,threading,uuid,re,ssl,hashlib,base64,subprocess,tkinter as tk
from tkinter import messagebox,ttk
from .mirror import MirrorWindow
from .combined import CombinedRun

class Network:
    def __init__(self,output,pki=None,websocket=False):
        sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'p2-proxy-relay'))
        from relay import Config,Relay
        self.loop=asyncio.new_event_loop();self.thread=threading.Thread(target=self.loop.run_forever,daemon=True);self.thread.start()
        self.tasks=set()
        context=None
        if pki:
            pki=pathlib.Path(pki)
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(pki/'server.pem',pki/'server.key')
        if websocket:
            from websocket_relay import read_frame
            from websockets.frames import Frame,OP_CLOSE
        async def setup():
            async def echo(reader,writer):
                task=asyncio.current_task();self.tasks.add(task)
                try:
                    head=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),3)
                    path=head.split(b' ')[1]
                    if path==b'/favicon.ico':
                        writer.write(b'HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n');await writer.drain();return
                    token=path.split(b'/')[-1]
                    if not re.fullmatch(rb'qa-[a-z0-9-]{1,60}',token):raise ValueError('Fixture token required')
                    if websocket:
                        headers=dict(line.split(b':',1) for line in head.split(b'\r\n')[1:] if b':' in line)
                        key=next((v.strip() for k,v in headers.items() if k.lower()==b'sec-websocket-key'),b'')
                        if len(base64.b64decode(key,validate=True))!=16:raise ValueError('Invalid fixture handshake')
                        accept=base64.b64encode(hashlib.sha1(key+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
                        writer.write(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+b'\r\n\r\n');await writer.drain()
                        while True:
                            frame,raw=await read_frame(reader,masked=True,maximum=125,idle_timeout=5,io_timeout=3)
                            writer.write(Frame(frame.opcode,frame.data,fin=frame.fin).serialize(mask=False));await writer.drain()
                            if frame.opcode==OP_CLOSE:break
                        return
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\nContent-Length: '+str(len(token)).encode()+b'\r\n\r\n'+token);await writer.drain()
                except (OSError,ValueError,TimeoutError,asyncio.IncompleteReadError):pass
                finally:
                    writer.close()
                    try:await writer.wait_closed()
                    except OSError:pass
                    self.tasks.discard(task)
            self.server=await asyncio.start_server(echo,'127.0.0.1',0,ssl=context)
            self.db=pathlib.Path(output)/('network-'+uuid.uuid4().hex+'.sqlite3')
            self.relay=Relay(Config(db=self.db,upstream_port=self.server.sockets[0].getsockname()[1],enable_websocket=websocket,
                listener_cert=pki/'server.pem' if pki else None,listener_key=pki/'server.key' if pki else None,
                upstream_tls=bool(pki),upstream_ca=pki/'assets/qa-ca.pem' if pki else None))
            await self.relay.start()
            return await self.relay.command(dict(schema_version=1,command_id=uuid.uuid4().hex,command='ON'))
        result=asyncio.run_coroutine_threadsafe(setup(),self.loop).result(15)
        if not result['ok']:raise RuntimeError('Network setup failed')
        self.port=result['result']['listen_port']
    def command(self,name,**extra):
        result=asyncio.run_coroutine_threadsafe(self.relay.command(dict(schema_version=1,command_id=uuid.uuid4().hex,command=name,**extra)),self.loop).result(15)
        if not result['ok']:raise RuntimeError('Network command failed: '+str(result.get('error')))
        return result['result']
    def close(self):
        async def shutdown():
            await self.relay.close();self.server.close();await self.server.wait_closed()
            for task in list(self.tasks):task.cancel()
            if self.tasks:await asyncio.gather(*self.tasks,return_exceptions=True)
        try:asyncio.run_coroutine_threadsafe(shutdown(),self.loop).result(15)
        finally:self.loop.call_soon_threadsafe(self.loop.stop);self.thread.join(5)

class CombinedWindow(MirrorWindow):
    def __init__(self,root,args,network):
        self.network=network;self.sync=None;self.abort_pending=False
        from device_resources import Reservation
        self.reservation=Reservation(args.device)
        try:self.reservation.acquire()
        except Exception:network.close();raise
        args.device_lease=self.reservation
        try:super().__init__(root,args)
        except Exception:
            self.reservation.poison('Combined GUI initialization failed; verify owned resources');self.reservation.end();network.close();raise
        self.sync=CombinedRun(self.engine,network,args.output)
        self.engine.start=self.sync.start;self.engine.finish=self.sync.finish;self.engine.replay=self.sync.replay
        root.title('Finsec P1 + P2 - COMBINED QA RECORDING')
        self.postid.set('dev.finsec.qa.network:id/state');self.posttext.set('ready')
        self.sync_status=tk.StringVar();ttk.Label(self.post_selector.master,textvariable=self.sync_status,wraplength=300).pack()
        self.sync_tick()
    def prepare_fixture(self,protocol):
        from device_resources import OwnedReverse
        self.reverse_mapping=OwnedReverse(self.args.adb,self.args.device,self.network.port)
        try:
            self.reverse=self.reverse_mapping.allocate()
            self.reverse_mapping.verify()
            self.sync.preflight=self.reverse_mapping.verify
            self.fixture_token='qa-'+uuid.uuid4().hex[:12]
            subprocess.run([self.args.adb,'-s',self.args.device,'shell','am','start','-S','-n',self.args.package+'/.MainActivity','--es','protocol',protocol,'--ei','port',self.reverse,'--es','token',self.fixture_token,'--ez','interactive','true'],check=True,capture_output=True,timeout=15)
        except Exception:
            self.reservation.poison('Fixture startup failed; verify owned reverse mapping');raise
    def sync_tick(self):
        if self.closing:return
        self.sync_status.set('Combined recording: '+self.sync.state+'\nInput/network IDs are linked in local combined.json')
        self.root.after(100,self.sync_tick)
    def stop(self):
        if self.sync.state=='starting':
            self.engine.stop_requested();self.status.set('STOP requested during start; input remains blocked');return
        if self.sync.state=='active':self.sync.j.write('stop_requested')
        super().stop()
    def input(self,action):
        if self.sync.state!='active':self.status.set('Both recorders must acknowledge start');return
        super().input(action)
    def text_input(self):
        if self.sync.state!='active':self.status.set('Both recorders must acknowledge start');return
        super().text_input()
    def replay(self):super().replay()
    def abort(self,reason):
        super().abort(reason)
        if self.sync and self.sync.state not in ('idle','completed','partial') and not self.abort_pending:
            self.abort_pending=True
            def work():
                try:self.sync.abort(reason)
                finally:self.abort_pending=False
            self.tasks.put((work,None))
    def close(self):
        if self.closing:return
        def cleanup_network():
            try:
                self.sync.abort('Window closed')
            finally:
                try:self.network.close()
                finally:
                    try:
                        if hasattr(self,'reverse_mapping'):self.reverse_mapping.close()
                    except Exception:
                        self.reservation.poison('Owned reverse cleanup not confirmed');raise
        self.tasks.put((cleanup_network,None));super().close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device',required=True);parser.add_argument('--adb',default='adb');parser.add_argument('--server-jar',required=True)
    parser.add_argument('--server',default='http://127.0.0.1:4723');parser.add_argument('--output',default='outputs')
    parser.add_argument('--protocol',choices=('http','https','ws','wss','okhttp-http','okhttp-https'),default='http')
    parser.add_argument('--pki',type=pathlib.Path,help='Private matching QA PKI; required for TLS')
    args=parser.parse_args();args.package='dev.finsec.qa.network';args.allow_coordinates=True;args.session_create_timeout=90
    if args.protocol in ('https','wss','okhttp-https') and not args.pki:parser.error('TLS requires private matching --pki')
    pathlib.Path(args.output).mkdir(parents=True,exist_ok=True)
    root=tk.Tk()
    if not messagebox.askyesno('Combined QA fixture','Start whole-device video and the disposable QA loopback fixture? Input requires an approved Appium session. No global proxy or CA is changed.',parent=root):root.destroy();return
    network=Network(args.output,args.pki if args.protocol in ('https','wss','okhttp-https') else None,args.protocol in ('ws','wss'));window=CombinedWindow(root,args,network)
    try:window.prepare_fixture(args.protocol)
    except Exception:
        window.close();root.mainloop();raise
    root.mainloop()

if __name__=='__main__':main()
