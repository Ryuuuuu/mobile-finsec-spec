"""Bounded transparent RFC 6455 bridge using the pinned websockets frame codec.

Only extension-free HTTP/1.1 Upgrade is accepted. Frame.parse owns wire decoding;
this adapter owns async reads, message bounds, recording admission, and cleanup.
It never synthesizes Pong/Close frames and never reserializes accepted frames.
"""
from __future__ import annotations

import asyncio
import codecs
import hashlib
import re
import ssl
import time
import uuid

from websockets.datastructures import Headers
from websockets.exceptions import InvalidHeader, InvalidHandshake, PayloadTooBig, ProtocolError, SecurityError
from websockets.frames import Close, Frame, OP_BINARY, OP_CLOSE, OP_CONT, OP_PING, OP_PONG, OP_TEXT
from websockets.headers import parse_connection, parse_upgrade
from websockets.http11 import Request
from websockets.server import ServerProtocol

PARSER = 'websockets/16.0-frame-adapter/1'


class WebSocketError(Exception):
    """Sanitized protocol failure; never contains captured payload or headers."""


class WebSocketEOF(Exception):
    pass


def is_websocket_request(raw):
    head = raw.split(b'\r\n\r\n', 1)[0]
    return any(line.lower().startswith(b'upgrade:') for line in head.split(b'\r\n')[1:])


def _headers(raw, maximum, *, response=False):
    if len(raw) > maximum or not raw.endswith(b'\r\n\r\n'):
        raise WebSocketError('websocket_header_limit_or_framing')
    lines = raw[:-4].split(b'\r\n')
    pattern = rb'HTTP/1\.1 101 [\x20-\x7e]*' if response else rb'GET /[\x21-\x7e]* HTTP/1\.1'
    if not re.fullmatch(pattern, lines[0]) or (not response and b'#' in lines[0]):
        raise WebSocketError('websocket_invalid_response' if response else 'websocket_invalid_request')
    headers = Headers()
    seen = set()
    for line in lines[1:]:
        if b':' not in line:
            raise WebSocketError('websocket_invalid_header')
        name, value = line.split(b':', 1)
        if (not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
                or re.search(rb'[^\x09\x20-\x7e]', value) or name.lower() in seen):
            raise WebSocketError('websocket_invalid_header')
        seen.add(name.lower())
        headers[name.decode('ascii')] = value.strip().decode('ascii')
    if any(name in headers for name in ('Transfer-Encoding', 'Expect', 'Trailer')):
        raise WebSocketError('websocket_unsupported_framing')
    if 'Content-Length' in headers and headers['Content-Length'] != '0':
        raise WebSocketError('websocket_body_unsupported')
    if any(name in headers for name in ('Sec-WebSocket-Extensions', 'Sec-WebSocket-Protocol')):
        raise WebSocketError('websocket_negotiation_unsupported')
    return lines[0], headers


def validate_request(raw, maximum):
    first, headers = _headers(raw, maximum)
    if not headers.get('Host'):
        raise WebSocketError('websocket_host_required')
    request = Request(first.split(b' ')[1].decode('ascii'), headers)
    response = ServerProtocol(extensions=None, subprotocols=None).accept(request)
    if response.status_code != 101:
        raise WebSocketError('websocket_invalid_request')
    return response.headers['Sec-WebSocket-Accept']


def validate_response(raw, maximum, expected_accept):
    _, headers = _headers(raw, maximum, response=True)
    try:
        connection = parse_connection(headers.get('Connection', ''))
        upgrade = parse_upgrade(headers.get('Upgrade', ''))
        if (not any(token.lower() == 'upgrade' for token in connection)
                or len(upgrade) != 1 or upgrade[0].lower() != 'websocket'
                or headers.get('Sec-WebSocket-Accept') != expected_accept):
            raise WebSocketError('websocket_invalid_response')
    except (InvalidHeader, ValueError) as exc:
        raise WebSocketError('websocket_invalid_response') from exc


def new_direction_state():
    return dict(message_id=None, message_opcode=None, message_size=0,
                fragment_index=0, frame_sequence=0, message_started_monotonic=None,
                frame_in_progress=False, close_received=False)


def _need_bytes(size):
    data = yield size
    return data


