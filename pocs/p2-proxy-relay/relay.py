"""P2 synthetic-only fixed loopback HTTP(S) and optional WS(S) capture relay."""
from __future__ import annotations

import argparse
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sqlite3
import ssl
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
    listener_cert: Path | None = None
    listener_key: Path | None = None
    upstream_tls: bool = False
    upstream_ca: Path | None = None
    upstream_server_name: str = 'localhost'
    enable_websocket: bool = False
    max_websocket_frame_bytes: int = 1048576
    max_websocket_message_bytes: int = 1048576
    websocket_idle_timeout: float = 30.0

    def validate(self):
        if type(self.enable_websocket) is not bool:
            raise ValueError('invalid_enable_websocket')
        for name in ('listener_cert', 'listener_key', 'upstream_ca'):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Path):
                raise ValueError('invalid_tls_path:' + name)
        if (self.listener_cert is None) != (self.listener_key is None):
            raise ValueError('listener_certificate_key_pair_required')
        if type(self.upstream_tls) is not bool:
            raise ValueError('invalid_upstream_tls')
        if self.upstream_ca is not None and not self.upstream_tls:
            raise ValueError('upstream_ca_requires_tls')
        if (not isinstance(self.upstream_server_name, str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', self.upstream_server_name)):
            raise ValueError('invalid_upstream_server_name')
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
                     'max_connections', 'capture_body_bytes', 'max_websocket_frame_bytes',
                     'max_websocket_message_bytes'):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= 16777216:
                raise ValueError('invalid_limit:' + name)
        for name in ('io_timeout', 'relay_off_drain_ms', 'record_stop_response_drain_ms', 'websocket_idle_timeout'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 60000:
                raise ValueError('invalid_timeout:' + name)


def tls_contexts(config):
    """Explicit contexts never inherit SSLKEYLOGFILE or disable verification."""
    listener = upstream = None
    metadata = dict(configuration_version=1, listener_enabled=config.listener_cert is not None,
                    upstream_enabled=config.upstream_tls, minimum_version='TLSv1.2',
                    listener_certificate_sha256=None, upstream_ca_sha256=[],
                    upstream_trust='disabled', upstream_server_name=None)
    if config.listener_cert is not None:
        listener = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        listener.minimum_version = ssl.TLSVersion.TLSv1_2
        listener.set_alpn_protocols(['http/1.1'])
        # An encrypted key must fail without prompting on the command channel.
        listener.load_cert_chain(config.listener_cert, config.listener_key, password='')
        pem = config.listener_cert.read_text(encoding='ascii')
        certificate = re.search(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',
                                pem, re.DOTALL)
        if certificate is None:
            raise ValueError('listener_certificate_invalid')
        metadata['listener_certificate_sha256'] = hashlib.sha256(
            ssl.PEM_cert_to_DER_cert(certificate.group())).hexdigest()
    if config.upstream_tls:
        upstream = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        upstream.minimum_version = ssl.TLSVersion.TLSv1_2
        upstream.set_alpn_protocols(['http/1.1'])
        # PROTOCOL_TLS_CLIENT defaults require chain and hostname verification.
        if config.upstream_ca is None:
            upstream.load_default_certs(ssl.Purpose.SERVER_AUTH)
            metadata['upstream_trust'] = 'system'
        else:
            upstream.load_verify_locations(cafile=config.upstream_ca)
            metadata['upstream_trust'] = 'explicit_ca'
            # Snapshot the supplied CA bundle, not extra trust/distrust entries
            # which the Python/OpenSSL runtime may preload into its store.
            certificates = re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',
                                      config.upstream_ca.read_text(encoding='ascii'), re.DOTALL)
            metadata['upstream_ca_sha256'] = sorted(
                hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert)).hexdigest() for cert in certificates)
        metadata['upstream_server_name'] = config.upstream_server_name
    return listener, upstream, metadata


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
    if any(key in headers for key in ('transfer-encoding', 'expect', 'trailer')):
        raise ProtocolError('unsupported_framing')
    if 'upgrade' in headers:
        if response or not config.enable_websocket or headers['upgrade'].lower() != b'websocket':
            raise ProtocolError('unsupported_framing')
        if not first.startswith(b'GET ') or headers.get('content-length', b'0') != b'0':
            raise ProtocolError('unsupported_websocket_body')
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
                decoder_errors=0, upstream_errors=0, connection_rejections=0, tls_errors=0,
                http_transactions=0, websocket_handshakes=0, websocket_frames=0, websocket_events=0)


