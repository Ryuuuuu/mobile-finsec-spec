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
    w.observing = False
    w.pending_input = None
    w.tasks = queue.Queue()
    w.closing = False
    w.connected = True
    w.adapter = Mock()
    return w


class PreviewLifecycleTest(unittest.TestCase):
    def test_close_waits_for_cleanup_without_querying_destroyed_tk(self):
        w = window(); w.engine.stop_requested = Mock()
        w.adapter.uncertain = False; w.adapter.session = None
        w.root.winfo_exists.side_effect = AssertionError('Tk queried after destruction')
        w.close()
        cleanup, finished = w.tasks.get_nowait()
        drain_close = w.root.after.call_args.args[1]
        w.root.after.reset_mock()
        drain_close()  # Cleanup is still running: keep draining without destroying Tk.
        w.root.destroy.assert_not_called()
        w.root.after.assert_called_once_with(100, drain_close)
        cleanup()
        w.adapter.close.assert_called_once()
        w.lease.release.assert_called_once_with(clean=True)
        w.answers.put((finished, None, None))
        w.root.after.reset_mock()
        drain_close()
        w.root.destroy.assert_called_once()
        w.root.after.assert_not_called()
        w.root.winfo_exists.assert_not_called()

    def test_input_waits_once_for_preview_and_duplicate_is_rejected(self):
        w = window(); w.observing = True
        action = Mock(); done = Mock()
        self.assertTrue(w.ready())
        self.assertTrue(w.submit(action, done))
        self.assertFalse(w.ready())
        self.assertFalse(w.submit(Mock()))
        w.answers.put((None, {}, None)); w.drain()
        self.assertEqual(w.tasks.get_nowait(), (action, done))
        self.assertTrue(w.busy)
        self.assertFalse(w.observing)
        self.assertIsNone(w.pending_input)

    def test_preview_failure_discards_waiting_input_without_dispatch(self):
        for error in (TargetNotForeground('home'), Uncertain('timeout')):
            w = window(); w.observing = True
            w.submit(Mock())
            w.answers.put((w.render, None, error)); w.drain()
            self.assertTrue(w.tasks.empty())
            self.assertIsNone(w.pending_input)

    def test_stop_during_preview_finishes_after_read_without_dispatching_pending_input(self):
        w=window();w.observing=True;w.engine=Mock(mode='recording')
        discarded=Mock();w.pending_input=(discarded,None)
        w.stop()
        w.engine.stop_requested.assert_called_once()
        self.assertEqual(w.pending_input[0],w.engine.finish)
        w.answers.put((None,{},None));w.drain()
        finish,_=w.tasks.get_nowait();self.assertEqual(finish,w.engine.finish)
        discarded.assert_not_called()

    def test_stop_during_actual_input_does_not_queue_successful_finish(self):
        w=window();w.observing=False;w.engine=Mock(mode='recording')
        w.stop();w.engine.stop_requested.assert_called_once()
        self.assertTrue(w.tasks.empty());self.assertIsNone(w.pending_input)

    def test_hold_selected_during_capture_preserves_displayed_frame(self):
        w = window(); w.visible.get.return_value = True
        previous = w.frame
        w.render({'png': b'unused pending image'})
        self.assertIs(w.frame, previous)
        w.visible.set.assert_not_called()
        w.canvas.delete.assert_not_called()

    def test_manual_completion_releases_hold_for_updated_screen(self):
        w = window(); w.visible.get.return_value = True
        w.answers.put((None, None, None)); w.drain()
        w.visible.set.assert_called_with(False)

    def test_close_discards_input_waiting_for_preview(self):
        w = window(); w.observing = True
        w.submit(Mock()); w.closing = True
        w.answers.put((None, {}, None)); w.drain()
        self.assertTrue(w.tasks.empty())
        self.assertIsNone(w.pending_input)

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
