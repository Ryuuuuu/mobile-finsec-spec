import asyncio,json,unittest
from integration.ollama_http import LocalOllama

class LocalHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests=[];self.mode='normal';self.tasks=set()
        self.accepted=asyncio.Event();self.release=asyncio.Event()
        self.server=await asyncio.start_server(self.handle,'127.0.0.1',0)
        self.port=self.server.sockets[0].getsockname()[1]
    async def asyncTearDown(self):
        self.release.set();self.server.close();await asyncio.wait_for(self.server.wait_closed(),2)
        if self.tasks:await asyncio.wait_for(asyncio.gather(*self.tasks,return_exceptions=True),2)
    async def handle(self,reader,writer):
        task=asyncio.current_task();self.tasks.add(task)
        try:
            header=await reader.readuntil(b'\r\n\r\n')
            length=int(next(x.split(b':')[1] for x in header.split(b'\r\n') if x.lower().startswith(b'content-length:')))
            body=await reader.readexactly(length)
            self.requests.append((header,json.loads(body)));self.accepted.set()
            if self.mode=='hang':await self.release.wait()
            data=dict(model='qa-local',done=True,response=json.dumps({'selected_items':['synthetic-item']}))
            if self.mode=='not_done':data['done']=False
            if self.mode=='wrong_model':data['model']='other'
            if self.mode=='bad_proposal':data['response']='PRIVATE_MODEL_TEXT'
            if self.mode=='nonfinite':data['response']='{"value":NaN}'
            if self.mode=='duplicate':data['response']='{"value":1,"value":2}'
            payload=json.dumps(data).encode();status='200 OK'
            if self.mode=='redirect':status='302 Found'
            if self.mode=='error':status='500 Error'
            if self.mode=='malformed':payload=b'PRIVATE_INVALID_JSON'
            if self.mode=='oversize':payload=b'x'*65537
            extra=b'Transfer-Encoding: chunked\r\n' if self.mode=='chunked' else b''
            writer.write(f'HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\n'.encode()+extra+b'\r\n'+(payload[:2] if self.mode=='truncated' else payload))
            await writer.drain()
        except (OSError,asyncio.IncompleteReadError):pass
        finally:
            writer.close()
            try:await writer.wait_closed()
            except OSError:pass
            self.tasks.discard(task)
    async def test_request_and_untrusted_result(self):
        client=LocalOllama(self.port)
        result=await client.generate('qa-local','SYNTHETIC PROMPT')
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['proposal'],{'selected_items':['synthetic-item']})
        header,request=self.requests[0]
        self.assertTrue(header.startswith(b'POST /api/generate HTTP/1.1'))
        self.assertNotIn(b'Authorization',header)
        self.assertEqual(request,dict(model='qa-local',prompt='SYNTHETIC PROMPT',stream=False,format='json'))
        self.assertFalse(client.capabilities()['supervisor_enabled'])
        self.assertFalse(client.capabilities()['cancellation'])
    async def test_failures_are_redacted_and_not_retried(self):
        for mode in ('not_done','wrong_model','bad_proposal','redirect','error','malformed','oversize','chunked','truncated','nonfinite','duplicate'):
            with self.subTest(mode=mode):
                self.mode=mode;client=LocalOllama(self.port);count=len(self.requests)
                result=await client.generate('qa-local','SYNTHETIC')
                self.assertEqual(result['status'],'unknown');self.assertTrue(result['recovery_required'])
                self.assertNotIn('PRIVATE',json.dumps(result))
                self.assertEqual((await client.generate('qa-local','SYNTHETIC'))['status'],'not_run')
                self.assertEqual(len(self.requests),count+1)
    async def test_timeout_uncertainty(self):
        self.mode='hang';client=LocalOllama(self.port,timeout=0.05)
        result=await client.generate('qa-local','SYNTHETIC')
        self.assertEqual(result['reason'],'TIMEOUT')
        self.assertEqual(result['remote_termination'],'unconfirmed')
        self.release.set();self.assertTrue(client.recovery_required)
    async def test_cancel_local_only_and_busy(self):
        self.mode='hang';client=LocalOllama(self.port)
        task=asyncio.create_task(client.generate('qa-local','SYNTHETIC'))
        await asyncio.wait_for(self.accepted.wait(),1)
        self.assertEqual((await client.generate('qa-local','SYNTHETIC'))['status'],'not_run')
        task.cancel();result=await task
        self.assertEqual(result['reason'],'CANCEL_LOCAL_ONLY')
        self.assertEqual(result['remote_termination'],'unconfirmed')
        self.assertEqual(len(self.requests),1)
    async def test_invalid_configuration_no_request(self):
        for port in (True,0,65536,'remote.example'):
            with self.assertRaises(ValueError):LocalOllama(port)
        client=LocalOllama(self.port)
        for model in ('cloud-model','../escape','x\r\nAuth:secret'):
            with self.assertRaises(ValueError):await client.generate(model,'SYNTHETIC')
        with self.assertRaises(ValueError):await client.generate('qa-local','x'*8193)
        self.assertEqual(self.requests,[])

    async def test_connection_refused_is_not_submission(self):
        self.server.close();await asyncio.wait_for(self.server.wait_closed(),2)
        client=LocalOllama(self.port)
        result=await client.generate('qa-local','SYNTHETIC')
        self.assertEqual(result['status'],'not_run')
        self.assertFalse(result['recovery_required'])
        self.assertEqual(self.requests,[])
