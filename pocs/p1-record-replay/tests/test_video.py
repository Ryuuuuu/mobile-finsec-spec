import struct,time,unittest,io,socket,threading
from PIL import Image
from pc.video import header,recv_exact
from pc.mirror import mapping,verify_pixels

class VideoProtocolTest(unittest.TestCase):
    def test_session_resize_and_media_flags(self):
        self.assertEqual(header(struct.pack('>III',0x80000001,1080,2340)),('session',1080,2340))
        self.assertEqual(header(struct.pack('>QI',1<<62,100)),('media',1<<62,100))
        for data in (b'',struct.pack('>III',0x80000000,0,20),struct.pack('>QI',0,0),struct.pack('>QI',0,20*1024*1024)):
            with self.assertRaises(ValueError):header(data)
    def test_fragmented_transport_and_eof(self):
        class Socket:
            parts=[b'ab',b'c',b'']
            def recv(self,count):return self.parts.pop(0)
        socket=Socket();self.assertEqual(recv_exact(socket,3),b'abc')
        with self.assertRaises(EOFError):recv_exact(socket,1)
    def test_mapping_rejects_stale_rotated_or_scaled_stream(self):
        frame={'at':10,'generation':2,'size':(1080,2340)}
        geometry={'width':1080,'height':2340,'rotation':'PORTRAIT'}
        mapping(frame,geometry,11,2)
        for now,gen,g in ((16,2,geometry),(11,3,geometry),(11,2,dict(geometry,width=540))):
            with self.assertRaises(ValueError):mapping(frame,g,now,gen)
    def test_idle_timeout_preserves_partial_packet(self):
        class Socket:
            parts=[b'ab',socket.timeout(),b'c']
            def recv(self,count):
                item=self.parts.pop(0)
                if isinstance(item,Exception):raise item
                return item
        self.assertEqual(recv_exact(Socket(),3,threading.Event()),b'abc')
    def test_local_pixel_change_is_not_hidden_by_global_average(self):
        original=Image.new('RGB',(512,512),'white');current=original.copy()
        def png(image):
            output=io.BytesIO();image.save(output,format='PNG');return output.getvalue()
        self.assertEqual(verify_pixels(original,png(current)),0)
        current.paste('black',(200,200,216,216))
        with self.assertRaises(ValueError):verify_pixels(original,png(current))
        with self.assertRaises(ValueError):verify_pixels(original,png(current.resize((256,256))))