async def read_frame(reader, *, masked, maximum, idle_timeout, io_timeout, state=None):
    """Return (decoded frame, original wire bytes); no TCP chunk is a frame.

    Frame.parse is a version-pinned library codec method. The adapter supplies
    requested exact reads and retains the original length encoding and mask key.
    """
    parser = Frame.parse(_need_bytes, mask=masked, max_size=maximum, extensions=None)
    raw = bytearray()
    deadline = None
    try:
        needed = next(parser)
        while True:
            part = bytearray()
            while len(part) < needed:
                timeout = idle_timeout if deadline is None else max(0, deadline - time.monotonic())
                chunk = await asyncio.wait_for(reader.read(needed - len(part)), timeout)
                if not chunk:
                    if not raw and not part:
                        raise WebSocketEOF()
                    raise WebSocketError('websocket_incomplete_frame')
                if deadline is None:
                    deadline = time.monotonic() + io_timeout
                if state is not None:
                    state['frame_in_progress'] = True
                part.extend(chunk)
            raw.extend(part)
            try:
                needed = parser.send(bytes(part))
            except StopIteration as finished:
                frame = finished.value
                # RFC 6455 requires the minimal length representation. The
                # library codec checks bounds/masking/opcodes; enforce this
                # extra strict scope without implementing a second decoder.
                encoded = raw[1] & 0x7f
                if ((encoded == 126 and len(frame.data) < 126)
                        or (encoded == 127 and len(frame.data) < 65536)):
                    raise WebSocketError('websocket_nonminimal_length')
                return frame, bytes(raw)
    except (ProtocolError, PayloadTooBig, UnicodeDecodeError) as exc:
        raise WebSocketError('websocket_invalid_or_oversized_frame') from exc
    finally:
        parser.close()
        if state is not None:
            state['frame_in_progress'] = False


class MessageState:
    """Small application-message validator around the library frame codec."""
    def __init__(self, snapshot, maximum):
        self.snapshot = snapshot
        self.maximum = maximum
        self.decoder = None

    def accept(self, frame):
        state = self.snapshot
        if state['close_received']:
            raise WebSocketError('websocket_frame_after_close')
        metadata = dict(frame_id=str(uuid.uuid4()), opcode=int(frame.opcode), fin=frame.fin,
                        payload_size=len(frame.data), payload_sha256=hashlib.sha256(frame.data).hexdigest(),
                        parser_version=PARSER, message_id=None, fragment_index=None,
                        message_finished=False)
        if frame.opcode in (OP_TEXT, OP_BINARY, OP_CONT):
            if frame.opcode == OP_CONT:
                if state['message_id'] is None:
                    raise WebSocketError('websocket_unexpected_continuation')
                state['fragment_index'] += 1
            else:
                if state['message_id'] is not None:
                    raise WebSocketError('websocket_expected_continuation')
                state.update(message_id=str(uuid.uuid4()), message_opcode=int(frame.opcode),
                             message_size=0, fragment_index=0, message_started_monotonic=time.monotonic())
                self.decoder = codecs.getincrementaldecoder('utf-8')() if frame.opcode == OP_TEXT else None
            state['message_size'] += len(frame.data)
            if state['message_size'] > self.maximum:
                raise WebSocketError('websocket_message_too_large')
            if self.decoder is not None:
                try:
                    self.decoder.decode(frame.data, final=frame.fin)
                except UnicodeDecodeError as exc:
                    raise WebSocketError('websocket_invalid_utf8') from exc
            metadata.update(message_id=state['message_id'], message_opcode=state['message_opcode'],
                            fragment_index=state['fragment_index'], message_finished=frame.fin,
                            message_size_so_far=state['message_size'],
                            message_started_monotonic=state['message_started_monotonic'])
            if frame.fin:
                state.update(message_id=None, message_opcode=None, message_size=0, fragment_index=0, message_started_monotonic=time.monotonic())
                self.decoder = None
        elif frame.opcode == OP_CLOSE:
            try:
                close = Close.parse(frame.data)
            except (ProtocolError, UnicodeDecodeError) as exc:
                raise WebSocketError('websocket_invalid_close') from exc
            state['close_received'] = True
            metadata.update(close_code=int(close.code), close_reason=close.reason,
                            interrupted_message=state['message_id'] is not None)
        elif frame.opcode not in (OP_PING, OP_PONG):
            raise WebSocketError('websocket_invalid_opcode')
        state['frame_sequence'] += 1
        metadata['frame_sequence'] = state['frame_sequence']
        return metadata


