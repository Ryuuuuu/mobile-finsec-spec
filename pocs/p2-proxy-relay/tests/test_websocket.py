"""Only synthetic RFC 6455 clients/upstreams on ephemeral IPv4 loopback ports."""
from __future__ import annotations

import asyncio
import base64
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relay import Config, Relay, query  # noqa: E402
from websocket_relay import (MessageState, WebSocketEOF, WebSocketError, new_direction_state,  # noqa: E402
                             read_frame, validate_request, validate_response)
from websockets.frames import Frame, OP_BINARY, OP_CLOSE, OP_CONT, OP_PING, OP_PONG, OP_TEXT  # noqa: E402

REQUEST = (b'GET /synthetic-ws HTTP/1.1\r\nHost: qa.invalid\r\nUpgrade: websocket\r\n'
           b'Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n'
           b'Sec-WebSocket-Key: c3ludGhldGljLXBvYy1rZQ==\r\n\r\n')
RESPONSE = (b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
            b'Sec-WebSocket-Accept: 7sbntUgfmFlpglBJP/c9zZsZnL4=\r\n\r\n')


async def get_frame(reader, masked=False):
    return await read_frame(reader, masked=masked, maximum=1048576,
                            idle_timeout=2, io_timeout=1)


class CodecTests(unittest.IsolatedAsyncioTestCase):
    async def test_split_tcp_and_coalesced_frames_keep_exact_wire(self):
        reader = asyncio.StreamReader()
        first = Frame(OP_BINARY, b'a' * 300, fin=False).serialize(mask=True)
        second = Frame(OP_CONT, b'b', fin=True).serialize(mask=True)
        pending = asyncio.create_task(get_frame(reader, True))
        reader.feed_data(first[:1])
        await asyncio.sleep(0)
        self.assertFalse(pending.done())
        reader.feed_data(first[1:8])
        await asyncio.sleep(0)
        self.assertFalse(pending.done())
        reader.feed_data(first[8:] + second)
        decoded, raw = await pending
        self.assertEqual((decoded.opcode, decoded.fin, decoded.data, raw), (OP_BINARY, False, b'a' * 300, first))
        decoded, raw = await get_frame(reader, True)
        self.assertEqual((decoded.opcode, decoded.fin, raw), (OP_CONT, True, second))

    async def test_invalid_mask_reserved_opcode_control_and_nonminimal_length(self):
        cases = [Frame(OP_TEXT, b'no mask').serialize(mask=False),
                 b'\xc1\x80\x00\x00\x00\x00', b'\x83\x80\x00\x00\x00\x00',
                 b'\x09\x80\x00\x00\x00\x00', b'\x82\xfe\x00\x01\x00\x00\x00\x00x']
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(WebSocketError):
                reader = asyncio.StreamReader()
                reader.feed_data(raw)
                reader.feed_eof()
                await get_frame(reader, True)

    async def test_oversized_header_rejected_without_waiting_for_body(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b'\x82\xff' + (1048577).to_bytes(8, 'big'))
        with self.assertRaisesRegex(WebSocketError, 'oversized'):
            await asyncio.wait_for(get_frame(reader, True), 0.2)

    def test_fragment_utf8_message_limit_and_close_validation(self):
        state = MessageState(new_direction_state(), 8)
        first = state.accept(Frame(OP_TEXT, b'\xe2', fin=False))
        state.accept(Frame(OP_PING, b'x'))
        last = state.accept(Frame(OP_CONT, b'\x82\xac', fin=True))
        self.assertEqual(first['message_id'], last['message_id'])
        self.assertEqual(last['fragment_index'], 1)
        self.assertTrue(last['message_finished'])
        with self.assertRaisesRegex(WebSocketError, 'unexpected_continuation'):
            state.accept(Frame(OP_CONT, b'x'))
        with self.assertRaisesRegex(WebSocketError, 'invalid_utf8'):
            MessageState(new_direction_state(), 8).accept(Frame(OP_TEXT, b'\xff'))
        oversized = MessageState(new_direction_state(), 4)
        oversized.accept(Frame(OP_BINARY, b'123', fin=False))
        with self.assertRaisesRegex(WebSocketError, 'message_too_large'):
            oversized.accept(Frame(OP_CONT, b'45'))
        with self.assertRaisesRegex(WebSocketError, 'invalid_close'):
            MessageState(new_direction_state(), 8).accept(Frame(OP_CLOSE, b'x'))

    def test_handshake_strict_validation_both_legs(self):
        expected = validate_request(REQUEST, 16384)
        validate_response(RESPONSE, 16384, expected)
        for raw in (REQUEST.replace(b'13\r\n', b'12\r\n'),
                    REQUEST.replace(b'Connection: Upgrade', b'Connection: close'),
                    REQUEST.replace(b'c3ludGhldGljLXBvYy1rZQ==', b'bad'),
                    REQUEST.replace(b'Host: qa.invalid\r\n', b''),
                    REQUEST.replace(b'\r\n\r\n', b'\r\nSec-WebSocket-Extensions: permessage-deflate\r\n\r\n'),
                    REQUEST.replace(b'\r\n\r\n', b'\r\nSec-WebSocket-Protocol: synthetic\r\n\r\n')):
            with self.subTest(raw=raw), self.assertRaises(WebSocketError):
                validate_request(raw, 16384)
        for raw in (RESPONSE.replace(b'101', b'200'),
                    RESPONSE.replace(b'7sbntUgfmFlpglBJP/c9zZsZnL4=', b'incorrect'),
                    RESPONSE.replace(b'Connection: Upgrade', b'Connection: close'),
                    RESPONSE.replace(b'\r\n\r\n', b'\r\nSec-WebSocket-Extensions: permessage-deflate\r\n\r\n')):
            with self.subTest(raw=raw), self.assertRaises(WebSocketError):
                validate_response(raw, 16384, expected)


