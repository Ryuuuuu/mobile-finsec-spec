"""P2 synthetic-only, fixed loopback HTTP/1.1 relay. No device integration."""
from __future__ import annotations

import argparse
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid

VERSION = 1
PARSER = 'p2-http1-content-length/1'
SCOPE = 'HTTP/1.1 origin-form GET/POST; Content-Length; one transaction per connection'


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def envelope(result=None, error=None):
    value = dict(schema_version=VERSION, event_id=uid(), timestamp=now(), ok=error is None)
    value['error' if error else 'result'] = error if error else result
    return value


def clone(value):
    return json.loads(json.dumps(value))


@dataclass
class Config:
    db: Path
    upstream_port: int
    listen_port: int = 0
    host: str = '127.0.0.1'
    relay_off_drain_ms: int = 5000
    record_stop_response_drain_ms: int = 2000
    io_timeout: float = 2.0
    queue_size: int = 128
    max_body_bytes: int = 1048576
    max_header_bytes: int = 16384
    max_transactions: int = 1000
    max_connections: int = 64
    capture_body_bytes: int = 65536

    def validate(self):
        if self.host != '127.0.0.1':
            raise ValueError('loopback_ipv4_only')
        for port in (self.listen_port, self.upstream_port):
            if type(port) is not int or not 0 <= port <= 65535:
                raise ValueError('invalid_port')
        if self.upstream_port == 0:
            raise ValueError('upstream_port_required')
        if self.listen_port and self.listen_port == self.upstream_port:
            raise ValueError('relay_upstream_port_conflict')
        for name in ('queue_size', 'max_body_bytes', 'max_header_bytes', 'max_transactions',
                     'max_connections', 'capture_body_bytes'):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= 16777216:
                raise ValueError('invalid_limit:' + name)
        for name in ('io_timeout', 'relay_off_drain_ms', 'record_stop_response_drain_ms'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 60000:
                raise ValueError('invalid_timeout:' + name)


class FileLock:
    """Single serving process per DB; kernel releases the lock after a crash."""
    def __init__(self, path):
        self.file = open(str(path) + '.lock', 'a+b')
        if self.file.tell() == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('database_in_use') from None

    def close(self):
        self.file.close()


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='p2-store')
        self.fail_writes = False  # deterministic test fault, never a CLI option
        self.write_delay_seconds = 0.0  # packet writer fault injection only
        self.conn = None
        self.lock = None

    async def run(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(self.executor, function, *args)

    async def start(self):
        await self.run(self._start)

    def _start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(self.path)
        try:
            self.conn = sqlite3.connect(self.path, timeout=0.2)
            version = self.conn.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, VERSION):
                raise ValueError('unsupported_database_version')
            self.conn.execute('PRAGMA journal_mode=WAL')
            self.conn.execute('PRAGMA synchronous=FULL')
            self.conn.executescript('''
                CREATE TABLE IF NOT EXISTS recordings (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS packets (id TEXT PRIMARY KEY, recording_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL, data TEXT NOT NULL, request BLOB, response BLOB);
                CREATE INDEX IF NOT EXISTS packet_recording ON packets(recording_id,sequence);
                CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL);
                PRAGMA user_version=1;
            ''')
            for rid, data in self.conn.execute('SELECT id,data FROM recordings').fetchall():
                record = json.loads(data)
                if record['status'] in ('recording', 'stopping'):
                    record.update(status='interrupted', network_coverage='partial', ended_at=now())
                    record['gaps'].append(dict(reason='process_interrupted', timestamp=now()))
                    self.conn.execute('UPDATE recordings SET data=? WHERE id=?', (json.dumps(record), rid))
                    for pid, pdata in self.conn.execute('SELECT id,data FROM packets WHERE recording_id=?', (rid,)).fetchall():
                        packet = json.loads(pdata)
                        if packet['incomplete']:
                            packet['error'] = 'process_interrupted'
                            self.conn.execute('UPDATE packets SET data=? WHERE id=?', (json.dumps(packet), pid))
            self.conn.commit()
        except Exception:
            if self.conn:
                self.conn.close()
                self.conn = None
            self.lock.close()
            self.lock = None
            raise

    def _check_write(self):
        if self.fail_writes:
            raise sqlite3.OperationalError('injected_storage_error')

    def _record(self, record):
        self._check_write()
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO recordings VALUES (?,?)',
                              (record['recording_id'], json.dumps(record)))

    async def record(self, record):
        await self.run(self._record, clone(record))

    def _packet(self, packet):
        if self.write_delay_seconds:
            time.sleep(self.write_delay_seconds)
        self._check_write()
        metadata = clone(packet)
        blobs = []
        for key in ('request', 'response'):
            message = metadata[key]
            blobs.append(base64.b64decode(message.pop('raw_base64')) if message else None)
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO packets VALUES (?,?,?,?,?,?)',
                              (metadata['packet_id'], metadata['recording_id'], metadata['sequence'],
                               json.dumps(metadata), *blobs))

    async def packet(self, packet):
        await self.run(self._packet, packet)

    def _command_get(self, cid):
        # Independent WAL reader: STOP admission must not queue behind a slow
        # payload write in the capture executor.
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.2)) as conn:
            row = conn.execute('SELECT digest,result FROM commands WHERE id=?', (cid,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def _finalize_packets(self, rid):
        self._check_write()
        with self.conn:
            rows = self.conn.execute('SELECT id,data FROM packets WHERE recording_id=?', (rid,)).fetchall()
            for pid, data in rows:
                packet = json.loads(data)
                if packet['incomplete'] and packet['error'] is None:
                    packet['error'] = 'capture_write_lost'
                    self.conn.execute('UPDATE packets SET data=? WHERE id=?', (json.dumps(packet), pid))
            return len(rows)

    def _command_save(self, cid, digest, result):
        self._check_write()
        with self.conn:
            self.conn.execute('INSERT INTO commands VALUES (?,?,?)', (cid, digest, json.dumps(result)))

    async def close(self):
        def cleanup():
            if self.conn:
                self.conn.close()
                self.conn = None
            if self.lock:
                self.lock.close()
                self.lock = None
        await self.run(cleanup)
        self.executor.shutdown(wait=True)


def query(db, kind='recordings', recording_id=None, packet_id=None, limit=100, offset=0):
    """Separate read-only connection: queries never run on the relay event loop."""
    if kind not in ('recordings', 'packets', 'detail') or type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        return envelope(error='invalid_query')
    try:
        with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True, timeout=0.2)) as conn:
            if conn.execute('PRAGMA user_version').fetchone()[0] != VERSION:
                return envelope(error='unsupported_database_version')
            if kind == 'recordings':
                data = [json.loads(row[0]) for row in conn.execute('SELECT data FROM recordings ORDER BY rowid DESC LIMIT ? OFFSET ?', (limit, offset))]
            elif kind == 'packets':
                if not recording_id:
                    return envelope(error='recording_id_required')
                data = [json.loads(row[0]) for row in conn.execute('SELECT data FROM packets WHERE recording_id=? ORDER BY sequence LIMIT ? OFFSET ?', (recording_id, limit, offset))]
            else:
                row = conn.execute('SELECT data,request,response FROM packets WHERE id=?', (packet_id,)).fetchone()
                if not row:
                    return envelope(error='packet_not_found')
                data = json.loads(row[0])
                for key, raw in zip(('request', 'response'), row[1:]):
                    if data[key] is not None:
                        data[key]['raw_base64'] = base64.b64encode(raw).decode('ascii')
        return envelope(data)
    except (OSError, sqlite3.Error):
        return envelope(error='storage_read_error')


