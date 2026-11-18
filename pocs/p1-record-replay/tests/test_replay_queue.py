import copy
import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from test_core import Fake, tap
from pc.core import Engine
from pc.combined import CombinedRun
from pc.replay_queue import ReplayQueue


class ReplayQueueTests(unittest.TestCase):
    def make(self, root):
        engine = Engine(Fake(), root)
        routes = []
        for _ in range(3):
            engine.a = Fake()
            engine.start(); engine.record_action(tap()); engine.finish()
            routes.append(copy.deepcopy(engine.record))
        network = Mock()
        def command(name, **kw):
            return {'recording_id': kw['recording_id']} if name == 'RECORD' else {'network_coverage': 'complete_for_supported_scope'}
        network.command.side_effect = command
        combined = CombinedRun(engine, network, root)
        queue = ReplayQueue(combined, root)
        queue.prepare = lambda index, route: setattr(engine, 'a', Fake())
        return queue, routes, network

    def test_three_routes_separate_ids_and_repeat(self):
        with tempfile.TemporaryDirectory() as root:
            queue, routes, network = self.make(root)
            ordered = [routes[2], routes[0], routes[1]]
            first = queue.run(ordered)
            self.assertEqual(first['status'], 'succeeded')
            self.assertEqual([r['source_recording_id'] for r in first['entries']], [r['recording_id'] for r in ordered])
            for field in ('combined_id', 'network_recording_id', 'replay_run_id'):
                self.assertEqual(len({r[field] for r in first['entries']}), 3)
            self.assertEqual([call.args[0] for call in network.command.call_args_list], ['RECORD','STOP'] * 3)
            second = queue.run(ordered)
            self.assertNotEqual(first['queue_id'], second['queue_id'])
            self.assertTrue(set(r['replay_run_id'] for r in first['entries']).isdisjoint(r['replay_run_id'] for r in second['entries']))

    def test_partial_network_stops_remaining(self):
        with tempfile.TemporaryDirectory() as root:
            queue, routes, network = self.make(root)
            original = network.command.side_effect
            network.command.side_effect = lambda name, **kw: {'network_coverage':'partial'} if name == 'STOP' else original(name, **kw)
            result = queue.run(routes)
            self.assertEqual(result['status'], 'partial')
            self.assertEqual([r['status'] for r in result['entries']], ['incomplete','not_run','not_run'])
            self.assertEqual(network.command.call_count, 2)

    def test_cancel_survives_route_clear_and_blocks_dispatch(self):
        with tempfile.TemporaryDirectory() as root:
            queue, routes, network = self.make(root)
            original = network.command.side_effect
            def command(name, **kw):
                if name == 'RECORD': queue.cancel()
                return original(name, **kw)
            network.command.side_effect = command
            result = queue.run(routes)
            self.assertEqual(result['status'], 'cancelled')
            self.assertEqual(queue.combined.engine.a.inputs, [])
            self.assertEqual(result['entries'][1]['status'], 'not_run')
            self.assertEqual([c.args[0] for c in network.command.call_args_list], ['RECORD','STOP'])

    def test_intent_storage_failure_and_duplicate_do_not_start(self):
        with tempfile.TemporaryDirectory() as root:
            queue, routes, network = self.make(root)
            with patch('pc.replay_queue.atomic', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): queue.run(routes)
            network.command.assert_not_called()
            self.assertTrue(queue.blocked)
            with self.assertRaises(RuntimeError): queue.run(routes)
            queue.guard.acquire()
            try:
                with self.assertRaises(RuntimeError): queue.run(routes)
            finally: queue.guard.release()
            network.command.assert_not_called()

    def test_terminal_storage_failure_prevents_next_route_and_retry(self):
        from pc.replay_queue import atomic
        with tempfile.TemporaryDirectory() as root:
            queue, routes, network = self.make(root)
            def write(path, result):
                if result['entries'][0]['status'] == 'succeeded': raise OSError('lost terminal write')
                atomic(path, result)
            with patch('pc.replay_queue.atomic', side_effect=write): result = queue.run(routes)
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(result['entries'][1]['status'], 'not_run')
            self.assertEqual(network.command.call_count, 2)
            with self.assertRaises(RuntimeError): queue.run(routes)

    def test_prepare_failure_is_persisted_without_network_start(self):
        with tempfile.TemporaryDirectory() as root:
            queue, routes, network = self.make(root)
            queue.prepare = Mock(side_effect=RuntimeError('fixture unavailable'))
            result = queue.run(routes)
            self.assertEqual(result['status'], 'partial')
            network.command.assert_not_called()
            self.assertEqual(json.loads((queue.journal.path/'queue.json').read_text())['entries'][1]['status'], 'not_run')
