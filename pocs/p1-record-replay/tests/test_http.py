"""Loopback fake server integration: exercises real JSON/HTTP adapter, not a device."""
import base64,json,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from pc.adapter import Appium,ELEMENT
from pc.protocol import PREFIX,PACKAGE
class Handler(BaseHTTPRequestHandler):
    calls=[]
    def log_message(self,*args):pass
    def run_request(self):
        payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or b'null')
        self.calls.append((self.command,self.path,payload))
        if self.path=='/session':value={'sessionId':'fake-session','capabilities':{}}
        elif self.path.endswith('/elements'):value=[{ELEMENT:'el1'}]
        elif self.path.endswith('/text'):value='qa-user'
        elif self.path.endswith('/current_package'):value=PACKAGE
        elif self.path.endswith('/window/rect'):value={'width':1080,'height':1920,'x':0,'y':0}
        elif self.path.endswith('/orientation'):value='PORTRAIT'
        elif self.path.endswith('/source'):value='<hierarchy/>'
        elif self.path.endswith('/screenshot'):value=base64.b64encode(b'PNG').decode()
        else:value=None
        data=json.dumps({'value':value}).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    do_POST=run_request;do_GET=run_request;do_DELETE=run_request
class HttpTest(unittest.TestCase):
    def test_w3c_end_to_end(self):
        Handler.calls=[];server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            a=Appium('EXPLICIT-SERIAL',PACKAGE,'http://127.0.0.1:'+str(server.server_port))
            with patch.object(a,'target',return_value={}):a.open()
            a.foreground();self.assertEqual(a.elements(PREFIX+'username'),['el1']);self.assertEqual(a.text('el1'),'qa-user')
            a.enter('el1','qa-user');a.click('el1');a.back();a.gesture([100,200],[100,500]);self.assertEqual(a.geometry()['rotation'],'PORTRAIT')
            self.assertEqual(a.source(),'<hierarchy/>');self.assertEqual(a.screenshot(),b'PNG');a.close()
            caps=Handler.calls[0][2]['capabilities']['alwaysMatch'];self.assertEqual(caps['appium:udid'],'EXPLICIT-SERIAL');self.assertTrue(caps['appium:noReset'])
            paths=[c[1] for c in Handler.calls];self.assertFalse(any('/execute' in x for x in paths));self.assertEqual(Handler.calls[-1][:2],('DELETE','/session/fake-session'))
        finally:server.shutdown();thread.join();server.server_close()
    def test_remote_server_rejected(self):
        for url in ['http://example.com','https://127.0.0.1','http://user@localhost']:
            with self.assertRaises(ValueError):Appium('SERIAL',PACKAGE,url)
if __name__=='__main__':unittest.main()
