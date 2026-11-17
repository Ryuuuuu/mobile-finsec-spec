"""Synthetic preview lifecycle regressions; no Tk display, device or Appium server."""
import queue
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pc.adapter import TargetNotForeground, Uncertain
from pc.ui import Window


def window():
    w = Window.__new__(Window)
    w.frame = {'display': (100, 200, 100, 200)}
    w.image = object()
    w.start_point = [0.4, 0.5]
    w.visible = Mock()
    w.visible.get.return_value = False
    w.canvas = Mock()
    w.canvas.winfo_width.return_value = 400
    w.canvas.winfo_height.return_value = 600
    w.preview_status = Mock()
    w.status = Mock()
    w.root = Mock()
    w.answers = queue.Queue()
    w.engine = SimpleNamespace(j=None, mode='idle')
    w.lease = Mock()
    w.replay_disabled = []
    w.busy = True
    w.closing = False
    w.connected = True
    w.adapter = Mock()
    return w


class PreviewLifecycleTest(unittest.TestCase):
    def assert_invalidated(self, w):
        self.assertIsNone(w.frame)
        self.assertIsNone(w.image)
        self.assertIsNone(w.start_point)
        w.visible.set.assert_called_with(False)
        w.canvas.delete.assert_called_with('all')

    def test_foreground_loss_discards_pixels_and_coordinate_mapping(self):
        w = window()
        w.answers.put((w.render, None, TargetNotForeground('Target is not foreground')))
        w.drain()
        self.assert_invalidated(w)
        self.assertTrue(w.connected)  # May resume when the synthetic app returns.
        self.assertIn('target app is not foreground', w.preview_status.set.call_args.args[0])
        w.lease.poison.assert_not_called()

    def test_transport_uncertainty_invalidates_and_disconnects(self):
        w = window()
        w.answers.put((w.render, None, Uncertain('synthetic timeout')))
        w.drain()
        self.assert_invalidated(w)
        self.assertFalse(w.connected)
        w.lease.poison.assert_called_once()

    def test_missing_and_malformed_images_cannot_reuse_an_old_frame(self):
        for frame in ({'png_error': 'synthetic capture unavailable'}, {'png': b'bad'}):
            with self.subTest(frame=frame):
                w = window()
                w.render(frame)
                self.assert_invalidated(w)
                w.canvas.create_image.assert_not_called()

    def test_success_after_failure_renders_new_frame_with_observed_secure_state(self):
        w = window()
        w.clear_preview('Preview paused')
        frame = {'png': b'\0' * 16 + struct.pack('>II', 100, 200),
                 'geometry': {'width': 100, 'height': 200}, 'received_at': '12:34:56',
                 'xml': '<hierarchy><node resource-id="dev.finsec.poc:id/secure_state" text="secure:on"/></hierarchy>'}
        photo = Mock()
        photo.subsample.return_value = photo
        photo.width.return_value = 100
        photo.height.return_value = 200
        with patch('pc.ui.tk.PhotoImage', return_value=photo):
            w.render(frame)
        self.assertIs(w.frame, frame)
        self.assertIs(w.image, photo)
        w.canvas.create_image.assert_called_once()
        label = w.preview_status.set.call_args.args[0]
        self.assertIn('12:34:56', label)
        self.assertIn('FLAG_SECURE is ON', label)

    def test_home_guard_prevents_capture_and_transition_during_capture_rejects_frame(self):
        for results, calls in (([TargetNotForeground('home')], 0),
                               ([None, TargetNotForeground('switched during capture')], 1)):
            with self.subTest(calls=calls):
                w = window()
                w.busy = False
                w.start_point = None
                w.adapter.foreground.side_effect = results
                w.submit = Mock()
                w.poll()
                work = w.submit.call_args.args[0]
                with self.assertRaises(TargetNotForeground):
                    work()
                self.assertEqual(w.adapter.screenshot.call_count, calls)


if __name__ == '__main__':
    unittest.main()
