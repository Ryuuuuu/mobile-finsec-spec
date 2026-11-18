import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from integration.stdio_client import StdioClient, UnknownOutcome
from test_mock_stdio import request


def message(op, args):
    return dict(contract='mock-ui-request.v1', project_id='synthetic-stdio',
        request_generation=1, operation=op, arguments=args)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def client(self, code=None, timeout=2):
        argv=[sys.executable,'-m','integration.mock_stdio','--mock-root',str(self.root)] if code is None else [sys.executable,'-c',code,str(self.root)]
        client=StdioClient(argv,timeout=timeout);self.addCleanup(client.close);return client

    def test_live_duplicate_and_changed_request(self):
        client=self.client();msg=message('submit',{'request':request()})
        first=client.exchange(msg)['data'];again=client.exchange(msg)['data']
        self.assertEqual(first['execution_id'],again['execution_id'])
        self.assertEqual(again['status'],'duplicate')
        msg['arguments']['request']['inventory_revision']=2
        self.assertEqual(client.exchange(msg)['data']['status'],'conflict')

    def test_delayed_admission_reply_poisoned_then_restart(self):
        code='''import asyncio,sys,time
from pathlib import Path
from integration.mock_stdio import serve
from integration.ui_wire import UIWire
original=UIWire.exchange
def delayed(self,raw):
    reply=original(self,raw)
    time.sleep(.6)
    return reply
UIWire.exchange=delayed
asyncio.run(serve(Path(sys.argv[1])))
'''
        client=self.client(code);client.timeout=.1
        with self.assertRaisesRegex(UnknownOutcome,'RESPONSE_DEADLINE'):
            client.exchange(message('submit',{'request':request()}))
        time.sleep(.7)  # Ensure the stale reply actually reaches the pipe.
        with self.assertRaisesRegex(UnknownOutcome,'CHANNEL_UNUSABLE'):
            client.exchange(message('history',{}))
        client.close()
        restarted=self.client()
        self.assertEqual(restarted.exchange(message('submit',{'request':request()}))['data']['status'],'recovery_required')

    def test_eof_and_wrong_response_identity(self):
        ready=json.dumps({'contract':'mock-stdio.v1','status':'ready','synthetic':True})
        for tail in ("sys.exit(0)","print(json.dumps({'contract':'mock-ui.v1','project_id':'wrong','request_generation':1}),flush=True)"):
            client=self.client(f'import sys,json\nprint({ready!r},flush=True)\nsys.stdin.readline()\n'+tail)
            with self.assertRaises(UnknownOutcome):client.exchange(message('history',{}))
            self.assertTrue(client.uncertain);client.close()

    def test_non_reading_child_write_deadline(self):
        ready=json.dumps({'contract':'mock-stdio.v1','status':'ready','synthetic':True})
        client=self.client(f'import time\nprint({ready!r},flush=True)\ntime.sleep(10)')
        client.timeout=.1
        with self.assertRaisesRegex(UnknownOutcome,'RESPONSE_DEADLINE'):
            client.exchange({'payload':'x'*200000})
        client.close();self.assertIsNotNone(client.process.poll())