class Relay:
    def __init__(self, config):
        config.validate()
        self.config = config
        self.websocket_connections = {}
        self.websocket_module = None
        if config.enable_websocket:
            spec = importlib.util.spec_from_file_location('p2_websocket_relay', Path(__file__).with_name('websocket_relay.py'))
            self.websocket_module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(self.websocket_module)
            except ImportError:
                raise ValueError('websocket_dependency_required:install_p2_requirements') from None
        self.supported_scope = SCOPE + ('; RFC6455 WS frames, no extensions/subprotocols' if config.enable_websocket else '')
        self.listener_ssl_context, self.upstream_ssl_context, self.tls_config = tls_contexts(config)
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
                          supported_scope=self.supported_scope, app_routing_verified=False, attribution='unverified',
                          tls=self.tls_config, websocket_enabled=self.config.enable_websocket,
                          websocket_connections=self.websocket_connections))

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

    def _observe_kind(self, kind):
        key = {'http_transaction': 'http_transactions', 'websocket_handshake': 'websocket_handshakes',
               'websocket_frame': 'websocket_frames'}.get(kind, 'websocket_events')
        self.counters[key] += 1
        if self.active_recording is not None:
            self.active_recording['counters'][key] += 1
        self._count('observed', self.active_recording)

    def _begin(self, request, connection_id, accepted_at, *, kind='http_transaction'):
        self._observe_kind(kind)
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
                      kind=kind, transport='TLS' if self.listener_ssl_context or self.upstream_ssl_context else 'TCP',
                      protocol='HTTP/1.1', parser_version=PARSER, tls=self._tls_metadata(),
                      capture_mode='decrypted' if self.listener_ssl_context or self.upstream_ssl_context else 'plaintext',
                      endpoint=dict(host=self.config.host, port=self.config.upstream_port),
                      context_before_recording=accepted_at < record['monotonic_start'],
                      request=self._message(request, 'client_to_upstream', record), response=None,
                      incomplete=True, error=None, received_after_stop=False)
        self.pending[packet['packet_id']] = (packet, record)
        self._emit(packet, record)
        return packet

    def _capture_ws(self, connection_id, accepted_at, kind, raw, direction, metadata, error=None):
        # Independent frame/event admission: never enter HTTP response drain.
        self._observe_kind(kind)
        record = self.active_recording
        if record is None:
            return None
        if record['counters']['captured'] >= self.config.max_transactions:
            self._count('dropped', record)
            return None
        self._count('captured', record)
        message = self._message(raw, direction, record) if direction else None
        tls = metadata.get('tls', self._tls_metadata())
        packet = dict(schema_version=VERSION, packet_id=uid(), recording_id=record['recording_id'],
                      event_id=uid(), session_id=self.session_id, run_id=None, connection_id=connection_id,
                      sequence=record['counters']['captured'], timestamp=now(), monotonic=time.monotonic(),
                      kind=kind, transport='TLS' if self.listener_ssl_context or self.upstream_ssl_context else 'TCP',
                      protocol='WebSocket/13', parser_version='websockets/16.0-frame-adapter/1', tls=tls,
                      capture_mode='decrypted' if self.listener_ssl_context or self.upstream_ssl_context else 'plaintext',
                      endpoint=dict(host=self.config.host, port=self.config.upstream_port),
                      context_before_recording=accepted_at < record['monotonic_start'],
                      direction=direction, websocket=clone(metadata),
                      request=message if direction == 'client_to_upstream' else None,
                      response=message if direction == 'upstream_to_client' else None,
                      incomplete=error is not None, error=error, received_after_stop=False)
        message_start = metadata.get('message_started_monotonic')
        packet['message_context_before_recording'] = message_start is not None and message_start < record['monotonic_start']
        if error or packet['message_context_before_recording']:
            record['network_coverage'] = 'partial'
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

    async def _open_upstream(self):
        options = dict(limit=self.config.max_header_bytes)
        if self.upstream_ssl_context is not None:
            options.update(ssl=self.upstream_ssl_context,
                           server_hostname=self.config.upstream_server_name,
                           ssl_handshake_timeout=self.config.io_timeout,
                           ssl_shutdown_timeout=min(self.config.io_timeout, 0.5))
        return await asyncio.open_connection(self.config.host, self.config.upstream_port, **options)

    def _tls_metadata(self, client_writer=None, upstream_writer=None):
        value = clone(self.tls_config)
        client = client_writer.get_extra_info('ssl_object') if client_writer else None
        upstream = upstream_writer.get_extra_info('ssl_object') if upstream_writer else None
        value.update(client_version=client.version() if client else None,
                     upstream_version=upstream.version() if upstream else None,
                     upstream_verified=bool(upstream), upstream_peer_sha256=None)
        if upstream:
            value['upstream_peer_sha256'] = hashlib.sha256(upstream.getpeercert(binary_form=True)).hexdigest()
        return value

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
        stage = 'tls' if self.listener_ssl_context else 'request'
        try:
            if self.listener_ssl_context is not None:
                # Track the TCP connection before TLS, so OFF also owns clients
                # which never send ClientHello. No global trust/proxy changes.
                await writer.start_tls(self.listener_ssl_context,
                                       ssl_handshake_timeout=self.config.io_timeout,
                                       ssl_shutdown_timeout=min(self.config.io_timeout, 0.5))
            stage = 'request'
            request = await asyncio.wait_for(read_message(reader, self.config), self.config.io_timeout)
            if self.websocket_module and self.websocket_module.is_websocket_request(request):
                await self.websocket_module.relay_websocket(self, reader, writer, request, connection_id, accepted_at)
                return
            packet = self._begin(request, connection_id, accepted_at)
            if packet:
                packet['tls'] = self._tls_metadata(writer)
            stage = 'upstream'
            async with asyncio.timeout(self.config.io_timeout):
                upstream_reader, upstream = await self._open_upstream()
                if packet:
                    packet['tls'] = self._tls_metadata(writer, upstream)
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
            error = ('certificate_verification_failed' if isinstance(exc, ssl.SSLCertVerificationError)
                     else 'tls_error' if isinstance(exc, ssl.SSLError)
                     else str(exc) if isinstance(exc, ProtocolError)
                     else 'timeout' if isinstance(exc, TimeoutError) else 'connection_error')
            self.last_error = stage + ':' + error
            if stage == 'tls' or isinstance(exc, ssl.SSLError):
                self._count('tls_errors', record)
            if stage == 'request':
                self._count('decoder_errors', record)
            elif stage == 'upstream':
                self._count('upstream_errors', record)
                if isinstance(exc, ProtocolError):
                    self._count('decoder_errors', record)
            self._finish(packet, error=stage + ':' + error)
            if stage not in ('client', 'tls'):
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
        optional = {'recording_id'} if cmd == 'RECORD' else {'expected_recording_id'} if cmd == 'STOP' else set()
        if not required | extra <= payload.keys() or payload.keys() - (required | extra | optional) or type(payload['schema_version']) is not int or payload['schema_version'] != VERSION:
            return envelope(error='invalid_command')
        if any(not isinstance(payload[key],str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',payload[key]) for key in optional & payload.keys()):
            return envelope(error='invalid_recording_scope')
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
            recording_id=payload.get('recording_id') or uid()
            exists=await self.store.run(lambda:self.store.conn.execute('SELECT 1 FROM recordings WHERE id=?',(recording_id,)).fetchone())
            if exists:raise ValueError('recording_id_exists')
            record = dict(schema_version=VERSION, recording_id=recording_id, session_id=self.session_id, run_id=None,
                          event_id=uid(), timestamp=now(), started_at=now(), monotonic_start=time.monotonic(),
                          status='recording', network_coverage='unknown' if self.relay_state == 'on' else 'none',
                          supported_scope=self.supported_scope, parser_version=PARSER, counters=counter_set(), gaps=[],
                          attribution=dict(device_id=payload['device_id'], app_id=payload['app_id'], confidence='unverified',
                                           method='explicit_synthetic_labels', limitations=['No device routing or app identity verified']),
                          config=dict(record_stop_response_drain_ms=self.config.record_stop_response_drain_ms,
                                      relay_off_drain_ms=self.config.relay_off_drain_ms,
                                      capture_body_bytes=self.config.capture_body_bytes,
                                      max_transactions=self.config.max_transactions, tls=clone(self.tls_config),
                                      enable_websocket=self.config.enable_websocket,
                                      max_websocket_frame_bytes=self.config.max_websocket_frame_bytes,
                                      max_websocket_message_bytes=self.config.max_websocket_message_bytes,
                                      websocket_idle_timeout=self.config.websocket_idle_timeout))
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
            expected=payload.get('expected_recording_id')
            if expected is not None and self.active_recording and self.active_recording['recording_id']!=expected:
                raise ValueError('recording_scope_mismatch')
            if not self.active_recording:
                if expected is not None:return dict(recording_id=expected,status='idle',scope_matched=False)
                return dict(recording_id=self.last_recording['recording_id'] if self.last_recording else None, status='idle')
            record = self.active_recording
            self.active_recording = None  # seal without awaiting storage or drain
            record['websocket_at_stop'] = clone(self.websocket_connections)
            if any(state.get('frame_in_progress') or state.get('message_id')
                   for connection in self.websocket_connections.values()
                   for state in connection.get('directions', {}).values()):
                record['network_coverage'] = 'partial'
                record['gaps'].append(dict(reason='websocket_incomplete_at_stop', timestamp=now()))
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
    relay = Relay(Config(db=args.db, upstream_port=args.upstream_port, listen_port=args.port,
                         listener_cert=args.listener_cert, listener_key=args.listener_key,
                         upstream_tls=args.upstream_tls, upstream_ca=args.upstream_ca,
                         upstream_server_name=args.upstream_server_name, enable_websocket=args.websocket))
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
    run.add_argument('--listener-cert', type=Path)
    run.add_argument('--listener-key', type=Path)
    run.add_argument('--upstream-tls', action='store_true')
    run.add_argument('--upstream-ca', type=Path)
    run.add_argument('--upstream-server-name', default='localhost')
    run.add_argument('--websocket', action='store_true', help='Capture RFC6455 traffic frames (requires P2 requirements)')
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