class ProtocolError(Exception):
    pass


async def read_message(reader, config, *, response=False):
    try:
        head = await reader.readuntil(b'\r\n\r\n')
    except asyncio.LimitOverrunError:
        raise ProtocolError('header_too_large') from None
    except asyncio.IncompleteReadError:
        raise ProtocolError('unexpected_eof') from None
    if len(head) > config.max_header_bytes:
        raise ProtocolError('header_too_large')
    lines = head[:-4].split(b'\r\n')
    first = lines[0]
    if response:
        if not re.fullmatch(rb'HTTP/1\.1 [2-5][0-9][0-9] [\x20-\x7e]*', first):
            raise ProtocolError('unsupported_response_line')
    elif not re.fullmatch(rb'(GET|POST) /[\x21-\x7e]* HTTP/1\.1', first) or b'#' in first:
        raise ProtocolError('unsupported_request_line')
    headers = {}
    for line in lines[1:]:
        if b':' not in line:
            raise ProtocolError('invalid_header')
        name, value = line.split(b':', 1)
        if not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) or re.search(rb'[^\x09\x20-\x7e]', value):
            raise ProtocolError('invalid_header')
        name = name.lower().decode('ascii')
        if name in headers:
            raise ProtocolError('duplicate_header')
        headers[name] = value.strip()
    if any(key in headers for key in ('transfer-encoding', 'upgrade', 'expect', 'trailer')):
        raise ProtocolError('unsupported_framing')
    if not response and not headers.get('host'):
        raise ProtocolError('host_required')
    length_raw = headers.get('content-length', b'')
    if response and not length_raw:
        raise ProtocolError('response_content_length_required')
    if length_raw and not re.fullmatch(rb'[0-9]{1,10}', length_raw):
        raise ProtocolError('invalid_content_length')
    if 'content-length' in headers and not length_raw:
        raise ProtocolError('invalid_content_length')
    length = int(length_raw or 0)
    if length > config.max_body_bytes:
        raise ProtocolError('body_too_large')
    if response and first[9:12] in (b'204', b'304') and length:
        raise ProtocolError('unsupported_bodyless_response')
    try:
        body = await reader.readexactly(length)
    except asyncio.IncompleteReadError:
        raise ProtocolError('incomplete_body') from None
    return head + body


