"""Python reference launcher, not a GPUI integration. Never log ready/token."""
import http.client
import json
import re
import sys
from uuid import uuid4
from .stdio_client import StdioClient, UnknownOutcome
from .ui_wire import LIMIT


class HTTPChild(StdioClient):
    def __init__(self, root, *, timeout=3, argv=None):
        # Optional argv is a trusted test launcher input, not a wire/model field.
        super().__init__(argv or [sys.executable, '-m', 'integration.mock_http_child',
                                 '--mock-root', str(root)], timeout=timeout)

    def valid_handshake(self, ready):
        return (set(ready) == {'contract','synthetic','host','port','token','project_id'}
                and ready['contract'] == 'mock-http-child.v1' and ready['synthetic'] is True
                and ready['host'] == '127.0.0.1' and type(ready['port']) is int
                and 0 < ready['port'] < 65536 and ready['project_id'] == 'synthetic-http'
                and isinstance(ready['token'],str) and re.fullmatch(r'[A-Za-z0-9_-]{43}',ready['token']) is not None)

    def exchange(self, request):
        body = json.dumps(request, allow_nan=False).encode()
        if len(body) > LIMIT: raise ValueError('REQUEST_LIMIT')
        if not self.lock.acquire(blocking=False): raise RuntimeError('REQUEST_IN_PROGRESS')
        connection = None
        try:
            if self.closed or self.uncertain: raise UnknownOutcome('CHANNEL_UNUSABLE')
            correlation = uuid4().hex
            connection = http.client.HTTPConnection('127.0.0.1',self.ready['port'],timeout=self.timeout)
            connection.request('POST','/v1/ui',body,headers={
                'Authorization':'Bearer '+self.ready['token'], 'Content-Type':'application/json',
                'X-API-Version':'mock-loopback.v1','X-Request-ID':correlation})
            response = connection.getresponse()
            raw = response.read(LIMIT+1025)
            if len(raw)>LIMIT+1024: raise ValueError('RESPONSE_LIMIT')
            data = json.loads(raw)
            if not isinstance(data,dict) or response.status!=200 or data.get('contract')!='mock-loopback.v1' or data.get('request_id')!=correlation:
                raise ValueError('RESPONSE_MISMATCH')
            return data['payload']
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            self.uncertain = True
            raise UnknownOutcome('HTTP_OUTCOME_UNKNOWN') from None
        finally:
            if connection is not None: connection.close()
            self.lock.release()
