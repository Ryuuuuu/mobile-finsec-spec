"""Ollama /api/generate transport preparation, not enabled in Supervisor.

Only numeric IPv4 loopback, bounded HTTP/1.1 Content-Length JSON, no auth,
proxy environment, redirects, automatic retries or remote cancellation claims.
"""
import asyncio
import json
import math
import re


class LocalOllama:
    def __init__(self, port, timeout=2.0):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('INVALID_PORT')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0.01 <= timeout <= 60:
            raise ValueError('INVALID_TIMEOUT')
        self.port, self.timeout = port, timeout
        self.busy = False
        self.recovery_required = False

    def capabilities(self):
        return dict(provider='ollama-loopback-preparation', streaming=False,
                    cancellation=False, resume=False, tool_execution=False,
                    supervisor_enabled=False, local_transport_only=True)

    async def generate(self, model, prompt):
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', model) or 'cloud' in model.lower():
            raise ValueError('INVALID_LOCAL_MODEL')
        if not isinstance(prompt, str) or len(prompt.encode('utf-8')) > 8192:
            raise ValueError('INVALID_PROMPT')
        if self.busy or self.recovery_required:
            return dict(status='not_run', reason='BUSY_OR_RECOVERY_REQUIRED', retry_allowed=False)
        self.busy = True
        writer = None
        submitted = False
        result = dict(status='unknown', reason='TRANSPORT_UNCERTAIN', retry_allowed=False)
        try:
            async with asyncio.timeout(self.timeout):
                reader, writer = await asyncio.open_connection('127.0.0.1', self.port, limit=16384)
                body = json.dumps(dict(model=model, prompt=prompt, stream=False, format='json')).encode()
                header = (f'POST /api/generate HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n'
                          f'Content-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n').encode()
                submitted = True
                writer.write(header + body)
                await writer.drain()
                raw = await reader.readuntil(b'\r\n\r\n')
                if len(raw) > 8192:
                    raise ValueError('HEADER_LIMIT')
                lines = raw.decode('ascii').split('\r\n')
                if not re.fullmatch(r'HTTP/1\.[01] 200(?: .*)?', lines[0]):
                    raise ValueError('HTTP_STATUS')
                headers = {}
                for line in lines[1:-2]:
                    key, value = line.split(':', 1); key = key.lower()
                    if key in headers:
                        raise ValueError('DUPLICATE_HEADER')
                    headers[key] = value.strip()
                if 'transfer-encoding' in headers:
                    raise ValueError('UNSUPPORTED_TRANSFER_ENCODING')
                length = headers.get('content-length', '')
                if not length.isdigit() or not 0 < int(length) <= 65536:
                    raise ValueError('BODY_LIMIT')
                if headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                    raise ValueError('CONTENT_TYPE')
                data = await reader.readexactly(int(length))
                def unique(pairs):
                    output = {}
                    for k, v in pairs:
                        if k in output: raise ValueError('DUPLICATE_JSON')
                        output[k] = v
                    return output
                response = json.loads(data, object_pairs_hook=unique,
                                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
                if (not isinstance(response, dict) or response.get('done') is not True
                        or response.get('model') != model or not isinstance(response.get('response'), str)):
                    raise ValueError('INVALID_RESPONSE')
                proposal = json.loads(response['response'], object_pairs_hook=unique,
                                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
                if not isinstance(proposal, dict): raise ValueError('INVALID_PROPOSAL')
                # Proposal is untrusted data, never a tool invocation or security verdict.
                result = dict(status='completed', reason='RESPONSE_RECEIVED', proposal=proposal, retry_allowed=False)
        except asyncio.CancelledError:
            result = dict(status='unknown' if submitted else 'not_run', reason='CANCEL_LOCAL_ONLY', retry_allowed=False)
        except TimeoutError:
            result = dict(status='unknown' if submitted else 'not_run', reason='TIMEOUT', retry_allowed=False)
        except (OSError, ValueError, UnicodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, RecursionError):
            result = dict(status='unknown' if submitted else 'not_run', reason='TRANSPORT_OR_PROTOCOL_ERROR', retry_allowed=False)
        finally:
            if writer is not None:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), 0.1)
                except (TimeoutError, OSError, asyncio.CancelledError):
                    pass
            self.busy = False
            if submitted and result['status'] != 'completed':
                self.recovery_required = True
        result['remote_termination'] = 'unconfirmed' if self.recovery_required else 'not_claimed'
        result['recovery_required'] = self.recovery_required
        return result