def counter_set():
    return dict(observed=0, captured=0, dropped=0, storage_errors=0, truncated=0,
                decoder_errors=0, upstream_errors=0, connection_rejections=0)


class Relay:
    def __init__(self, config):
        config.validate()
        self.config = config
        self.store = Store(config.db)
        self.session_id = uid()
        self.server = None
        self.port = config.listen_port
        self.relay_state = 'starting'
        self.command_lock = asyncio.Lock()
        self.queue = asyncio.Queue(maxsize=config.queue_size)
        self.tasks = set()
        self.pending = {}
        self.active_recording = None
        self.last_recording = None
        self.counters = counter_set()
        self.writer_task = None
        self.started = False
        self.closed = False
        self.last_error = None
        self.command_cache = {}

    async def start(self):
        try:
            await self.store.start()
        except Exception:
            await self.store.close()
            raise
        self.writer_task = asyncio.create_task(self._writer())
        self.relay_state = 'off'
        self.started = True

    def status(self):
        return clone(dict(session_id=self.session_id, run_id=None, process_state='running',
                          relay_state=self.relay_state, listen_port=self.port,
                          active_recording=self.active_recording, last_recording=self.last_recording,
                          counters=self.counters, last_error=self.last_error,
                          active_connections=len(self.tasks), capture_queue_depth=self.queue.qsize(),
                          supported_scope=SCOPE, app_routing_verified=False, attribution='unverified'))

    def _count(self, name, record=None):
        self.counters[name] += 1
        if record is not None:
            record['counters'][name] += 1
            if name not in ('observed', 'captured'):
                record['network_coverage'] = 'partial'

    async def _writer(self):
        while True:
            item = await self.queue.get()
            try:
                if item is None:
                    return
                packet, record = item
                try:
                    await self.store.packet(packet)
                except (OSError, sqlite3.Error):
                    self._count('storage_errors', record)
                    self.last_error = 'storage_write_error'
            finally:
                self.queue.task_done()

    def _emit(self, packet, record):
        try:
            self.queue.put_nowait((clone(packet), record))
        except asyncio.QueueFull:
            self._count('dropped', record)

    def _message(self, raw, direction, record):
        stored = raw[:self.config.capture_body_bytes]
        truncated = len(stored) != len(raw)
        if truncated:
            self._count('truncated', record)
        return dict(direction=direction, raw_base64=base64.b64encode(stored).decode('ascii'),
                    sha256=hashlib.sha256(raw).hexdigest(), stored_sha256=hashlib.sha256(stored).hexdigest(),
                    size=len(raw), stored_size=len(stored), truncated=truncated,
                    timestamp=now(), monotonic=time.monotonic())

    def _begin(self, request, connection_id, accepted_at):
        self._count('observed', self.active_recording)
        record = self.active_recording
        if record is None:
            return None
        if record['counters']['captured'] >= self.config.max_transactions:
            self._count('dropped', record)
            return None
        self._count('captured', record)
        packet = dict(schema_version=VERSION, packet_id=uid(), recording_id=record['recording_id'],
                      event_id=uid(),
                      session_id=self.session_id, run_id=None, connection_id=connection_id,
                      sequence=record['counters']['captured'], timestamp=now(), monotonic=time.monotonic(),
                      kind='http_transaction', transport='TCP', protocol='HTTP/1.1', parser_version=PARSER,
                      endpoint=dict(host=self.config.host, port=self.config.upstream_port),
                      context_before_recording=accepted_at < record['monotonic_start'],
                      request=self._message(request, 'client_to_upstream', record), response=None,
                      incomplete=True, error=None, received_after_stop=False)
        self.pending[packet['packet_id']] = (packet, record)
        self._emit(packet, record)
        return packet

    def _finish(self, packet, response=None, error=None):
        if packet is None:
            return
        pair = self.pending.pop(packet['packet_id'], None)
        if pair is None:
            return  # STOP has finalized this packet; late traffic is forwarded only.
        _, record = pair
        if response is not None:
            packet['response'] = self._message(response, 'upstream_to_client', record)
        packet['incomplete'] = error is not None
        packet['error'] = error
        packet['received_after_stop'] = record['status'] == 'stopping' and response is not None
        if error:
            record['network_coverage'] = 'partial'
        packet['completed_at'] = now()
        self._emit(packet, record)

    def _accept(self, reader, writer):
        if self.relay_state != 'on' or len(self.tasks) >= self.config.max_connections:
            self._count('connection_rejections', self.active_recording)
            writer.close()
            return
        task = asyncio.create_task(self._handle(reader, writer))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _handle(self, reader, writer):
        packet = None
        upstream = None
        connection_id = uid()
        accepted_at = time.monotonic()
        stage = 'request'
        try:
            request = await asyncio.wait_for(read_message(reader, self.config), self.config.io_timeout)
            packet = self._begin(request, connection_id, accepted_at)
            stage = 'upstream'
            async with asyncio.timeout(self.config.io_timeout):
                upstream_reader, upstream = await asyncio.open_connection(self.config.host, self.config.upstream_port,
                                                                         limit=self.config.max_header_bytes)
                # Force close on the actual forwarded request. Capture retains client wire bytes.
                lines = request.split(b'\r\n\r\n', 1)
                head = b'\r\n'.join(line for line in lines[0].split(b'\r\n') if not line.lower().startswith(b'connection:'))
                upstream.write(head + b'\r\nConnection: close\r\n\r\n' + lines[1])
                await upstream.drain()
                response = await read_message(upstream_reader, self.config, response=True)
            self._finish(packet, response=response)
            stage = 'client'
            writer.write(response)
            await asyncio.wait_for(writer.drain(), self.config.io_timeout)
        except asyncio.CancelledError:
            self._finish(packet, error='relay_off_timeout')
            raise
        except (OSError, TimeoutError, ProtocolError) as exc:
            record = self.pending.get(packet['packet_id'], (None, None))[1] if packet else self.active_recording
            error = str(exc) if isinstance(exc, ProtocolError) else ('timeout' if isinstance(exc, TimeoutError) else 'connection_error')
            self.last_error = stage + ':' + error
            if stage == 'request':
                self._count('decoder_errors', record)
            elif stage == 'upstream':
                self._count('upstream_errors', record)
                if isinstance(exc, ProtocolError):
                    self._count('decoder_errors', record)
            self._finish(packet, error=stage + ':' + error)
            if stage != 'client':
                code = b'400 Bad Request' if stage == 'request' else b'502 Bad Gateway'
                writer.write(b'HTTP/1.1 ' + code + b'\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                try:
                    await asyncio.wait_for(writer.drain(), self.config.io_timeout)
                except (OSError, TimeoutError):
                    pass
        finally:
            for stream in (upstream, writer):
                if stream:
                    stream.close()
                    try:
                        await asyncio.wait_for(stream.wait_closed(), 0.5)
                    except (OSError, TimeoutError, asyncio.CancelledError):
                        pass

    async def command(self, payload):
        required = {'schema_version', 'command_id', 'command'}
        if not isinstance(payload, dict) or not required <= payload.keys():
            return envelope(error='invalid_command')
        cmd = payload['command']
        extra = {'device_id', 'app_id'} if cmd == 'RECORD' else set()
        if payload.keys() != required | extra or type(payload['schema_version']) is not int or payload['schema_version'] != VERSION:
            return envelope(error='invalid_command')
        if cmd not in ('ON', 'OFF', 'RECORD', 'STOP', 'STATUS') or not isinstance(payload['command_id'], str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', payload['command_id']):
            return envelope(error='invalid_command')
        if cmd == 'RECORD' and any(not isinstance(payload[key], str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', payload[key]) for key in extra):
            return envelope(error='invalid_target')
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        async with self.command_lock:
            if cmd == 'STATUS':
                return envelope(self.status())  # query, not an idempotent mutation
            try:
                previous = self.command_cache.get(payload['command_id'])
                if previous is None:
                    previous = await asyncio.to_thread(self.store._command_get, payload['command_id'])
                if previous:
                    return clone(previous[1]) if previous[0] == digest else envelope(error='command_conflict')
                if len(self.command_cache) >= 128:
                    return envelope(error='command_recovery_required')
                result = await self._dispatch(cmd, payload)
                response = envelope({**result, 'session_id': self.session_id})
                # Reserve the applied result before the durable acknowledgement. A failed
                # command journal must not reapply a mutation on a same-process retry.
                self.command_cache[payload['command_id']] = (digest, response)
                try:
                    await self.store.run(self.store._command_save, payload['command_id'], digest, response)
                    del self.command_cache[payload['command_id']]
                except (OSError, sqlite3.Error):
                    response['ok'] = False
                    response['error'] = 'command_journal_error'
                    response['applied'] = True
                    response['durable_command'] = False
                    self.last_error = 'command_journal_error'
                    self._count('storage_errors', self.active_recording)
                return clone(response)
            except (OSError, sqlite3.Error):
                self.last_error = 'storage_write_error'
                affected = self.active_recording
                if cmd == 'STOP' and self.last_recording and self.last_recording['status'] == 'failed':
                    affected = self.last_recording
                self._count('storage_errors', affected)
                response = envelope(error='storage_write_error')
                response['state_may_have_changed'] = True
                self.command_cache[payload['command_id']] = (digest, response)
                return clone(response)
            except ValueError as exc:
                response = envelope(error=str(exc))
                self.command_cache[payload['command_id']] = (digest, response)
                return clone(response)

    async def _dispatch(self, cmd, payload):
        if cmd == 'ON':
            if self.relay_state == 'on':
                return dict(relay_state='on', listen_port=self.port)
            self.relay_state = 'enabling'
            try:
                self.server = await asyncio.start_server(self._accept, self.config.host, self.config.listen_port,
                                                         limit=self.config.max_header_bytes)
            except OSError:
                self.relay_state = 'error'
                self.last_error = 'listen_failed'
                raise ValueError('listen_failed') from None
            self.port = self.server.sockets[0].getsockname()[1]
            self.relay_state = 'on'
            if self.active_recording:
                record = self.active_recording
                if record['gaps']:
                    record['network_coverage'] = 'partial'
                if record['gaps'] and 'ended_at' not in record['gaps'][-1]:
                    record['gaps'][-1]['ended_at'] = now()
                await self.store.record(record)
            return dict(relay_state='on', listen_port=self.port)
        if cmd == 'OFF':
            await self._off()
            return dict(relay_state='off')
        if cmd == 'RECORD':
            if self.active_recording:
                raise ValueError('recording_busy')
            if self.relay_state not in ('on', 'off'):
                raise ValueError('relay_not_ready')
            record = dict(schema_version=VERSION, recording_id=uid(), session_id=self.session_id, run_id=None,
                          event_id=uid(), timestamp=now(), started_at=now(), monotonic_start=time.monotonic(),
                          status='recording', network_coverage='unknown' if self.relay_state == 'on' else 'none',
                          supported_scope=SCOPE, parser_version=PARSER, counters=counter_set(), gaps=[],
                          attribution=dict(device_id=payload['device_id'], app_id=payload['app_id'], confidence='unverified',
                                           method='explicit_synthetic_labels', limitations=['No device routing or app identity verified']),
                          config=dict(record_stop_response_drain_ms=self.config.record_stop_response_drain_ms,
                                      relay_off_drain_ms=self.config.relay_off_drain_ms,
                                      capture_body_bytes=self.config.capture_body_bytes,
                                      max_transactions=self.config.max_transactions))
            if self.relay_state == 'off':
                record['gaps'].append(dict(reason='relay_off', started_at=now()))
            await self.store.record(record)
            record['prepared_at'] = record['started_at']
            record['started_at'] = now()
            record['monotonic_start'] = time.monotonic()
            record['start_marker_id'] = uid()
            self.active_recording = record
            self.last_recording = record
            return dict(recording_id=record['recording_id'], status='recording')
        if cmd == 'STOP':
            if not self.active_recording:
                return dict(recording_id=self.last_recording['recording_id'] if self.last_recording else None, status='idle')
            record = self.active_recording
            self.active_recording = None  # seal without awaiting storage or drain
            record.update(status='stopping', stop_requested_at=now(), monotonic_stop=time.monotonic(), stop_marker_id=uid())
            deadline = asyncio.get_running_loop().time() + self.config.record_stop_response_drain_ms / 1000
            while self.pending and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(min(0.005, max(0, deadline - asyncio.get_running_loop().time())))
            for packet, _ in list(self.pending.values()):
                self._finish(packet, error='stop_drain_timeout')
            await self.queue.join()
            if record['network_coverage'] != 'partial':
                record['network_coverage'] = ('complete_for_supported_scope' if record['counters']['observed'] else 'none')
            record.update(status='interrupted' if record['counters']['storage_errors'] else 'completed', ended_at=now())
            try:
                record['persisted_packets'] = await self.store.run(self.store._finalize_packets, record['recording_id'])
                await self.store.record(record)
            except (OSError, sqlite3.Error):
                record.update(status='failed', network_coverage='partial')
                raise
            return clone(record)
        raise ValueError('invalid_command')

    async def _off(self):
        if self.relay_state == 'off':
            return
        self.relay_state = 'draining'
        server = self.server
        if self.server:
            self.server.close()
            self.server = None
        record = self.active_recording
        if record:
            record['gaps'].append(dict(reason='relay_off', started_at=now()))
            record['network_coverage'] = 'partial'
        if self.tasks:
            _, pending = await asyncio.wait(list(self.tasks), timeout=self.config.relay_off_drain_ms / 1000)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        if server:
            await server.wait_closed()
        self.relay_state = 'off'
        if record:
            await self.store.record(record)

    async def close(self):
        if not self.started or self.closed:
            return
        async with self.command_lock:
            try:
                if self.active_recording:
                    await self._dispatch('STOP', {})
            finally:
                try:
                    await self._off()
                finally:
                    await self.queue.join()
                    await self.queue.put(None)
                    await self.writer_task
                    await self.store.close()
                    self.closed = True
                    self.relay_state = 'off'


async def serve(args):
    relay = Relay(Config(db=args.db, upstream_port=args.upstream_port, listen_port=args.port))
    await relay.start()
    async def output(value):
        # A stalled terminal blocks its own thread, never socket forwarding.
        await asyncio.to_thread(print, json.dumps(value, ensure_ascii=False), flush=True)
    try:
        await output(envelope(relay.status()))
        while True:
            line = await asyncio.to_thread(sys.stdin.readline, 8193)
            if not line or line.strip().upper() == 'QUIT':
                break
            if len(line) > 8192:
                while line and not line.endswith('\n'):
                    line = await asyncio.to_thread(sys.stdin.readline, 8193)
                await output(envelope(error='command_too_large'))
                continue
            try:
                def unique_pairs(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError('duplicate_key')
                        result[key] = value
                    return result
                command = json.loads(line, object_pairs_hook=unique_pairs)
            except (ValueError, json.JSONDecodeError):
                await output(envelope(error='invalid_json'))
                continue
            await output(await relay.command(command))
    finally:
        await relay.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    run = sub.add_parser('serve')
    run.add_argument('--db', type=Path, required=True)
    run.add_argument('--upstream-port', type=int, required=True)
    run.add_argument('--port', type=int, default=8780)
    view = sub.add_parser('query')
    view.add_argument('--db', type=Path, required=True)
    view.add_argument('--kind', choices=('recordings', 'packets', 'detail'), default='recordings')
    view.add_argument('--recording-id')
    view.add_argument('--packet-id')
    view.add_argument('--limit', type=int, default=100)
    view.add_argument('--offset', type=int, default=0)
    args = parser.parse_args()
    try:
        if args.action == 'serve':
            asyncio.run(serve(args))
        else:
            result = query(args.db, args.kind, args.recording_id, args.packet_id, args.limit, args.offset)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['ok'] else 1
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(json.dumps(envelope(error=type(exc).__name__), ensure_ascii=False))
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
