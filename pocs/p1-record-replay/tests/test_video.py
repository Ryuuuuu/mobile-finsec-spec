import struct,time,unittest,io,socket,threading
from PIL import Image
from pc.video import header,recv_exact
from pc.mirror import mapping,verify_pixels,content_region

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


class MirrorBoundaryTest(unittest.TestCase):
    def test_letterbox_mapping_after_resize(self):
        from types import SimpleNamespace
        from pc.ui import Window
        window=SimpleNamespace(image=True,frame={'display':(800,800,360,780)})
        self.assertEqual(Window.point(window,SimpleNamespace(x=400,y=400)),[.5,.5])
        with self.assertRaises(ValueError):Window.point(window,SimpleNamespace(x=10,y=400))
        window.frame['display']=(1200,900,400,880)
        self.assertEqual(Window.point(window,SimpleNamespace(x=600,y=450)),[.5,.5])
    def test_release_blocks_resize_rotation_and_disconnect(self):
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        from pc.mirror import MirrorWindow
        for resized,error,generation in ((True,None,2),(False,None,3),(False,'EOF',2)):
            with self.subTest(resized=resized,error=error,generation=generation):
                w=SimpleNamespace(gesture_frame={'at':0,'generation':2,'size':(1080,2340)},
                    frame={'display':(800,800,360,780),'geometry':{'width':1080,'height':2340}},
                    gesture_display=(900,800,360,780) if resized else (800,800,360,780),
                    video=SimpleNamespace(snapshot=lambda:(None,error,generation)),start_point=[.5,.5],status=Mock())
                with patch('pc.ui.Window.release') as dispatch:
                    MirrorWindow.release(w,SimpleNamespace(x=400,y=400))
                    dispatch.assert_not_called()
                self.assertIsNone(w.start_point);w.status.set.assert_called_once()

    def test_duplicate_record_does_not_abort_existing_run(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from pc.ui import Window
        for mode in ('recording','replaying','incomplete'):
            w=SimpleNamespace(engine=SimpleNamespace(mode=mode),status=Mock(),submit=Mock())
            Window.record(w);w.submit.assert_not_called();w.status.set.assert_called_once()

class ContentRegionTest(unittest.TestCase):
    def xml(self,package='qa.app',extra=''):
        return f'<hierarchy><node package="{package}" resource-id="android:id/content" bounds="[0,32][128,240]"><node package="{package}" resource-id="qa.app:id/send" bounds="[16,64][112,96]" clickable="true" enabled="true"/>{extra}</node></hierarchy>'
    def test_only_unique_target_inside_content_allows_crop(self):
        self.assertEqual(content_region(self.xml(),'qa.app','qa.app:id/send',(128,256)),(0,32,128,240))
        for xml,locator in ((self.xml(),None),(self.xml('other'),'qa.app:id/send'),('<bad','qa.app:id/send'),(self.xml().replace('[0,32][128,240]','[0,32][128,260]'),'qa.app:id/send'),(self.xml().replace('[16,64][112,96]','[16,0][112,16]'),'qa.app:id/send')):
            self.assertIsNone(content_region(xml,'qa.app',locator,(128,256)))
    def test_system_change_allowed_only_with_verified_region_body_change_still_blocks(self):
        a=Image.new('RGB',(128,256),'white');b=a.copy();b.paste('black',(16,0,32,16))
        def png(image):
            out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()
        with self.assertRaises(ValueError):verify_pixels(a,png(b))
        region=content_region(self.xml(),'qa.app','qa.app:id/send',a.size)
        self.assertEqual(verify_pixels(a,png(b),region),0)
        b.paste('black',(32,64,48,80))
        with self.assertRaises(ValueError):verify_pixels(a,png(b),region)

    def test_edge_to_edge_requires_valid_live_status_bar_and_target_below_it(self):
        xml=self.xml().replace('[0,32][128,240]','[0,0][128,256]')
        bar=dict(visible=True,x=0,y=0,width=128,height=32)
        self.assertEqual(content_region(xml,'qa.app','qa.app:id/send',(128,256),bar),(0,32,128,256))
        for bad in (dict(bar,height=100),dict(bar,width=120),dict(bar,visible=False),dict(bar,height=True)):
            self.assertIsNone(content_region(xml,'qa.app','qa.app:id/send',(128,256),bad))
        self.assertIsNone(content_region(xml.replace('[16,64][112,96]','[16,0][112,16]'),'qa.app','qa.app:id/send',(128,256),bar))
