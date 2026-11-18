"""Opt-in disposable Android app smoke. No global proxy or trust-store changes."""
import argparse,asyncio,base64,json,re,ssl,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay import Config,Relay,query
from websocket_relay import read_frame
from websockets.frames import Frame,OP_CLOSE
PACKAGE='dev.finsec.qa.network'

async def main(args):
    args.output.mkdir(parents=True,exist_ok=True)
    async def adb(*command,check=True):
        proc=await asyncio.create_subprocess_exec(args.adb,'-s',args.device,*command,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:out,err=await asyncio.wait_for(proc.communicate(),20)
        except BaseException:
            proc.kill();await proc.communicate();raise
        if check and proc.returncode:raise RuntimeError('ADB operation failed: '+command[0])
        return out
    assert (await adb('shell','pm','path',PACKAGE)).startswith(b'package:'),'Install the dedicated QA APK first'
    results=[]
    for protocol in ('http','https','ws','wss'):
        tls=protocol in ('https','wss');ws=protocol in ('ws','wss');tasks=set();received=[]
        if args.untrusted_listener and not tls:continue
        listener_pki=args.untrusted_listener or args.pki
        context=None
        if tls:
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(args.pki/'server.pem',args.pki/'server.key')
        async def upstream(reader,writer):
            task=asyncio.current_task();tasks.add(task)
            try:
                head=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),5)
                token=head.split(b' ')[1].split(b'/')[-1].decode('ascii')
                assert re.fullmatch('qa-[a-z0-9-]{1,60}',token);received.append(token)
                if ws:
                    writer.write(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: 7sbntUgfmFlpglBJP/c9zZsZnL4=\r\n\r\n');await writer.drain()
                    while True:
                        frame,raw=await read_frame(reader,masked=True,maximum=125,idle_timeout=5,io_timeout=3)
                        writer.write(Frame(frame.opcode,frame.data,fin=frame.fin).serialize(mask=False));await writer.drain()
                        if frame.opcode==OP_CLOSE:break
                else:
                    body=token.encode();writer.write(b'HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body);await writer.drain()
            finally:
                writer.close()
                try:await writer.wait_closed()
                except OSError:pass
                tasks.discard(task)
        server=await asyncio.start_server(upstream,'127.0.0.1',0,ssl=context)
        db=args.output/(protocol+'-'+uuid.uuid4().hex+'.sqlite3')
        config=Config(db=db,upstream_port=server.sockets[0].getsockname()[1],enable_websocket=ws,
            listener_cert=listener_pki/'server.pem' if tls else None,listener_key=listener_pki/'server.key' if tls else None,
            upstream_tls=tls,upstream_ca=args.pki/'assets/qa-ca.pem' if tls else None,io_timeout=5)
        relay=Relay(config);reverse=None
        async def command(name,**extra):
            result=await relay.command(dict(schema_version=1,command_id=uuid.uuid4().hex,command=name,**extra))
            assert result['ok'],result
            return result['result']
        async def invoke(token,expect_failure=False):
            # Only this newly created disposable app is stopped; no pm clear or other app data is touched.
            await adb('shell','am','force-stop',PACKAGE)
            await adb('shell','am','start','-n',PACKAGE+'/.MainActivity','--es','protocol',protocol,'--ei','port',reverse,'--es','token',token)
            for attempt in range(60):
                raw=await adb('exec-out','run-as',PACKAGE,'cat','files/receipt.json',check=False)
                try:receipt=json.loads(raw)
                except (ValueError,UnicodeError):receipt={}
                if receipt.get('token')==token:
                    if expect_failure:
                        assert receipt.get('status')=='failed' and receipt.get('error')=='SSLHandshakeException',receipt
                    else:
                        assert receipt.get('status')=='succeeded',receipt
                        assert receipt['echo']==token
                    return receipt
                await asyncio.sleep(.2)
            raise TimeoutError('QA receipt did not arrive')
        try:
            await relay.start();on=await command('ON')
            reverse=(await adb('reverse','tcp:0','tcp:'+str(on['listen_port']))).decode().strip();assert reverse.isdigit()
            prefix='qa-'+uuid.uuid4().hex[:12]
            pre=prefix+'-pre';post=prefix+'-post'
            if args.untrusted_listener:
                rec=await command('RECORD',device_id='authorized-disposable-device',app_id=PACKAGE)
                receipt=await invoke(prefix+'-reject',expect_failure=True)
                stopped=await command('STOP')
                assert query(db,'packets',recording_id=rec['recording_id'])['result']==[]
                assert received==[]
                result=dict(protocol=protocol,status='untrusted_certificate_rejected',app_error=receipt['error'],upstream_requests=0,stored_rows=0)
                results.append(result);print(json.dumps(result),flush=True)
                continue
            await invoke(pre)
            rec=await command('RECORD',device_id='authorized-disposable-device',app_id=PACKAGE)
            tokens=[prefix+'-'+str(i) for i in range(3)]
            receipts=[await invoke(token) for token in tokens]
            stopped=await command('STOP');assert stopped['network_coverage']=='complete_for_supported_scope',stopped
            before=query(db,'packets',recording_id=rec['recording_id'],limit=100)['result']
            await invoke(post)
            after=query(db,'packets',recording_id=rec['recording_id'],limit=100)['result'];assert before==after
            details=[query(db,'detail',packet_id=row['packet_id'])['result'] for row in before]
            handshakes=[d for d in details if d['kind']=='websocket_handshake'] if ws else details
            assert len(handshakes)==3,(protocol,len(handshakes))
            raw=b'\n'.join(base64.b64decode(d[direction]['raw_base64']) for d in details for direction in ('request','response') if d.get(direction))
            for token in tokens:assert token.encode() in raw
            assert pre.encode() not in raw and post.encode() not in raw
            assert received==[pre,*tokens,post],received
            result=dict(protocol=protocol,status='succeeded',app_receipts=len(receipts),captured_transactions=len(handshakes),stored_rows=len(details),record_boundary='pre/post excluded',attribution='correlated disposable fixture, not general OS attribution')
            results.append(result);print(json.dumps(result),flush=True)
            (args.output/(protocol+'-receipts.json')).write_text(json.dumps(receipts,indent=2))
        finally:
            if reverse:await adb('reverse','--remove','tcp:'+reverse)
            await relay.close();server.close();await server.wait_closed()
            for task in list(tasks):task.cancel()
            if tasks:await asyncio.gather(*tasks,return_exceptions=True)
    (args.output/'summary.json').write_text(json.dumps(results,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb',default='adb');parser.add_argument('--device',required=True)
    parser.add_argument('--pki',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--untrusted-listener',type=Path,help='Optional distinct generated PKI: expect HTTPS/WSS certificate rejection')
    asyncio.run(main(parser.parse_args()))
