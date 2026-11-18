"""QA-only integrated GUI. P2 runs independently on an owned asyncio loop."""
import argparse,asyncio,pathlib,sys,threading,uuid,re,subprocess,tkinter as tk
from tkinter import messagebox,ttk
from .mirror import MirrorWindow
from .combined import CombinedRun

class Network:
    def __init__(self,output):
        sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'p2-proxy-relay'))
        from relay import Config,Relay
        self.loop=asyncio.new_event_loop();self.thread=threading.Thread(target=self.loop.run_forever,daemon=True);self.thread.start()
        self.tasks=set()
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
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\nContent-Length: '+str(len(token)).encode()+b'\r\n\r\n'+token);await writer.drain()
                except (OSError,ValueError,TimeoutError,asyncio.IncompleteReadError):pass
                finally:
                    writer.close()
                    try:await writer.wait_closed()
                    except OSError:pass
                    self.tasks.discard(task)
            self.server=await asyncio.start_server(echo,'127.0.0.1',0)
            self.db=pathlib.Path(output)/('network-'+uuid.uuid4().hex+'.sqlite3')
            self.relay=Relay(Config(db=self.db,upstream_port=self.server.sockets[0].getsockname()[1]))
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
        super().__init__(root,args)
        self.sync=CombinedRun(self.engine,network,args.output)
        self.engine.start=self.sync.start;self.engine.finish=self.sync.finish
        root.title('Finsec P1 + P2 - COMBINED QA RECORDING')
        self.postid.set('dev.finsec.qa.network:id/state');self.posttext.set('ready')
        self.sync_status=tk.StringVar();ttk.Label(self.post_selector.master,textvariable=self.sync_status,wraplength=300).pack()
        self.sync_tick()
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
    def replay(self):self.status.set('Combined replay is not implemented; use standalone P1 replay explicitly')
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
                    if hasattr(self,'reverse'):subprocess.run([self.args.adb,'-s',self.args.device,'reverse','--remove','tcp:'+self.reverse],check=True,capture_output=True,timeout=10)
        self.tasks.put((cleanup_network,None));super().close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device',required=True);parser.add_argument('--adb',default='adb');parser.add_argument('--server-jar',required=True)
    parser.add_argument('--server',default='http://127.0.0.1:4723');parser.add_argument('--output',default='outputs')
    args=parser.parse_args();args.package='dev.finsec.qa.network';args.allow_coordinates=True;args.session_create_timeout=90
    pathlib.Path(args.output).mkdir(parents=True,exist_ok=True)
    root=tk.Tk()
    if not messagebox.askyesno('Combined QA fixture','Start whole-device video and the disposable QA HTTP loopback fixture? Input requires an approved Appium session. No global proxy or CA is changed.',parent=root):root.destroy();return
    network=Network(args.output);window=CombinedWindow(root,args,network)
    reverse=subprocess.check_output([args.adb,'-s',args.device,'reverse','tcp:0','tcp:'+str(network.port)],text=True).strip()
    if not reverse.isdigit():raise RuntimeError('No owned reverse port')
    window.reverse=reverse
    subprocess.run([args.adb,'-s',args.device,'shell','am','start','-S','-n',args.package+'/.MainActivity','--es','protocol','http','--ei','port',reverse,'--es','token','qa-'+uuid.uuid4().hex[:12],'--ez','interactive','true'],check=True,capture_output=True,timeout=15)
    root.mainloop()

if __name__=='__main__':main()