class WebSocketUpstream:
    def __init__(self):
        self.server = None
        self.handlers = set()
        self.writers = set()
        self.requests = []
        self.frames = []
        self.responses = []
        self.response = RESPONSE
        self.opened = asyncio.Event()
        self.arrived = asyncio.Queue()
        self.echo = True

    async def start(self, ssl=None):
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0, ssl=ssl)
        self.port = self.server.sockets[0].getsockname()[1]

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        self.writers.add(writer)
        try:
            self.requests.append(await reader.readuntil(b'\r\n\r\n'))
            writer.write(self.response)
            await writer.drain()
            self.opened.set()
            if self.response != RESPONSE:
                return
            while True:
                frame, raw = await get_frame(reader, True)
                self.frames.append(raw)
                self.arrived.put_nowait((frame, raw))
                if self.echo:
                    opcode = OP_PONG if frame.opcode == OP_PING else frame.opcode
                    answer = Frame(opcode, frame.data, fin=frame.fin).serialize(mask=False)
                    self.responses.append(answer)
                    writer.write(answer)
                    await writer.drain()
                if frame.opcode == OP_CLOSE:
                    return
        except (OSError, asyncio.CancelledError, asyncio.IncompleteReadError, WebSocketEOF, WebSocketError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            self.writers.discard(writer)
            self.handlers.discard(task)

    async def send(self, raw):
        await asyncio.wait_for(self.opened.wait(), 1)
        for writer in self.writers:
            writer.write(raw)
            await writer.drain()

    async def close(self):
        if self.server:
            self.server.close()
        for writer in list(self.writers):
            writer.close()
        for task in list(self.handlers):
            task.cancel()
        if self.handlers:
            await asyncio.gather(*self.handlers, return_exceptions=True)
        if self.server:
            await self.server.wait_closed()


class WebSocketRelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='p2-ws-synthetic-')
        self.db = Path(self.temp.name) / 'capture.sqlite3'
        self.upstream = WebSocketUpstream()
        await self.upstream.start()
        self.relay = None
        self.clients = []
        await self.make_relay()

    async def asyncTearDown(self):
        for writer in self.clients:
            writer.close()
        if self.relay:
            self.relay.store.fail_writes = False
            self.relay.store.write_delay_seconds = 0
            await asyncio.wait_for(self.relay.close(), 3)
        await self.upstream.close()
        for writer in self.clients:
            try:
                await writer.wait_closed()
            except OSError:
                pass
        self.temp.cleanup()

    async def make_relay(self, **settings):
        if self.relay:
            await self.relay.close()
        values = dict(db=self.db, upstream_port=self.upstream.port, enable_websocket=True,
                      io_timeout=0.5, websocket_idle_timeout=5,
                      relay_off_drain_ms=50, record_stop_response_drain_ms=50)
        values.update(settings)
        self.relay = Relay(Config(**values))
        await self.relay.start()
        await self.command('ON')

    async def command(self, operation, **kwargs):
        response = await self.relay.command(dict(schema_version=1, command_id=uuid.uuid4().hex,
                                                 command=operation, **kwargs))
        self.assertTrue(response['ok'], response)
        return response['result']

    async def record(self):
        return (await self.command('RECORD', device_id='synthetic-device', app_id='synthetic.ws'))['recording_id']

    async def connect(self, request=REQUEST, **kwargs):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.relay.port, **kwargs)
        self.clients.append(writer)
        writer.write(request)
        await writer.drain()
        response = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2)
        return reader, writer, response

    async def exchange(self, reader, writer, opcode, payload, *, fin=True):
        raw = Frame(opcode, payload, fin=fin).serialize(mask=True)
        writer.write(raw)
        await writer.drain()
        frame, response = await get_frame(reader)
        return raw, frame, response

    async def clean_close(self, reader, writer):
        await self.exchange(reader, writer, OP_CLOSE, b'\x03\xe8synthetic-close')
        await asyncio.wait_for(reader.read(), 1)
        await self.wait_handlers()

    async def wait_handlers(self):
        async with asyncio.timeout(1):
            while self.relay.tasks:
                await asyncio.sleep(0)

    def rows(self, rid, kind=None):
        rows = query(self.db, 'packets', recording_id=rid)['result']
        return [query(self.db, 'detail', packet_id=row['packet_id'])['result'] for row in rows
                if kind is None or row['kind'] == kind]

    def raw(self, row):
        # Frame storage uses the existing directional request/response BLOBs.
        message = row['request'] or row['response']
        return base64.b64decode(message['raw_base64'])

    async def test_ws_real_delivery_frames_directions_hashes_and_clean_lifecycle(self):
        rid = await self.record()
        reader, writer, response = await self.connect()
        self.assertEqual(response, RESPONSE)
        sent = []
        received = []
        for opcode, payload in ((OP_TEXT, b'synthetic text'), (OP_BINARY, bytes(range(256))), (OP_PING, b'qa ping')):
            raw, frame, answer = await self.exchange(reader, writer, opcode, payload)
            sent.append(raw)
            received.append(answer)
            self.assertEqual(frame.data, payload)
        await self.clean_close(reader, writer)
        stopped = await self.command('STOP')
        self.assertEqual(stopped['network_coverage'], 'complete_for_supported_scope')
        self.assertEqual(self.upstream.requests, [REQUEST])
        self.assertEqual(self.upstream.frames[:3], sent)
        frames = self.rows(rid, 'websocket_frame')
        self.assertEqual(len(frames), 8)
        self.assertEqual([self.raw(row) for row in frames[:6:2]], sent)
        self.assertEqual([self.raw(row) for row in frames[1:6:2]], received)
        for row in frames:
            raw = self.raw(row)
            message = row['request'] or row['response']
            self.assertEqual(message['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(self.rows(rid, 'websocket_open')), 1)
        closed, = self.rows(rid, 'websocket_close')
        self.assertFalse(closed['incomplete'])

    async def test_fragmented_text_binary_and_interleaved_ping_preserve_frames(self):
        rid = await self.record()
        reader, writer, _ = await self.connect()
        sequence = [(OP_TEXT, b'\xe2', False), (OP_PING, b'between', True),
                    (OP_CONT, b'\x82\xac', True), (OP_BINARY, b'first', False), (OP_CONT, b'last', True)]
        sent = []
        for opcode, payload, fin in sequence:
            raw, frame, _ = await self.exchange(reader, writer, opcode, payload, fin=fin)
            sent.append(raw)
            self.assertEqual((frame.data, frame.fin), (payload, fin))
        await self.clean_close(reader, writer)
        await self.command('STOP')
        self.assertEqual(self.upstream.frames[:5], sent)
        captured = [row for row in self.rows(rid, 'websocket_frame') if row['request']]
        self.assertEqual([self.raw(row) for row in captured[:5]], sent)

    async def test_partial_frame_at_stop_excluded_and_same_connection_records_again(self):
        rid = await self.record()
        reader, writer, _ = await self.connect()
        await self.exchange(reader, writer, OP_TEXT, b'before')
        raw = Frame(OP_BINARY, b'crosses stop').serialize(mask=True)
        writer.write(raw[:-2])
        await writer.drain()
        async with asyncio.timeout(1):
            while not any(s['directions']['client_to_upstream']['frame_in_progress']
                          for s in self.relay.websocket_connections.values()):
                await asyncio.sleep(0)
        await self.command('STOP')
        sealed = self.rows(rid)
        writer.write(raw[-2:])
        await writer.drain()
        self.assertEqual((await get_frame(reader))[0].data, b'crosses stop')
        await self.exchange(reader, writer, OP_TEXT, b'after stop')
        self.assertEqual(self.rows(rid), sealed)
        rid2 = await self.record()
        await self.exchange(reader, writer, OP_TEXT, b'second recording')
        await self.clean_close(reader, writer)
        await self.command('STOP')
        frames = self.rows(rid2, 'websocket_frame')
        self.assertTrue(frames)
        self.assertTrue(all(row['context_before_recording'] for row in frames))
        self.assertTrue(all(row['websocket']['frame_sequence'] > 1 for row in frames))
        self.assertEqual(self.rows(rid), sealed)

    async def test_server_unsolicited_frame_after_stop_is_not_response_drain(self):
        rid = await self.record()
        reader, writer, _ = await self.connect()
        await self.exchange(reader, writer, OP_TEXT, b'before')
        await self.command('STOP')
        sealed = self.rows(rid)
        pushed = Frame(OP_TEXT, b'unsolicited after STOP').serialize(mask=False)
        await self.upstream.send(pushed)
        self.assertEqual((await get_frame(reader))[1], pushed)
        await self.clean_close(reader, writer)
        self.assertEqual(self.rows(rid), sealed)

    async def test_abrupt_close_and_off_force_cleanup_are_partial(self):
        rid = await self.record()
        reader, writer, _ = await self.connect()
        await self.exchange(reader, writer, OP_TEXT, b'abrupt')
        writer.close()
        await writer.wait_closed()
        await self.wait_handlers()
        result = await self.command('STOP')
        self.assertEqual(result['network_coverage'], 'partial')
        closed, = self.rows(rid, 'websocket_close')
        self.assertTrue(closed['incomplete'])
        rid2 = await self.record()
        reader2, _, _ = await self.connect()
        await self.command('OFF')
        self.assertEqual(await asyncio.wait_for(reader2.read(), 1), b'')
        self.assertFalse(self.relay.tasks)
        self.assertFalse(self.relay.websocket_connections)
        result = await self.command('STOP')
        self.assertEqual(result['network_coverage'], 'partial')
        self.assertTrue(self.rows(rid2, 'websocket_close'))

    async def test_frame_limit_invalid_mask_and_message_limit_end_connection(self):
        await self.make_relay(max_websocket_frame_bytes=8, max_websocket_message_bytes=10)
        rid = await self.record()
        for raw in (Frame(OP_BINARY, b'x' * 9).serialize(mask=True),
                    Frame(OP_TEXT, b'x').serialize(mask=False),
                    Frame(OP_BINARY, b'a' * 6, fin=False).serialize(mask=True)
                    + Frame(OP_CONT, b'b' * 6).serialize(mask=True)):
            reader, writer, _ = await self.connect()
            writer.write(raw)
            await writer.drain()
            await asyncio.wait_for(reader.read(), 1)
            await self.wait_handlers()
        result = await self.command('STOP')
        self.assertEqual(result['network_coverage'], 'partial')
        self.assertEqual(len(self.rows(rid, 'websocket_close')), 3)

    async def test_invalid_handshake_never_opens_bridge_and_bad_upstream_rejected(self):
        rid = await self.record()
        _, _, response = await self.connect(REQUEST.replace(b'13\r\n', b'12\r\n'))
        self.assertIn(b'400', response)
        self.assertEqual(self.upstream.requests, [])
        self.upstream.response = RESPONSE.replace(b'7sbntUgfmFlpglBJP/c9zZsZnL4=', b'bad')
        _, _, response = await self.connect()
        self.assertIn(b'502', response)
        await self.wait_handlers()
        result = await self.command('STOP')
        self.assertEqual(result['network_coverage'], 'partial')
        self.assertFalse(self.rows(rid, 'websocket_open'))

    async def test_default_http_mode_rejects_upgrade(self):
        await self.make_relay(enable_websocket=False)
        rid = await self.record()
        _, _, response = await self.connect()
        self.assertIn(b'400', response)
        self.assertEqual(self.upstream.requests, [])
        await self.command('STOP')
        self.assertFalse(self.rows(rid, 'websocket_frame'))

    async def test_first_frame_with_upgrade_and_coalesced_frames_keep_tcp_boundaries(self):
        rid = await self.record()
        first = Frame(OP_BINARY, b'first synthetic frame').serialize(mask=True)
        second = Frame(OP_TEXT, b'second synthetic frame').serialize(mask=True)
        reader, writer, response = await self.connect(REQUEST + first[:1])
        self.assertEqual(response, RESPONSE)
        writer.write(first[1:] + second)
        await writer.drain()
        self.assertEqual((await get_frame(reader))[0].data, b'first synthetic frame')
        self.assertEqual((await get_frame(reader))[0].data, b'second synthetic frame')
        await self.clean_close(reader, writer)
        await self.command('STOP')
        captured = [row for row in self.rows(rid, 'websocket_frame') if row['request']]
        self.assertEqual([self.raw(row) for row in captured[:2]], [first, second])
        self.assertEqual([row['websocket']['frame_sequence'] for row in captured], [1, 2, 3])

    async def test_fragment_context_crosses_record_windows_without_reassigning_old_frames(self):
        rid = await self.record()
        reader, writer, _ = await self.connect()
        first_raw, _, _ = await self.exchange(reader, writer, OP_TEXT, b'begin ', fin=False)
        stopped = await self.command('STOP')
        self.assertEqual(stopped['network_coverage'], 'partial')
        self.assertIn('websocket_incomplete_at_stop', [gap['reason'] for gap in stopped['gaps']])
        states = [state for connection in stopped['websocket_at_stop'].values()
                  for state in connection['directions'].values()]
        self.assertTrue(any(state['message_id'] for state in states))
        first_rows = self.rows(rid, 'websocket_frame')
        rid2 = await self.record()
        await self.exchange(reader, writer, OP_CONT, b'end', fin=True)
        await self.clean_close(reader, writer)
        await self.command('STOP')
        first = next(row for row in first_rows if row['request'])
        last = next(row for row in self.rows(rid2, 'websocket_frame') if row['request'])
        self.assertEqual(self.raw(first), first_raw)
        self.assertEqual(first['websocket']['message_id'], last['websocket']['message_id'])
        self.assertLess(last['websocket']['message_started_monotonic'], last['monotonic'])
        self.assertEqual(first['websocket']['fragment_index'], 0)
        self.assertEqual(last['websocket']['fragment_index'], 1)
        self.assertEqual(self.rows(rid, 'websocket_frame'), first_rows)

    async def test_ws_queue_overflow_preserves_delivery_and_reports_loss(self):
        await self.make_relay(queue_size=1)
        rid = await self.record()
        self.relay.store.write_delay_seconds = 0.025
        reader, writer, _ = await self.connect()
        for index in range(20):
            _, frame, _ = await self.exchange(reader, writer, OP_TEXT, f'synthetic-{index}'.encode())
            self.assertEqual(frame.data, f'synthetic-{index}'.encode())
        await self.clean_close(reader, writer)
        result = await self.command('STOP')
        self.assertEqual(result['network_coverage'], 'partial')
        self.assertGreater(result['counters']['dropped'], 0)
        self.assertEqual(len(self.upstream.frames), 21)
        self.assertLess(len(self.rows(rid, 'websocket_frame')), 42)

    async def test_ws_storage_failure_and_restart_immutable_query(self):
        rid = await self.record()
        reader, writer, _ = await self.connect()
        self.relay.store.fail_writes = True
        _, frame, _ = await self.exchange(reader, writer, OP_TEXT, b'synthetic storage fault')
        self.assertEqual(frame.data, b'synthetic storage fault')
        await self.relay.queue.join()
        self.relay.store.fail_writes = False
        await self.clean_close(reader, writer)
        result = await self.command('STOP')
        self.assertEqual(result['network_coverage'], 'partial')
        self.assertGreater(result['counters']['storage_errors'], 0)
        before = self.rows(rid)
        await self.make_relay()
        self.assertEqual(self.rows(rid), before)

    async def test_recorded_decoder_error_counter_for_established_connection(self):
        rid = await self.record()
        reader, writer, _ = await self.connect()
        writer.write(Frame(OP_TEXT, b'\xff').serialize(mask=True))
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.read(), 1), b'')
        await self.wait_handlers()
        result = await self.command('STOP')
        self.assertEqual(result['network_coverage'], 'partial')
        self.assertGreater(result['counters']['decoder_errors'], 0)
        self.assertFalse(self.rows(rid, 'websocket_frame'))

    async def test_capture_truncation_preserves_full_forwarding_and_payload_hashes(self):
        await self.make_relay(capture_body_bytes=16)
        rid = await self.record()
        reader, writer, _ = await self.connect()
        payload = b'synthetic payload:' + bytes(range(256))
        raw, frame, answer = await self.exchange(reader, writer, OP_BINARY, payload)
        self.assertEqual(frame.data, payload)
        await self.clean_close(reader, writer)
        result = await self.command('STOP')
        self.assertEqual(result['network_coverage'], 'partial')
        captured = self.rows(rid, 'websocket_frame')[:2]
        for row, original in zip(captured, (raw, answer)):
            message = row['request'] or row['response']
            self.assertTrue(message['truncated'])
            self.assertEqual(self.raw(row), original[:16])
            self.assertEqual(message['size'], len(original))
            self.assertEqual(message['stored_size'], 16)
            self.assertEqual(message['sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(message['stored_sha256'], hashlib.sha256(original[:16]).hexdigest())
            self.assertEqual(row['websocket']['payload_sha256'], hashlib.sha256(payload).hexdigest())
            self.assertEqual(row['websocket']['payload_size'], len(payload))
        self.assertEqual(self.upstream.frames[0], raw)

    async def test_malformed_frame_and_abrupt_eof_after_stop_do_not_mutate_record(self):
        for malformed in (True, False):
            with self.subTest(malformed=malformed):
                rid = await self.record()
                reader, writer, _ = await self.connect()
                await self.exchange(reader, writer, OP_TEXT, b'before seal')
                stopped = await self.command('STOP')
                self.assertEqual(stopped['network_coverage'], 'complete_for_supported_scope')
                sealed_record = next(row for row in query(self.db, 'recordings')['result']
                                     if row['recording_id'] == rid)
                sealed_packets = self.rows(rid)
                if malformed:
                    writer.write(Frame(OP_TEXT, b'\xff').serialize(mask=True))
                    await writer.drain()
                else:
                    writer.close()
                    await writer.wait_closed()
                await asyncio.wait_for(reader.read(), 1)
                await self.wait_handlers()
                actual_record = next(row for row in query(self.db, 'recordings')['result']
                                     if row['recording_id'] == rid)
                self.assertEqual(actual_record, sealed_record)
                self.assertEqual(self.rows(rid), sealed_packets)
                self.assertEqual(self.relay.last_recording, sealed_record)
