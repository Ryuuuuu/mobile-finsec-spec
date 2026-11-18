"""Minimal synthetic UI HTTP adapter. Loopback only; no device/model backend."""
import asyncio
import hmac
import json
import re
import secrets
from .ui_wire import LIMIT


class LoopbackAPI:
    def __init__(self, wire):
        self.wire = wire
        self.server = None
        self.token = None
        self.tasks = set()

    async def start(self):
        if self.server is not None: raise RuntimeError('ALREADY_STARTED')
        self.token = secrets.token_urlsafe(32)
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0, limit=8192)
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port  # Credential is memory-only, not printed or put in URLs.

    async def close(self):
        if self.server is None: return
        server = self.server
        server.close()
        self.server = None
        self.token = None
        pending = list(self.tasks)
        for task in pending: task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await server.wait_closed()
        # Transport shutdown does not cancel/reconcile already admitted API jobs.

    async def handle(self, reader, writer):
        # An accepted socket callback can start after close() took its task snapshot.
        if self.server is None:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, TimeoutError): pass
            return
        task = asyncio.current_task(); self.tasks.add(task)
        request_id = None
        dispatched = False
        async def respond(code, payload):
            body = json.dumps(dict(contract='mock-loopback.v1', request_id=request_id,
                                   payload=payload), allow_nan=False).encode()
            writer.write(f'HTTP/1.1 {code} Response\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n'.encode() + body)
            await asyncio.wait_for(writer.drain(), 1)
        try:
            raw = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 1)
            lines = raw.decode('ascii').split('\r\n')
            if lines[0] != 'POST /v1/ui HTTP/1.1':
                await respond(400, {'error':'UNSUPPORTED_REQUEST','outcome':'not_dispatched'}); return
            headers = {}
            for line in lines[1:-2]:
                name, value = line.split(':', 1)
                name = name.lower()
                if not re.fullmatch(r'[a-z0-9-]+', name) or name in headers: raise ValueError('HEADER')
                headers[name] = value.strip()
            if headers.get('host') != f'127.0.0.1:{self.port}' or 'origin' in headers:
                await respond(403, {'error':'ORIGIN_OR_HOST','outcome':'not_dispatched'}); return
            supplied = headers.get('authorization', '')
            if not self.token or not hmac.compare_digest(supplied, 'Bearer ' + self.token):
                await respond(401, {'error':'UNAUTHORIZED','outcome':'not_dispatched'}); return
            correlation = headers.get('x-request-id', '')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', correlation): raise ValueError('REQUEST_ID')
            request_id = correlation
            if headers.get('x-api-version') != 'mock-loopback.v1':
                await respond(400, {'error':'UNSUPPORTED_VERSION','outcome':'not_dispatched'}); return
            if 'transfer-encoding' in headers or headers.get('content-type') != 'application/json':
                raise ValueError('FRAMING')
            length = headers.get('content-length', '')
            if not re.fullmatch(r'[0-9]{1,9}', length): raise ValueError('LENGTH')
            if int(length) > LIMIT:
                await respond(413, {'error':'REQUEST_LIMIT','outcome':'not_dispatched'}); return
            body = await asyncio.wait_for(reader.readexactly(int(length)), 1)
            dispatched = True
            reply = json.loads(self.wire.exchange(body))
            await respond(200, reply)
        except (ValueError, UnicodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            try:
                await respond(400, {'error':'INVALID_OR_INCOMPLETE_REQUEST',
                                   'outcome':'unknown' if dispatched else 'not_dispatched'})
            except (OSError, TimeoutError): pass
        except (OSError, RuntimeError):
            # Do not echo internal errors, headers, credential, or request contents.
            pass
        finally:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, TimeoutError): pass
            self.tasks.discard(task)
