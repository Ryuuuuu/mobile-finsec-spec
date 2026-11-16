"""Subprocess CLI checks, synthetic loopback only."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CLIIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='p2-cli-')
        self.db = Path(self.temp.name) / 'qa.sqlite3'
        self.children = []
        self.deliveries = []

        async def upstream(reader, writer):
            try:
                head = await reader.readuntil(b'\r\n\r\n')
                line = head.split(b'\r\n')[0].decode('ascii')
                self.deliveries.append(line)
                body = json.dumps({'fixture': 'synthetic-only', 'request': line}).encode()
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        self.server = await asyncio.start_server(upstream, '127.0.0.1', 0)
        self.upstream_port = self.server.sockets[0].getsockname()[1]
        self.proc = await self.spawn('relay.py', 'serve', '--db', str(self.db), '--upstream-port', str(self.upstream_port), '--port', '0')
        first = await self.response()
        self.assertEqual(first['result']['relay_state'], 'off')

    async def asyncTearDown(self):
        for proc in self.children:
            if proc.returncode is None:
                proc.kill()
            await proc.communicate()
        self.server.close()
        await self.server.wait_closed()
        self.temp.cleanup()

    async def spawn(self, script, *args):
        proc = await asyncio.create_subprocess_exec(sys.executable, str(ROOT / script), *args,
                                                   stdin=asyncio.subprocess.PIPE,
                                                   stdout=asyncio.subprocess.PIPE,
                                                   stderr=asyncio.subprocess.PIPE)
        self.children.append(proc)
        return proc

    async def response(self):
        return json.loads(await asyncio.wait_for(self.proc.stdout.readline(), 3))

    async def command(self, name, cid, **extra):
        data = dict(schema_version=1, command_id=cid, command=name, **extra)
        self.proc.stdin.write(json.dumps(data).encode() + b'\n')
        await self.proc.stdin.drain()
        result = await self.response()
        self.assertTrue(result['ok'], result)
        return result['result']

    async def query(self, *args):
        proc = await self.spawn('relay.py', 'query', '--db', str(self.db), *args)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), 3)
        self.assertEqual(proc.returncode, 0, stderr)
        result = json.loads(stdout)
        self.assertTrue(result['ok'], result)
        return result['result']

    async def client(self, port, count):
        proc = await self.spawn('fixture.py', 'client', '--port', str(port), '--count', str(count))
        stdout, stderr = await asyncio.wait_for(proc.communicate(), 5)
        self.assertEqual(proc.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)['delivered'], count)

    async def test_live_cli_20_delivery_record_query_and_process_restart(self):
        on = await self.command('ON', 'on-1')
        record = await self.command('RECORD', 'record-1', device_id='synthetic-device', app_id='synthetic.qa')
        await self.client(on['listen_port'], 20)
        stopped = await self.command('STOP', 'stop-1')
        self.assertEqual(stopped['network_coverage'], 'complete_for_supported_scope')
        self.assertEqual(stopped['persisted_packets'], 20)
        self.assertEqual(len(self.deliveries), 20)
        packets = await self.query('--kind', 'packets', '--recording-id', record['recording_id'])
        self.assertEqual(len(packets), 20)
        detail = await self.query('--kind', 'detail', '--packet-id', packets[0]['packet_id'])
        self.proc.stdin.write(b'QUIT\n')
        stdout, stderr = await asyncio.wait_for(self.proc.communicate(), 3)
        self.assertEqual(self.proc.returncode, 0, stderr)
        self.proc = await self.spawn('relay.py', 'serve', '--db', str(self.db), '--upstream-port', str(self.upstream_port), '--port', '0')
        self.assertEqual((await self.response())['result']['relay_state'], 'off')
        self.assertEqual(await self.query('--kind', 'detail', '--packet-id', packets[0]['packet_id']), detail)
        self.proc.stdin.write(b'QUIT\n')
        await asyncio.wait_for(self.proc.communicate(), 3)

    async def test_oversized_physical_line_cannot_execute_suffix_command(self):
        suffix = json.dumps(dict(schema_version=1, command_id='hidden', command='ON')).encode()
        self.proc.stdin.write(b' ' * 8193 + suffix + b'\n')
        await self.proc.stdin.drain()
        self.assertEqual((await self.response())['error'], 'command_too_large')
        self.assertEqual((await self.command('STATUS', 'status'))['relay_state'], 'off')
        self.proc.stdin.write(b'{"schema_version":1,"schema_version":1,"command_id":"duplicate","command":"ON"}\n')
        await self.proc.stdin.drain()
        self.assertEqual((await self.response())['error'], 'invalid_json')

    async def test_stalled_stdout_does_not_block_live_relay(self):
        port = (await self.command('ON', 'on'))['listen_port']
        await self.command('RECORD', 'record', device_id='synthetic-device', app_id='synthetic.qa')
        # Fill stdout and its reader buffer; never consume command responses while
        # verifying independent network delivery through the live service.
        for index in range(300):
            data = dict(schema_version=1, command_id=f'status-{index}', command='STATUS')
            self.proc.stdin.write(json.dumps(data).encode() + b'\n')
        await self.proc.stdin.drain()
        await asyncio.sleep(0.1)
        await self.client(port, 20)
        self.assertEqual(len(self.deliveries), 20)
        # Resume the consumer so normal shutdown can drain its outputs and storage.
        self.proc.stdin.write(b'QUIT\n')
        stdout, stderr = await asyncio.wait_for(self.proc.communicate(), 5)
        self.assertEqual(self.proc.returncode, 0, stderr)
        records = await self.query('--kind', 'recordings')
        self.assertEqual(records[0]['persisted_packets'], 20)
        self.assertEqual(records[0]['network_coverage'], 'complete_for_supported_scope')


if __name__ == '__main__':
    unittest.main()