async def relay_websocket(relay, reader, writer, request, connection_id, accepted_at):
    config = relay.config
    upstream = None
    packet = None
    upgraded = False
    pumps = []
    terminal_error = None
    stage = 'request'
    snapshot = dict(accepted_at=accepted_at, opened_monotonic=None,
                    directions={direction: new_direction_state() for direction in
                                ('client_to_upstream', 'upstream_to_client')})
    try:
        expected_accept = validate_request(request, config.max_header_bytes)
        packet = relay._begin(request, connection_id, accepted_at, kind='websocket_handshake')
        if packet is not None:
            packet['tls'] = relay._tls_metadata(writer)
        stage = 'upstream'
        async with asyncio.timeout(config.io_timeout):
            upstream_reader, upstream = await relay._open_upstream()
            snapshot['tls'] = relay._tls_metadata(writer, upstream)
            if packet is not None:
                packet['tls'] = snapshot['tls']
            upstream.write(request)
            await upstream.drain()
            response = await upstream_reader.readuntil(b'\r\n\r\n')
            validate_response(response, config.max_header_bytes, expected_accept)
        relay._finish(packet, response=response)
        writer.write(response)
        await asyncio.wait_for(writer.drain(), config.io_timeout)
        upgraded = True
        snapshot['opened_monotonic'] = time.monotonic()
        relay.websocket_connections[connection_id] = snapshot
        relay._capture_ws(connection_id, accepted_at, 'websocket_open', b'', None,
                          dict(parser_version=PARSER, lifecycle='opened', tls=snapshot['tls']))
        stage = 'websocket'

        async def pump(source, destination, direction):
            state = snapshot['directions'][direction]
            validator = MessageState(state, config.max_websocket_message_bytes)
            while True:
                try:
                    frame, raw = await read_frame(
                        source, masked=direction == 'client_to_upstream',
                        maximum=config.max_websocket_frame_bytes,
                        idle_timeout=config.websocket_idle_timeout,
                        io_timeout=config.io_timeout, state=state)
                except WebSocketEOF:
                    if state['close_received']:
                        return
                    raise WebSocketError('websocket_abrupt_eof') from None
                metadata = validator.accept(frame)
                metadata['masked'] = direction == 'client_to_upstream'
                metadata['tls'] = snapshot['tls']
                relay._capture_ws(connection_id, accepted_at, 'websocket_frame', raw, direction, metadata)
                destination.write(raw)
                await asyncio.wait_for(destination.drain(), config.io_timeout)
                if frame.opcode == OP_CLOSE:
                    return

        pumps = [asyncio.create_task(pump(reader, upstream, 'client_to_upstream')),
                 asyncio.create_task(pump(upstream_reader, writer, 'upstream_to_client'))]
        done, pending = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        # A received Close is forwarded unchanged. Give the peer one bounded
        # interval to send its own Close; no synthetic reply contaminates capture.
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), config.io_timeout)
        if any(not state['close_received'] for state in snapshot['directions'].values()):
            terminal_error = 'websocket_abrupt_eof'
        elif any(state['message_id'] is not None for state in snapshot['directions'].values()):
            terminal_error = 'websocket_fragment_interrupted'
    except asyncio.CancelledError:
        terminal_error = 'relay_off_timeout'
        relay._finish(packet, error=terminal_error)
        raise
    except (WebSocketError, OSError, TimeoutError, asyncio.IncompleteReadError,
            asyncio.LimitOverrunError, InvalidHandshake, SecurityError) as exc:
        if isinstance(exc, WebSocketError):
            terminal_error = str(exc)
        elif isinstance(exc, ssl.SSLCertVerificationError):
            terminal_error = 'tls_verification_failed'
        elif isinstance(exc, TimeoutError):
            terminal_error = 'websocket_timeout'
        else:
            terminal_error = 'websocket_connection_error'
        relay.last_error = stage + ':' + terminal_error
        record = relay.active_recording if upgraded or packet is None else relay.pending.get(packet['packet_id'], (None, None))[1]
        if isinstance(exc, ssl.SSLError):
            relay._count('tls_errors', record)
        if stage in ('request', 'websocket') or isinstance(exc, WebSocketError):
            relay._count('decoder_errors', record)
        if stage == 'upstream':
            relay._count('upstream_errors', record)
        relay._finish(packet, error=stage + ':' + terminal_error)
        if not upgraded:
            code = b'400 Bad Request' if stage == 'request' else b'502 Bad Gateway'
            writer.write(b'HTTP/1.1 ' + code + b'\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            try:
                await asyncio.wait_for(writer.drain(), config.io_timeout)
            except (OSError, TimeoutError):
                pass
    finally:
        for task in pumps:
            if not task.done():
                task.cancel()
        if pumps:
            await asyncio.gather(*pumps, return_exceptions=True)
        if upgraded:
            relay._capture_ws(connection_id, accepted_at, 'websocket_close', b'', None,
                              dict(parser_version=PARSER, lifecycle='closed' if terminal_error is None else 'abnormal',
                                   directions=snapshot['directions'], tls=snapshot['tls']), error=terminal_error)
        relay.websocket_connections.pop(connection_id, None)
        if upstream is not None:
            upstream.close()
            try:
                await asyncio.wait_for(upstream.wait_closed(), 0.5)
            except (OSError, TimeoutError, asyncio.CancelledError):
                pass
