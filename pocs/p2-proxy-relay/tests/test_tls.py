"""Verified local TLS termination tests; all certificates are generated at runtime."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relay import Config, Relay, query, tls_contexts
from tls_fixture import TLSFixture
from test_websocket import get_frame, REQUEST as WS_REQUEST, RESPONSE as WS_RESPONSE
from websocket_relay import WebSocketEOF, WebSocketError
from websockets.frames import Frame, OP_BINARY, OP_CLOSE, OP_CONT, OP_PING, OP_PONG, OP_TEXT

REQUEST = b'GET /synthetic/tls HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'
BODY = b'synthetic-tls-body\x00\xff'
RESPONSE = (b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(BODY)).encode()
            + b'\r\nConnection: close\r\n\r\n' + BODY)


class TLSAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.pki_temp = tempfile.TemporaryDirectory(prefix='p2-synthetic-pki-')
        cls.addClassCleanup(cls.pki_temp.cleanup)
        cls.pki = TLSFixture(Path(cls.pki_temp.name))

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='p2-tls-test-')
        self.db = Path(self.temp.name) / 'capture.sqlite3'
        self.relay = None
        self.server = None
        self.upstream_context = None
        self.tasks = set()
        self.writers = set()
        self.received = []
        self.websocket = False
        self.upstream_frames = []
        self.upstream_responses = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def asyncTearDown(self):
        self.release.set()
        if self.relay:
            await asyncio.wait_for(self.relay.close(), 3)
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in list(self.writers):
            writer.close()
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.temp.cleanup()

    async def upstream(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.writers.add(writer)
        try:
            if self.upstream_context is not None:
                await writer.start_tls(self.upstream_context, ssl_handshake_timeout=0.5, ssl_shutdown_timeout=0.5)
            self.received.append(await reader.readuntil(b'\r\n\r\n'))
            self.entered.set()
            await self.release.wait()
            if self.websocket:
                writer.write(WS_RESPONSE)
                await writer.drain()
                while True:
                    frame, raw = await get_frame(reader, masked=True)
                    self.upstream_frames.append(raw)
                    opcode = OP_PONG if frame.opcode == OP_PING else frame.opcode
                    response = Frame(opcode, frame.data, fin=frame.fin).serialize(mask=False)
                    self.upstream_responses.append(response)
                    writer.write(response)
                    await writer.drain()
                    if frame.opcode == OP_CLOSE:
                        break
            else:
                writer.write(RESPONSE)
                await writer.drain()
        except (OSError, asyncio.IncompleteReadError, asyncio.CancelledError, WebSocketEOF, WebSocketError):
            pass
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 0.5)
            except (OSError, TimeoutError, asyncio.CancelledError):
                pass
            self.writers.discard(writer)
            self.tasks.discard(task)

    async def start(self, *, listener=True, upstream=True, **kwargs):
        self.upstream_context = self.pki.server_context() if upstream else None
        self.server = await asyncio.start_server(self.upstream, '127.0.0.1', 0)
        config = dict(db=self.db, upstream_port=self.server.sockets[0].getsockname()[1],
                      listener_cert=self.pki.cert if listener else None,
                      listener_key=self.pki.key if listener else None,
                      upstream_tls=upstream, upstream_ca=self.pki.ca if upstream else None,
                      io_timeout=1, relay_off_drain_ms=40, record_stop_response_drain_ms=100)
        config.update(kwargs)
        self.relay = Relay(Config(**config))
        await self.relay.start()
        await self.command('ON')
        return (await self.command('RECORD', device_id='synthetic-tls',
                                   app_id='dev.finsec.synthetic'))['recording_id']

    async def command(self, operation, **kwargs):
        response = await self.relay.command(dict(schema_version=1, command_id=uuid.uuid4().hex,
                                                 command=operation, **kwargs))
        self.assertTrue(response['ok'], response)
        return response['result']

    async def exchange(self, *, tls=True, context=None):
        options = dict(ssl=context or self.pki.client_context(), server_hostname='localhost') if tls else {}
        reader, writer = await asyncio.open_connection('127.0.0.1', self.relay.port, **options)
        try:
            writer.write(REQUEST)
            await writer.drain()
            return await asyncio.wait_for(reader.read(), 2)
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, TimeoutError):
                pass

    def packets(self, rid):
        result = query(self.db, 'packets', recording_id=rid)
        self.assertTrue(result['ok'], result)
        return [query(self.db, 'detail', packet_id=p['packet_id'])['result'] for p in result['result']]

    async def wait_no_handlers(self):
        async with asyncio.timeout(2):
            while self.relay.tasks:
                await asyncio.sleep(0.001)

    async def wait_stopping(self):
        async with asyncio.timeout(2):
            while self.relay.active_recording is not None:
                await asyncio.sleep(0.001)

    async def test_https_decrypted_capture_and_verified_metadata(self):
        rid = await self.start()
        self.assertEqual(await self.exchange(), RESPONSE)
        stopped = await self.command('STOP')
        packet, = self.packets(rid)
        self.assertEqual(self.received, [REQUEST])
        self.assertEqual(packet['transport'], 'TLS')
        self.assertEqual(packet['protocol'], 'HTTP/1.1')
        self.assertEqual(packet['capture_mode'], 'decrypted')
        self.assertTrue(packet['tls']['upstream_verified'])
        self.assertTrue(packet['tls']['client_version'].startswith('TLSv1.'))
        self.assertTrue(packet['tls']['upstream_version'].startswith('TLSv1.'))
        self.assertEqual(packet['tls']['upstream_peer_sha256'], packet['tls']['listener_certificate_sha256'])
        for key, expected in (('request', REQUEST), ('response', RESPONSE)):
            self.assertEqual(base64.b64decode(packet[key]['raw_base64']), expected)
            self.assertEqual(packet[key]['sha256'], hashlib.sha256(expected).hexdigest())
        self.assertEqual(stopped['network_coverage'], 'complete_for_supported_scope')
        self.assertEqual(self.relay.relay_state, 'on')
        self.assertEqual(stopped['config']['tls'], self.relay.status()['tls'])
        metadata = json.dumps(self.relay.status())
        self.assertNotIn(str(self.pki.directory), metadata)
        self.assertNotIn('BEGIN CERTIFICATE', metadata)
        self.assertNotIn('PRIVATE KEY', metadata)
        self.assertEqual(len(stopped['config']['tls']['upstream_ca_sha256']), 1)

    async def test_plain_listener_verified_tls_upstream_is_explicit(self):
        rid = await self.start(listener=False)
        self.assertEqual(await self.exchange(tls=False), RESPONSE)
        await self.command('STOP')
        packet, = self.packets(rid)
        self.assertFalse(packet['tls']['listener_enabled'])
        self.assertIsNone(packet['tls']['client_version'])
        self.assertTrue(packet['tls']['upstream_verified'])
        self.assertEqual(packet['capture_mode'], 'decrypted')

    async def test_tls_listener_plain_upstream_is_explicit(self):
        rid = await self.start(upstream=False)
        self.assertEqual(await self.exchange(), RESPONSE)
        await self.command('STOP')
        packet, = self.packets(rid)
        self.assertTrue(packet['tls']['listener_enabled'])
        self.assertFalse(packet['tls']['upstream_enabled'])
        self.assertFalse(packet['tls']['upstream_verified'])
        self.assertIsNone(packet['tls']['upstream_version'])

    async def assert_upstream_rejected(self, **kwargs):
        rid = await self.start(**kwargs)
        self.assertIn(b'502 Bad Gateway', await self.exchange())
        stopped = await self.command('STOP')
        packet, = self.packets(rid)
        self.assertEqual(self.received, [])
        self.assertTrue(packet['incomplete'])
        self.assertEqual(packet['error'], 'upstream:certificate_verification_failed')
        self.assertFalse(packet['tls']['upstream_verified'])
        self.assertEqual(stopped['network_coverage'], 'partial')
        self.assertEqual(stopped['counters']['tls_errors'], 1)

    async def test_unknown_upstream_ca_is_rejected(self):
        await self.assert_upstream_rejected(upstream_ca=None)

    async def test_wrong_upstream_hostname_is_rejected(self):
        await self.assert_upstream_rejected(upstream_server_name='wrong.localhost')

    async def test_client_must_explicitly_trust_listener_certificate(self):
        rid = await self.start()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_default_certs()
        with self.assertRaises(ssl.SSLCertVerificationError):
            await self.exchange(context=context)
        await self.wait_no_handlers()
        stopped = await self.command('STOP')
        self.assertEqual(self.packets(rid), [])
        self.assertEqual(self.received, [])
        self.assertEqual(stopped['network_coverage'], 'partial')
        self.assertEqual(stopped['counters']['tls_errors'], 1)

    async def test_tls_stop_drains_existing_response_only(self):
        rid = await self.start(record_stop_response_drain_ms=500)
        self.release.clear()
        pending = asyncio.create_task(self.exchange())
        await asyncio.wait_for(self.entered.wait(), 2)
        stopping = asyncio.create_task(self.command('STOP'))
        await self.wait_stopping()
        self.assertFalse(stopping.done())
        self.release.set()
        self.assertEqual(await pending, RESPONSE)
        stopped = await stopping
        packet, = self.packets(rid)
        self.assertTrue(packet['received_after_stop'])
        self.assertEqual(stopped['persisted_packets'], 1)
        sealed = self.packets(rid)
        self.assertEqual(await self.exchange(), RESPONSE)
        self.assertEqual(self.packets(rid), sealed)

    async def test_tls_stop_timeout_seals_before_late_response(self):
        rid = await self.start(record_stop_response_drain_ms=20)
        self.release.clear()
        pending = asyncio.create_task(self.exchange())
        await asyncio.wait_for(self.entered.wait(), 2)
        stopped = await self.command('STOP')
        sealed = self.packets(rid)
        self.assertEqual(sealed[0]['error'], 'stop_drain_timeout')
        self.assertEqual(stopped['network_coverage'], 'partial')
        self.release.set()
        self.assertEqual(await pending, RESPONSE)
        self.assertEqual(self.packets(rid), sealed)

    async def test_off_owns_client_which_never_sends_tls_handshake(self):
        rid = await self.start()
        reader, writer = await asyncio.open_connection('127.0.0.1', self.relay.port)
        try:
            async with asyncio.timeout(1):
                while not self.relay.tasks:
                    await asyncio.sleep(0.001)
            await self.command('OFF')
            self.assertFalse(self.relay.tasks)
            self.assertIsNone(self.relay.server)
            self.assertEqual(await asyncio.wait_for(reader.read(), 1), b'')
            stopped = await self.command('STOP')
            self.assertEqual(self.packets(rid), [])
            self.assertEqual(stopped['network_coverage'], 'partial')
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_off_owns_established_tls_streams(self):
        rid = await self.start()
        self.release.clear()
        pending = asyncio.create_task(self.exchange())
        await asyncio.wait_for(self.entered.wait(), 2)
        await self.command('OFF')
        self.assertFalse(self.relay.tasks)
        self.assertEqual(await pending, b'')
        stopped = await self.command('STOP')
        packet, = self.packets(rid)
        self.assertEqual(packet['error'], 'relay_off_timeout')
        self.assertEqual(stopped['network_coverage'], 'partial')

    async def connect_websocket(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.relay.port,
                                                       ssl=self.pki.client_context(), server_hostname='localhost')
        writer.write(WS_REQUEST)
        await writer.drain()
        response = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2)
        return reader, writer, response

    async def test_wss_preserves_real_frame_wire_and_verified_tls_lifecycle(self):
        self.websocket = True
        rid = await self.start(enable_websocket=True)
        reader, writer, response = await self.connect_websocket()
        try:
            self.assertEqual(response, WS_RESPONSE)
            sent, returned = [], []
            for opcode, payload, fin in ((OP_BINARY, b'synthetic\x00\xff', True),
                                         (OP_TEXT, b'\xe2', False),
                                         (OP_CONT, b'\x82\xac', True),
                                         (OP_PING, b'synthetic-ping', True),
                                         (OP_CLOSE, b'\x03\xe8synthetic-close', True)):
                raw = Frame(opcode, payload, fin=fin).serialize(mask=True)
                sent.append(raw)
                # Split the TLS writes too: write/chunk boundaries are not WS frames.
                writer.write(raw[:1])
                await writer.drain()
                writer.write(raw[1:])
                await writer.drain()
                frame, wire = await get_frame(reader)
                returned.append(wire)
                self.assertEqual(frame.data, payload)
                self.assertEqual(frame.opcode, OP_PONG if opcode == OP_PING else opcode)
            self.assertEqual(await asyncio.wait_for(reader.read(), 2), b'')
            await self.wait_no_handlers()
            stopped = await self.command('STOP')
            rows = self.packets(rid)
            frames = [row for row in rows if row['kind'] == 'websocket_frame']
            self.assertEqual(len(frames), 10)
            self.assertEqual(self.upstream_frames, sent)
            self.assertEqual(self.upstream_responses, returned)
            self.assertEqual({row['kind'] for row in rows},
                             {'websocket_handshake', 'websocket_open', 'websocket_frame', 'websocket_close'})
            self.assertEqual(len({row['connection_id'] for row in rows}), 1)
            for row in rows:
                self.assertEqual(row['transport'], 'TLS')
                self.assertEqual(row['capture_mode'], 'decrypted')
                self.assertTrue(row['tls']['upstream_verified'])
                self.assertTrue(row['tls']['client_version'].startswith('TLSv1.'))
                self.assertTrue(row['tls']['upstream_version'].startswith('TLSv1.'))
            for direction, key, expected in (('client_to_upstream', 'request', sent),
                                             ('upstream_to_client', 'response', returned)):
                actual = [base64.b64decode(row[key]['raw_base64']) for row in frames
                          if row.get(key) and row[key]['direction'] == direction]
                self.assertEqual(actual, expected)
            self.assertEqual(stopped['network_coverage'], 'complete_for_supported_scope')
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_wss_stop_excludes_partial_frame_and_late_close_on_live_connection(self):
        self.websocket = True
        rid = await self.start(enable_websocket=True)
        reader, writer, response = await self.connect_websocket()
        try:
            self.assertEqual(response, WS_RESPONSE)
            raw = Frame(OP_BINARY, b'synthetic-cross-stop').serialize(mask=True)
            writer.write(raw[:-2])
            await writer.drain()
            async with asyncio.timeout(1):
                while not any(state['directions']['client_to_upstream']['frame_in_progress']
                              for state in self.relay.websocket_connections.values()):
                    await asyncio.sleep(0.001)
            stopped = await self.command('STOP')
            sealed = self.packets(rid)
            writer.write(raw[-2:])
            await writer.drain()
            self.assertEqual((await get_frame(reader))[0].data, b'synthetic-cross-stop')
            self.assertEqual(self.packets(rid), sealed)
            self.assertEqual(stopped['network_coverage'], 'partial')
            rid2 = (await self.command('RECORD', device_id='synthetic-tls',
                                       app_id='dev.finsec.synthetic'))['recording_id']
            raw2 = Frame(OP_TEXT, b'synthetic-second-recording').serialize(mask=True)
            writer.write(raw2)
            await writer.drain()
            self.assertEqual((await get_frame(reader))[0].data, b'synthetic-second-recording')
            await self.command('STOP')
            second = self.packets(rid2)
            frames = [row for row in second if row['kind'] == 'websocket_frame']
            self.assertEqual(len(frames), 2)
            self.assertTrue(all(row['context_before_recording'] for row in frames))
            self.assertTrue(all(row['tls']['upstream_verified'] for row in frames))
            writer.write(Frame(OP_CLOSE, b'\x03\xe8').serialize(mask=True))
            await writer.drain()
            self.assertEqual((await get_frame(reader))[0].opcode, OP_CLOSE)
            self.assertEqual(await asyncio.wait_for(reader.read(), 1), b'')
            await self.wait_no_handlers()
            self.assertEqual(self.packets(rid), sealed)
            self.assertEqual(self.packets(rid2), second)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_wss_failed_upstream_certificate_never_upgrades_or_captures_frames(self):
        self.websocket = True
        rid = await self.start(enable_websocket=True, upstream_ca=None)
        reader, writer, response = await self.connect_websocket()
        try:
            self.assertIn(b'502 Bad Gateway', response)
            await reader.read()
            stopped = await self.command('STOP')
            row, = self.packets(rid)
            self.assertEqual(row['kind'], 'websocket_handshake')
            self.assertTrue(row['incomplete'])
            self.assertEqual(row['error'], 'upstream:tls_verification_failed')
            self.assertFalse(row['tls']['upstream_verified'])
            self.assertEqual(self.received, [])
            self.assertEqual(self.upstream_frames, [])
            self.assertEqual(stopped['network_coverage'], 'partial')
            self.assertEqual(stopped['counters']['tls_errors'], 1)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_contexts_ignore_keylog_environment_and_keep_verification(self):
        keylog = Path(self.temp.name) / 'must-not-exist.keys'
        with patch.dict(os.environ, SSLKEYLOGFILE=str(keylog)):
            config = Config(db=self.db, upstream_port=1, listener_cert=self.pki.cert,
                            listener_key=self.pki.key, upstream_tls=True, upstream_ca=self.pki.ca)
            listener, upstream, metadata = tls_contexts(config)
        self.assertEqual(upstream.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(upstream.check_hostname)
        self.assertEqual(listener.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(upstream.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertIsNone(listener.keylog_filename)
        self.assertIsNone(upstream.keylog_filename)
        self.assertFalse(keylog.exists())
        self.assertEqual(metadata['upstream_trust'], 'explicit_ca')

    async def test_config_rejects_incomplete_or_mistyped_tls_options(self):
        cases = [dict(listener_cert=self.pki.cert), dict(listener_key=self.pki.key),
                 dict(listener_cert=str(self.pki.cert), listener_key=self.pki.key),
                 dict(upstream_tls=1), dict(upstream_tls='yes'), dict(upstream_ca=self.pki.ca),
                 dict(upstream_tls=True, upstream_ca=str(self.pki.ca)),
                 dict(upstream_server_name=''), dict(upstream_server_name='localhost/evil'),
                 dict(upstream_server_name='localhost\x00')]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Config(db=self.db, upstream_port=1, **kwargs).validate()


if __name__ == '__main__':
    unittest.main()
