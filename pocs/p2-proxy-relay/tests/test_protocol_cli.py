"""Real CLI WSS smoke with ephemeral PKI and independent websockets peers."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from tls_fixture import TLSFixture

ROOT = Path(__file__).resolve().parents[1]


class ProtocolCLITests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.pki_temp = tempfile.TemporaryDirectory(prefix='p2-cli-synthetic-pki-')
        cls.addClassCleanup(cls.pki_temp.cleanup)
        cls.pki = TLSFixture(Path(cls.pki_temp.name))

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='p2-cli-wss-')
        self.db = Path(self.temp.name) / 'capture.sqlite3'
        self.children = []
        self.deliveries = []

        async def upstream(connection):
            async for message in connection:
                self.deliveries.append(message)
                await connection.send(message)

        self.server = await serve(upstream, '127.0.0.1', 0,
                                  ssl=self.pki.server_context(), compression=None,
                                  ping_interval=None, close_timeout=1)
        self.upstream_port = self.server.sockets[0].getsockname()[1]
        self.proc = await self.start_relay()

    async def asyncTearDown(self):
        for proc in self.children:
            if proc.returncode is None:
                proc.kill()
            await proc.communicate()
        self.server.close()
        await self.server.wait_closed()
        self.temp.cleanup()

    async def spawn(self, *args):
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(ROOT / 'relay.py'), *map(str, args),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=ROOT)
        self.children.append(proc)
        return proc

    async def start_relay(self):
        proc = await self.spawn(
            'serve', '--db', self.db, '--upstream-port', self.upstream_port,
            '--port', 0, '--websocket', '--listener-cert', self.pki.cert,
            '--listener-key', self.pki.key, '--upstream-tls', '--upstream-ca', self.pki.ca,
            '--upstream-server-name', 'localhost')
        first = json.loads(await asyncio.wait_for(proc.stdout.readline(), 5))
        self.assertTrue(first['ok'], first)
        self.assertEqual(first['schema_version'], 1)
        self.assertEqual(first['result']['relay_state'], 'off')
        self.assertTrue(first['result']['websocket_enabled'])
        self.assertTrue(first['result']['tls']['listener_enabled'])
        self.assertTrue(first['result']['tls']['upstream_enabled'])
        return proc

    async def command(self, operation, command_id, **kwargs):
        self.proc.stdin.write(json.dumps(dict(schema_version=1, command_id=command_id,
                                             command=operation, **kwargs)).encode() + b'\n')
        await self.proc.stdin.drain()
        response = json.loads(await asyncio.wait_for(self.proc.stdout.readline(), 5))
        self.assertTrue(response['ok'], response)
        self.assertEqual(response['schema_version'], 1)
        return response['result']

    async def query(self, *args):
        proc = await self.spawn('query', '--db', self.db, *args)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), 5)
        self.assertEqual(proc.returncode, 0, stderr)
        self.assertEqual(stderr, b'')
        response = json.loads(stdout)
        self.assertTrue(response['ok'], response)
        self.assertEqual(response['schema_version'], 1)
        return response['result']

    async def stop_process(self):
        self.proc.stdin.write(b'QUIT\n')
        await self.proc.stdin.drain()
        stdout, stderr = await asyncio.wait_for(self.proc.communicate(), 5)
        self.assertEqual(self.proc.returncode, 0, stderr)
        self.assertEqual(stdout, b'')
        self.assertEqual(stderr, b'')

    async def test_cli_wss_frames_stop_seal_query_and_restart(self):
        on = await self.command('ON', 'wss-on')
        recording = await self.command('RECORD', 'wss-record', device_id='synthetic-device',
                                       app_id='synthetic.qa.wss')
        rid = recording['recording_id']
        messages = ['synthetic TLS text \u20ac', b'synthetic-binary\x00\xff']
        async with connect(f"wss://localhost:{on['listen_port']}/synthetic-cli",
                           ssl=self.pki.client_context(), proxy=None, compression=None,
                           ping_interval=None, open_timeout=3, close_timeout=1) as client:
            for message in messages:
                await client.send(message)
                self.assertEqual(await asyncio.wait_for(client.recv(), 3), message)
            stopped = await self.command('STOP', 'wss-stop')
            self.assertEqual(stopped['network_coverage'], 'complete_for_supported_scope')
            self.assertEqual(stopped['counters']['websocket_frames'], 4)
            self.assertEqual(stopped['persisted_packets'], 6)
            self.assertEqual((await self.command('STATUS', 'wss-status'))['relay_state'], 'on')
            packets = await self.query('--kind', 'packets', '--recording-id', rid)
            frames = [packet for packet in packets if packet['kind'] == 'websocket_frame']
            self.assertEqual(len(frames), 4)
            expected_payloads = [message.encode() if isinstance(message, str) else message
                                 for message in messages]
            expected_hashes = {hashlib.sha256(payload).hexdigest() for payload in expected_payloads}
            for direction in ('client_to_upstream', 'upstream_to_client'):
                matching = [frame for frame in frames if frame['direction'] == direction]
                self.assertEqual(len(matching), 2)
                self.assertEqual({frame['websocket']['payload_sha256'] for frame in matching},
                                 expected_hashes)
            details = []
            for frame in frames:
                self.assertEqual(frame['transport'], 'TLS')
                self.assertEqual(frame['capture_mode'], 'decrypted')
                self.assertTrue(frame['tls']['upstream_verified'])
                self.assertEqual(frame['tls']['upstream_trust'], 'explicit_ca')
                detail = await self.query('--kind', 'detail', '--packet-id', frame['packet_id'])
                details.append(detail)
                field = 'request' if frame['direction'] == 'client_to_upstream' else 'response'
                wire = base64.b64decode(detail[field]['raw_base64'])
                self.assertEqual(hashlib.sha256(wire).hexdigest(), detail[field]['sha256'])
                self.assertEqual(len(wire), detail[field]['size'])
                if field == 'response':
                    self.assertTrue(any(wire.endswith(payload) for payload in expected_payloads))
            records = await self.query('--kind', 'recordings')
            self.assertEqual(len(records), 1)
            late = b'synthetic-after-stop'
            await client.send(late)
            self.assertEqual(await asyncio.wait_for(client.recv(), 3), late)
        self.assertEqual(self.deliveries, messages + [late])
        # Late data and the real close handshake must not append or mutate records.
        self.assertEqual(await self.query('--kind', 'packets', '--recording-id', rid), packets)
        self.assertEqual(await self.query('--kind', 'recordings'), records)
        await self.stop_process()
        self.proc = await self.start_relay()
        self.assertEqual(await self.query('--kind', 'recordings'), records)
        for expected in details:
            actual = await self.query('--kind', 'detail', '--packet-id', expected['packet_id'])
            self.assertEqual(actual, expected)
        await self.stop_process()


if __name__ == '__main__':
    unittest.main()
