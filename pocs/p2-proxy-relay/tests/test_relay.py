"""Cloud-only acceptance tests: all traffic and identifiers are synthetic loopback data."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relay import Config, Relay, query  # noqa: E402


def request_bytes(path: str, body: bytes = b"") -> bytes:
    method = "POST" if body else "GET"
    return (
        f"{method} {path} HTTP/1.1\r\nHost: qa.invalid\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
        + body
    )


class Upstream:
    def __init__(self):
        self.received = []
        self.gates = {}
        self.tasks = set()
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    def gate(self, path):
        entered, release = asyncio.Event(), asyncio.Event()
        self.gates[path] = (entered, release)
        return entered, release

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            path = head.split(b" ", 2)[1].decode("ascii")
            headers = {}
            for line in head.split(b"\r\n")[1:]:
                if b":" in line:
                    name, value = line.split(b":", 1)
                    headers[name.lower()] = value.strip()
            body = await reader.readexactly(int(headers.get(b"content-length", b"0")))
            self.received.append((path, body))
            if path in self.gates:
                entered, release = self.gates[path]
                entered.set()
                await release.wait()
            if path == "/bad-response":
                writer.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n")
            elif path == "/short-response":
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\nshort")
            else:
                payload = b"reply:" + path.encode() + b":" + body
                writer.write(
                    f"HTTP/1.1 200 OK\r\nContent-Length: {len(payload)}\r\n"
                    "Connection: close\r\n\r\n".encode() + payload
                )
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.tasks.discard(task)

    async def close(self):
        self.server.close()
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.server.wait_closed()


class RelayAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="p2-qa-")
        self.db = Path(self.temp.name) / "capture.sqlite3"
        self.upstream = Upstream()
        await self.upstream.start()
        self.relay = None
        self.clients = set()
        await self.make_relay()

    async def asyncTearDown(self):
        for _, release in self.upstream.gates.values():
            release.set()
        for task in self.clients:
            if not task.done():
                task.cancel()
        if self.clients:
            await asyncio.gather(*self.clients, return_exceptions=True)
        if self.relay:
            self.relay.store.fail_writes = False
            self.relay.store.write_delay_seconds = 0
            await asyncio.wait_for(self.relay.close(), 3)
        await self.upstream.close()
        self.temp.cleanup()

    async def make_relay(self, **kwargs):
        if self.relay:
            await self.relay.close()
        settings = dict(db=self.db, upstream_port=self.upstream.port, io_timeout=1.0,
                        relay_off_drain_ms=120, record_stop_response_drain_ms=120)
        settings.update(kwargs)
        self.relay = Relay(Config(**settings))
        await self.relay.start()

    async def command(self, operation, command_id=None, **kwargs):
        payload = {"schema_version": 1, "command_id": command_id or uuid.uuid4().hex,
                   "command": operation, **kwargs}
        result = await self.relay.command(payload)
        self.assertEqual(result["schema_version"], 1)
        return result

    async def ok_command(self, operation, command_id=None, **kwargs):
        result = await self.command(operation, command_id, **kwargs)
        self.assertTrue(result["ok"], result)
        return result["result"]

    async def record(self):
        return (await self.ok_command("RECORD", device_id="synthetic-loopback",
                                      app_id="dev.finsec.synthetic"))["recording_id"]

    async def test_scoped_stop_and_record_id_reuse(self):
        await self.ok_command('ON')
        args=dict(device_id='synthetic',app_id='dev.finsec.synthetic',recording_id='qa-owner-a')
        first=await self.ok_command('RECORD',command_id='start-owner-a',**args)
        self.assertEqual(first['recording_id'],'qa-owner-a')
        self.assertEqual(await self.ok_command('RECORD',command_id='start-owner-a',**args),first)
        rejected=await self.command('STOP',expected_recording_id='qa-owner-b')
        self.assertEqual(rejected['error'],'recording_scope_mismatch')
        self.assertEqual(self.relay.active_recording['recording_id'],'qa-owner-a')
        await self.ok_command('STOP',command_id='stop-owner-a',expected_recording_id='qa-owner-a')
        await self.make_relay();await self.ok_command('ON')
        self.assertEqual((await self.command('RECORD',**args))['error'],'recording_id_exists')
        await self.ok_command('RECORD',device_id='synthetic',app_id='dev.finsec.synthetic',recording_id='qa-owner-b')
        # A retried old STOP returns its old result, never stops the newer recording.
        await self.ok_command('STOP',command_id='stop-owner-a',expected_recording_id='qa-owner-a')
        self.assertEqual(self.relay.active_recording['recording_id'],'qa-owner-b')
        await self.ok_command('STOP')  # Legacy unscoped compatibility is explicit, not ownership enforcement.

    async def test_scope_validation_and_idle_noop(self):
        for value in (None,'',True,'../outside'):
            self.assertEqual((await self.command('STOP',expected_recording_id=value))['error'],'invalid_recording_scope')
        result=await self.ok_command('STOP',expected_recording_id='qa-never-started')
        self.assertEqual(result['status'],'idle');self.assertFalse(result['scope_matched'])

    def read(self, kind, **kwargs):
        result = query(self.db, kind=kind, **kwargs)
        self.assertTrue(result["ok"], result)
        return result["result"]

    def packets(self, recording_id):
        rows = self.read("packets", recording_id=recording_id)
        return [self.read("detail", packet_id=row["packet_id"]) for row in rows]

    def recording(self, recording_id):
        return next(row for row in self.read("recordings") if row["recording_id"] == recording_id)

    async def exchange(self, path, body=b"", *, raw=None, fragments=False):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.relay.port)
        data = request_bytes(path, body) if raw is None else raw
        try:
            if fragments:
                # Deliberately split start-line, headers and payload at unrelated TCP boundaries.
                for offset in range(0, len(data), 7):
                    writer.write(data[offset:offset + 7])
                    await writer.drain()
                    await asyncio.sleep(0)
            else:
                writer.write(data)
                await writer.drain()
            return await asyncio.wait_for(reader.read(), 3)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    def client(self, path, **kwargs):
        task = asyncio.create_task(self.exchange(path, **kwargs))
        self.clients.add(task)
        return task

    async def wait_sealed(self):
        # Root exposes synchronous status for observation during an awaited STOP command.
        for _ in range(200):
            active = self.relay.active_recording
            if active is None or active.get("status") != "recording":
                return
            await asyncio.sleep(0.001)
        self.fail("STOP did not close the capture admission boundary")

    async def test_20_messages_exact_delivery_capture_hashes_and_pagination(self):
        await self.ok_command("ON")
        recording_id = await self.record()
        responses = await asyncio.gather(*(self.exchange(f"/qa/{i}", f"synthetic-{i}".encode())
                                           for i in range(20)))
        for i, response in enumerate(responses):
            self.assertTrue(response.startswith(b"HTTP/1.1 200"), response)
            self.assertTrue(response.endswith(f"reply:/qa/{i}:synthetic-{i}".encode()))
        await self.ok_command("STOP")
        self.assertEqual(len(self.upstream.received), 20)
        self.assertEqual(len(set(path for path, _ in self.upstream.received)), 20)
        packets = self.packets(recording_id)
        self.assertEqual(len(packets), 20)
        self.assertEqual(len({p["packet_id"] for p in packets}), 20)
        self.assertEqual(len({p["connection_id"] for p in packets}), 20)
        self.assertEqual(len({p["sequence"] for p in packets}), 20)
        paths = set()
        for packet in packets:
            self.assertFalse(packet["incomplete"])
            self.assertFalse(packet["received_after_stop"])
            for direction in ("request", "response"):
                payload = packet[direction]
                raw = base64.b64decode(payload["raw_base64"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), payload["sha256"])
                self.assertEqual(len(raw), payload["size"])
                self.assertEqual(len(raw), payload["stored_size"])
                self.assertFalse(payload["truncated"])
            paths.add(base64.b64decode(packet["request"]["raw_base64"]).split(b" ")[1])
        self.assertEqual(paths, {f"/qa/{i}".encode() for i in range(20)})
        first = self.read("packets", recording_id=recording_id, limit=7, offset=0)
        second = self.read("packets", recording_id=recording_id, limit=7, offset=7)
        self.assertEqual(len(first), 7)
        self.assertEqual(len(second), 7)
        self.assertFalse({p["packet_id"] for p in first} & {p["packet_id"] for p in second})
        self.assertEqual(self.recording(recording_id)["network_coverage"], "complete_for_supported_scope")

    async def test_record_and_stop_exclude_new_requests_outside_window(self):
        await self.ok_command("ON")
        self.assertIn(b"200 OK", await self.exchange("/before"))
        recording_id = await self.record()
        self.assertIn(b"200 OK", await self.exchange("/inside"))
        await self.ok_command("STOP")
        self.assertIn(b"200 OK", await self.exchange("/after"))
        packets = self.packets(recording_id)
        self.assertEqual(len(packets), 1)
        self.assertIn(b"/inside", base64.b64decode(packets[0]["request"]["raw_base64"]))
        self.assertEqual((await self.ok_command("STATUS"))["relay_state"], "on")

    async def test_stop_drains_only_identified_transaction_and_rejects_new_capture(self):
        await self.make_relay(record_stop_response_drain_ms=500)
        await self.ok_command("ON")
        recording_id = await self.record()
        entered, release = self.upstream.gate("/held")
        held = self.client("/held")
        await asyncio.wait_for(entered.wait(), 1)
        stop = asyncio.create_task(self.ok_command("STOP"))
        await self.wait_sealed()
        self.assertIn(b"200 OK", await self.exchange("/after-seal"))
        self.assertFalse(stop.done(), "STOP must wait for the eligible in-flight response")
        release.set()
        self.assertIn(b"200 OK", await held)
        await stop
        packets = self.packets(recording_id)
        self.assertEqual(len(packets), 1)
        self.assertTrue(packets[0]["received_after_stop"])
        self.assertFalse(packets[0]["incomplete"])

    async def test_stop_response_deadline_is_incomplete_but_relay_continues(self):
        await self.make_relay(record_stop_response_drain_ms=25)
        await self.ok_command("ON")
        recording_id = await self.record()
        entered, release = self.upstream.gate("/too-late")
        held = self.client("/too-late")
        await asyncio.wait_for(entered.wait(), 1)
        started = time.monotonic()
        await self.ok_command("STOP")
        self.assertLess(time.monotonic() - started, 0.8)
        before = self.packets(recording_id)
        self.assertEqual(len(before), 1)
        self.assertTrue(before[0]["incomplete"])
        self.assertEqual(before[0]["error"], "stop_drain_timeout")
        self.assertIsNone(before[0]["response"])
        release.set()
        self.assertIn(b"200 OK", await held)
        self.assertEqual(self.packets(recording_id), before, "sealed recording must not mutate on late response")
        self.assertEqual(self.recording(recording_id)["network_coverage"], "partial")

    async def test_off_on_creates_gap_and_listener_reopens(self):
        await self.ok_command("ON")
        recording_id = await self.record()
        self.assertIn(b"200 OK", await self.exchange("/on-1"))
        port = self.relay.port
        await self.ok_command("OFF")
        self.assertEqual((await self.ok_command("STATUS"))["relay_state"], "off")
        with self.assertRaises(OSError):
            await asyncio.open_connection("127.0.0.1", port)
        await self.ok_command("ON")
        self.assertIn(b"200 OK", await self.exchange("/on-2"))
        await self.ok_command("STOP")
        self.assertEqual(len(self.packets(recording_id)), 2)
        recording = self.recording(recording_id)
        self.assertEqual(recording["network_coverage"], "partial")
        self.assertTrue(recording["gaps"])

    async def test_off_drain_force_closes_without_waiting_for_record_stop_budget(self):
        await self.make_relay(relay_off_drain_ms=25, record_stop_response_drain_ms=700)
        await self.ok_command("ON")
        recording_id = await self.record()
        entered, release = self.upstream.gate("/off-held")
        held = self.client("/off-held")
        await asyncio.wait_for(entered.wait(), 1)
        started = time.monotonic()
        await self.ok_command("OFF")
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertNotIn(b"200 OK", await held)
        release.set()
        await self.ok_command("STOP")
        packet, = self.packets(recording_id)
        self.assertTrue(packet["incomplete"])
        self.assertEqual(packet["error"], "relay_off_timeout")

    async def test_record_while_off_is_none_and_does_not_turn_relay_on(self):
        recording_id = await self.record()
        self.assertEqual((await self.ok_command("STATUS"))["relay_state"], "off")
        await self.ok_command("STOP")
        recording = self.recording(recording_id)
        self.assertEqual(recording["network_coverage"], "none")
        self.assertEqual(self.packets(recording_id), [])

    async def test_repeated_command_ids_conflicts_and_busy_record(self):
        first = await self.command("ON", "on-id")
        self.assertTrue(first["ok"], first)
        port = self.relay.port
        second = await self.command("ON", "on-id")
        self.assertEqual(first, second)
        self.assertEqual(port, self.relay.port)
        conflict = await self.command("OFF", "on-id")
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["error"], "command_conflict")
        payload = {"device_id": "synthetic-loopback", "app_id": "dev.finsec.synthetic"}
        recorded = await self.command("RECORD", "record-id", **payload)
        self.assertTrue(recorded["ok"], recorded)
        self.assertEqual(recorded, await self.command("RECORD", "record-id", **payload))
        self.assertFalse((await self.command("RECORD", **payload))["ok"])
        stopped = await self.command("STOP", "stop-id")
        self.assertTrue(stopped["ok"], stopped)
        self.assertEqual(stopped, await self.command("STOP", "stop-id"))
        self.assertEqual(len(self.read("recordings")), 1)

    async def test_on_off_on_race_converges_and_only_one_listener_remains(self):
        results = await asyncio.gather(self.command("ON"), self.command("OFF"), self.command("ON"))
        self.assertTrue(all(result["ok"] for result in results), results)
        self.assertEqual((await self.ok_command("STATUS"))["relay_state"], "on")
        self.assertIn(b"200 OK", await self.exchange("/race"))
        await self.ok_command("OFF")
        with self.assertRaises(OSError):
            await asyncio.open_connection("127.0.0.1", self.relay.port)

    async def test_upstream_connection_failure_is_visible_and_incomplete(self):
        unavailable = socket.socket()
        unavailable.bind(("127.0.0.1", 0))
        port = unavailable.getsockname()[1]
        unavailable.close()
        await self.make_relay(upstream_port=port)
        await self.ok_command("ON")
        recording_id = await self.record()
        response = await self.exchange("/connection-error")
        self.assertNotIn(b"200 OK", response)
        await self.ok_command("STOP")
        packet, = self.packets(recording_id)
        self.assertTrue(packet["incomplete"])
        self.assertIsNotNone(packet["error"])
        self.assertEqual(self.recording(recording_id)["network_coverage"], "partial")

    async def test_upstream_timeout_is_visible(self):
        await self.make_relay(io_timeout=0.04)
        await self.ok_command("ON")
        recording_id = await self.record()
        entered, release = self.upstream.gate("/timeout")
        held = self.client("/timeout")
        await asyncio.wait_for(entered.wait(), 1)
        response = await held
        self.assertNotIn(b"200 OK", response)
        release.set()
        await self.ok_command("STOP")
        packet, = self.packets(recording_id)
        self.assertTrue(packet["incomplete"])
        self.assertEqual(packet["error"], "upstream:timeout")

    async def test_fragmented_request_is_one_logical_transaction(self):
        await self.ok_command("ON")
        recording_id = await self.record()
        response = await self.exchange("/fragmented", b"synthetic body across reads", fragments=True)
        self.assertTrue(response.endswith(b"reply:/fragmented:synthetic body across reads"))
        await self.ok_command("STOP")
        packet, = self.packets(recording_id)
        self.assertFalse(packet["incomplete"])
        raw = base64.b64decode(packet["request"]["raw_base64"])
        self.assertEqual(raw, request_bytes("/fragmented", b"synthetic body across reads"))

    async def test_connection_accepted_before_record_can_capture_request_in_window(self):
        await self.ok_command("ON")
        reader, writer = await asyncio.open_connection("127.0.0.1", self.relay.port)
        try:
            await asyncio.sleep(0.01)
            recording_id = await self.record()
            writer.write(request_bytes("/preexisting-connection"))
            await writer.drain()
            self.assertIn(b"200 OK", await asyncio.wait_for(reader.read(), 1))
            await self.ok_command("STOP")
            self.assertEqual(len(self.packets(recording_id)), 1)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_partial_request_at_stop_is_not_an_identified_transaction(self):
        await self.ok_command("ON")
        recording_id = await self.record()
        reader, writer = await asyncio.open_connection("127.0.0.1", self.relay.port)
        try:
            request = request_bytes("/partial", b"body")
            writer.write(request[:-2])
            await writer.drain()
            await asyncio.sleep(0.01)
            await self.ok_command("STOP")
            writer.write(request[-2:])
            await writer.drain()
            self.assertIn(b"200 OK", await asyncio.wait_for(reader.read(), 1))
            self.assertEqual(self.packets(recording_id), [])
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_unsupported_and_ambiguous_request_framing_never_reaches_upstream(self):
        await self.ok_command("ON")
        recording_id = await self.record()
        bad = [
            b"CONNECT qa.invalid:443 HTTP/1.1\r\nHost: qa.invalid\r\n\r\n",
            b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n",
            b"POST /chunked HTTP/1.1\r\nHost: qa.invalid\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
            b"POST /duplicate HTTP/1.1\r\nHost: qa.invalid\r\nContent-Length: 0\r\nContent-Length: 4\r\n\r\nbody",
            b"GET /hosts HTTP/1.1\r\nHost: a.invalid\r\nHost: b.invalid\r\n\r\n",
            b"GET http://qa.invalid/absolute HTTP/1.1\r\nHost: qa.invalid\r\n\r\n",
        ]
        for raw in bad:
            with self.subTest(raw=raw.split(b"\r\n", 1)[0]):
                response = await self.exchange("/unused", raw=raw)
                self.assertNotIn(b"200 OK", response)
        await self.ok_command("STOP")
        self.assertEqual(self.upstream.received, [])
        recording = self.recording(recording_id)
        self.assertEqual(recording["network_coverage"], "partial")
        self.assertGreaterEqual(recording["counters"]["decoder_errors"], len(bad))

    async def test_unsupported_and_short_upstream_response_are_incomplete(self):
        await self.ok_command("ON")
        recording_id = await self.record()
        for path in ("/bad-response", "/short-response"):
            response = await self.exchange(path)
            self.assertNotIn(b"200 OK", response)
        await self.ok_command("STOP")
        packets = self.packets(recording_id)
        self.assertEqual(len(packets), 2)
        self.assertTrue(all(p["incomplete"] and p["error"] for p in packets))
        self.assertEqual(self.recording(recording_id)["network_coverage"], "partial")

    async def test_payload_capture_truncates_without_truncating_forwarded_body(self):
        await self.make_relay(capture_body_bytes=64)
        await self.ok_command("ON")
        recording_id = await self.record()
        body = b"synthetic-large-body-" * 100
        response = await self.exchange("/truncated", body)
        self.assertTrue(response.endswith(b"reply:/truncated:" + body))
        await self.ok_command("STOP")
        packet, = self.packets(recording_id)
        self.assertTrue(packet["request"]["truncated"])
        self.assertLess(packet["request"]["stored_size"], packet["request"]["size"])
        self.assertTrue(packet["response"]["truncated"])
        self.assertEqual(self.recording(recording_id)["network_coverage"], "partial")

    async def test_transaction_limit_preserves_delivery_and_reports_capture_loss(self):
        await self.make_relay(max_transactions=2)
        await self.ok_command("ON")
        recording_id = await self.record()
        for i in range(5):
            self.assertIn(b"200 OK", await self.exchange(f"/limited/{i}"))
        await self.ok_command("STOP")
        self.assertEqual(len(self.upstream.received), 5)
        self.assertEqual(len(self.packets(recording_id)), 2)
        recording = self.recording(recording_id)
        self.assertEqual(recording["network_coverage"], "partial")
        self.assertGreater(recording["counters"]["dropped"], 0)

    async def test_bounded_queue_overflow_reports_loss_without_blocking_delivery(self):
        await self.make_relay(queue_size=1)
        await self.ok_command("ON")
        recording_id = await self.record()
        self.relay.store.write_delay_seconds = 0.2
        started = time.monotonic()
        responses = await asyncio.gather(*(self.exchange(f"/overflow/{i}") for i in range(20)))
        elapsed = time.monotonic() - started
        self.assertTrue(all(b"200 OK" in response for response in responses))
        self.assertEqual(len(self.upstream.received), 20)
        self.assertLess(elapsed, 2.0, "bounded capture must not serialize 20 disk delays on forwarding")
        self.relay.store.write_delay_seconds = 0
        await self.ok_command("STOP")
        recording = self.recording(recording_id)
        self.assertEqual(recording["network_coverage"], "partial")
        self.assertGreater(recording["counters"]["dropped"], 0)

    async def test_storage_failure_visible_while_forwarding_continues(self):
        await self.ok_command("ON")
        recording_id = await self.record()
        self.relay.store.fail_writes = True
        self.assertIn(b"200 OK", await self.exchange("/disk-failed"))
        # Give the writer an event-loop turn to report its injected disk failure.
        await asyncio.sleep(0.05)
        self.relay.store.fail_writes = False
        await self.ok_command("STOP")
        recording = self.recording(recording_id)
        self.assertEqual(recording["network_coverage"], "partial")
        self.assertGreater(recording["counters"]["storage_errors"], 0)
        self.assertNotEqual(recording["status"], "completed")

    async def test_restart_retains_packet_detail_and_hash_and_starts_off(self):
        await self.ok_command("ON")
        recording_id = await self.record()
        self.assertIn(b"200 OK", await self.exchange("/persisted", b"synthetic-persisted"))
        await self.ok_command("STOP")
        before = self.packets(recording_id)
        await self.make_relay()
        status = await self.ok_command("STATUS")
        self.assertEqual(status["relay_state"], "off")
        self.assertEqual(self.packets(recording_id), before)
        self.assertEqual(self.recording(recording_id)["network_coverage"], "complete_for_supported_scope")

    async def test_rejects_unknown_schema_and_missing_record_identity(self):
        result = await self.relay.command({"schema_version": 999, "command_id": "unknown-version", "command": "ON"})
        self.assertFalse(result["ok"])
        self.assertFalse((await self.command("RECORD"))["ok"])
        self.assertEqual(self.read("recordings"), [])

    async def test_port_conflict_is_error_and_does_not_close_other_server(self):
        occupied = Upstream()
        await occupied.start()
        try:
            await self.make_relay(listen_port=occupied.port)
            result = await self.command("ON")
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "listen_failed")
            reader, writer = await asyncio.open_connection("127.0.0.1", occupied.port)
            try:
                writer.write(request_bytes("/listener-still-owned"))
                await writer.drain()
                self.assertIn(b"200 OK", await asyncio.wait_for(reader.read(), 1))
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await occupied.close()


    async def test_second_writer_is_rejected_without_recovering_active_recording(self):
        await self.ok_command("ON")
        recording_id = await self.record()
        second = Relay(Config(db=self.db, upstream_port=self.upstream.port))
        with self.assertRaisesRegex(RuntimeError, "database_in_use"):
            await second.start()
        self.assertEqual(self.relay.status()["active_recording"]["recording_id"], recording_id)
        self.assertIn(b"200 OK", await self.exchange("/first-owner-still-active"))
        await self.ok_command("STOP")
        self.assertEqual(self.recording(recording_id)["status"], "completed")

    async def test_pipelining_is_not_relayed_as_second_transaction(self):
        await self.ok_command("ON")
        recording_id = await self.record()
        response = await self.exchange("/unused", raw=request_bytes("/first") + request_bytes("/unsupported-second"))
        self.assertEqual(response.count(b"HTTP/1.1 200 OK"), 1)
        self.assertEqual(self.upstream.received, [("/first", b"")])
        await self.ok_command("STOP")
        self.assertEqual(len(self.packets(recording_id)), 1)

    async def test_killed_process_recovers_active_record_as_interrupted(self):
        await self.relay.close()
        self.relay = None
        script = """
import asyncio,json,sys
from pathlib import Path
from relay import Config,Relay
async def main():
    relay=Relay(Config(db=Path(sys.argv[1]),upstream_port=int(sys.argv[2])))
    await relay.start()
    await relay.command(dict(schema_version=1,command_id='child-on',command='ON'))
    result=await relay.command(dict(schema_version=1,command_id='child-record',command='RECORD',device_id='synthetic-loopback',app_id='dev.finsec.synthetic'))
    print(json.dumps(dict(port=relay.port,recording_id=result['result']['recording_id'])),flush=True)
    await asyncio.Event().wait()
asyncio.run(main())
"""
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-c", script, str(self.db), str(self.upstream.port),
            cwd=str(Path(__file__).resolve().parents[1]),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        writer = None
        try:
            info = json.loads(await asyncio.wait_for(child.stdout.readline(), 3))
            recording_id = info["recording_id"]
            entered, release = self.upstream.gate("/crash-pending")
            reader, writer = await asyncio.open_connection("127.0.0.1", info["port"])
            writer.write(request_bytes("/crash-pending"))
            await writer.drain()
            await asyncio.wait_for(entered.wait(), 1)
            for _ in range(200):
                result = query(self.db, kind="packets", recording_id=recording_id)
                if result.get("ok") and result["result"]:
                    break
                await asyncio.sleep(0.005)
            else:
                self.fail("pending request was not persisted before process kill")
            child.terminate()
            await asyncio.wait_for(child.wait(), 3)
            release.set()
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionResetError:
                pass  # Expected when the peer was intentionally killed.
            writer = None
            await self.make_relay()
            recovered = self.recording(recording_id)
            self.assertEqual(recovered["status"], "interrupted")
            self.assertEqual(recovered["network_coverage"], "partial")
            self.assertTrue(any(gap["reason"] == "process_interrupted" for gap in recovered["gaps"]))
            packet, = self.packets(recording_id)
            self.assertTrue(packet["incomplete"])
            self.assertEqual(packet["error"], "process_interrupted")
            self.assertIsNone(packet["response"])
            self.assertEqual(self.relay.status()["relay_state"], "off")
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionResetError:
                    pass  # Expected after intentional peer termination.
            if child.returncode is None:
                child.kill()
                await child.wait()


    async def test_command_journal_failure_reports_applied_and_replay_does_not_duplicate(self):
        await self.ok_command("ON")
        original = self.relay.store._command_save
        def failing_save(cid, digest, result):
            if cid == "journal-record":
                raise sqlite3.OperationalError("synthetic journal failure")
            return original(cid, digest, result)
        self.relay.store._command_save = failing_save
        payload = dict(device_id="synthetic-loopback", app_id="dev.finsec.synthetic")
        failed = await self.command("RECORD", "journal-record", **payload)
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["error"], "command_journal_error")
        self.assertTrue(failed["applied"])
        self.assertFalse(failed["durable_command"])
        recording_id = failed["result"]["recording_id"]
        self.relay.store._command_save = original
        repeated = await self.command("RECORD", "journal-record", **payload)
        self.assertEqual(failed, repeated)
        self.assertEqual(len(self.read("recordings")), 1)
        self.assertEqual(self.relay.status()["active_recording"]["recording_id"], recording_id)
        await self.ok_command("STOP")
        self.assertEqual(self.recording(recording_id)["network_coverage"], "partial")

    async def test_persisted_command_replay_after_restart_is_historical_result(self):
        old = await self.command("ON", "historical-on")
        self.assertTrue(old["ok"], old)
        await self.make_relay()
        self.assertEqual(self.relay.status()["relay_state"], "off")
        repeated = await self.command("ON", "historical-on")
        self.assertEqual(old, repeated)
        self.assertEqual(self.relay.status()["relay_state"], "off")
        self.assertNotEqual(old["result"]["session_id"], self.relay.session_id)


    async def test_record_started_off_then_enabled_retains_partial_gap(self):
        self.assertEqual(self.relay.status()["relay_state"], "off")
        recording_id = await self.record()
        await self.ok_command("ON")
        self.assertIn(b"200 OK", await self.exchange("/after-initial-gap"))
        await self.ok_command("STOP")
        recording = self.recording(recording_id)
        self.assertEqual(recording["network_coverage"], "partial")
        gap, = recording["gaps"]
        self.assertEqual(gap["reason"], "relay_off")
        self.assertIn("started_at", gap)
        self.assertIn("ended_at", gap)
        self.assertEqual(recording["persisted_packets"], 1)

    async def test_unrelated_command_journal_failure_does_not_mutate_completed_record(self):
        await self.ok_command("ON")
        recording_id = await self.record()
        self.assertIn(b"200 OK", await self.exchange("/completed"))
        await self.ok_command("STOP")
        persisted = self.recording(recording_id)
        snapshot = self.relay.status()["last_recording"]
        original = self.relay.store._command_save
        def failing_save(cid, digest, result):
            if cid == "unrelated-off":
                raise sqlite3.OperationalError("synthetic unrelated journal failure")
            return original(cid, digest, result)
        self.relay.store._command_save = failing_save
        try:
            response = await self.command("OFF", "unrelated-off")
        finally:
            self.relay.store._command_save = original
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], "command_journal_error")
        self.assertTrue(response["applied"])
        self.assertEqual(self.relay.status()["relay_state"], "off")
        self.assertEqual(self.recording(recording_id), persisted)
        self.assertEqual(self.relay.status()["last_recording"], snapshot)
        self.assertGreater(self.relay.status()["counters"]["storage_errors"], 0)

    async def test_stop_seals_before_slow_packet_writer_finishes(self):
        await self.ok_command("ON")
        recording_id = await self.record()
        entered = threading.Event()
        original = self.relay.store._packet
        def slow_packet(packet):
            entered.set()
            return original(packet)
        self.relay.store._packet = slow_packet
        self.relay.store.write_delay_seconds = 0.3
        self.assertIn(b"200 OK", await self.exchange("/before-slow-stop"))
        self.assertTrue(await asyncio.to_thread(entered.wait, 1))
        stop = asyncio.create_task(self.ok_command("STOP"))
        await asyncio.wait_for(self.wait_sealed(), 0.2)
        self.assertFalse(stop.done(), "STOP must seal admission before waiting for durable flush")
        self.assertIn(b"200 OK", await self.exchange("/after-slow-seal"))
        await stop
        self.relay.store.write_delay_seconds = 0
        packet, = self.packets(recording_id)
        self.assertIn(b"/before-slow-stop", base64.b64decode(packet["request"]["raw_base64"]))
        self.assertEqual(self.recording(recording_id)["persisted_packets"], 1)
        self.assertEqual(len(self.upstream.received), 2)

    async def test_record_storage_failure_does_not_activate_and_retry_is_cached(self):
        await self.ok_command("ON")
        self.relay.store.fail_writes = True
        payload = dict(device_id="synthetic-loopback", app_id="dev.finsec.synthetic")
        failed = await self.command("RECORD", "failed-record", **payload)
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["error"], "storage_write_error")
        self.assertIsNone(self.relay.status()["active_recording"])
        self.relay.store.fail_writes = False
        self.assertEqual(await self.command("RECORD", "failed-record", **payload), failed)
        self.assertIsNone(self.relay.status()["active_recording"])
        self.assertEqual(self.read("recordings"), [])
        fresh = await self.ok_command("RECORD", "fresh-record", **payload)
        self.assertEqual(self.relay.status()["active_recording"]["recording_id"], fresh["recording_id"])
        await self.ok_command("STOP")

    async def test_request_header_and_body_size_bounds_reject_before_forwarding(self):
        await self.make_relay(max_header_bytes=160, max_body_bytes=32)
        await self.ok_command("ON")
        recording_id = await self.record()
        body_overflow = request_bytes("/body-overflow", b"x" * 33)
        self.assertIn(b"400 Bad Request", await self.exchange("/unused", raw=body_overflow))
        self.assertEqual(self.relay.status()["last_error"], "request:body_too_large")
        header_overflow = b"GET /header-overflow HTTP/1.1\r\nHost: qa.invalid\r\nX-Synthetic: " + b"x" * 180 + b"\r\n\r\n"
        self.assertIn(b"400 Bad Request", await self.exchange("/unused", raw=header_overflow))
        self.assertEqual(self.relay.status()["last_error"], "request:header_too_large")
        await self.ok_command("STOP")
        self.assertEqual(self.upstream.received, [])
        self.assertEqual(self.recording(recording_id)["counters"]["decoder_errors"], 2)
        self.assertEqual(self.recording(recording_id)["network_coverage"], "partial")

    async def test_connection_limit_rejects_extra_client_and_reports_partial(self):
        await self.make_relay(max_connections=1)
        await self.ok_command("ON")
        recording_id = await self.record()
        entered, release = self.upstream.gate("/held-slot")
        held = self.client("/held-slot")
        await asyncio.wait_for(entered.wait(), 1)
        reader, writer = await asyncio.open_connection("127.0.0.1", self.relay.port)
        try:
            self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
        finally:
            writer.close()
            await writer.wait_closed()
        self.assertEqual(self.relay.status()["active_connections"], 1)
        self.assertEqual(self.relay.status()["counters"]["connection_rejections"], 1)
        release.set()
        self.assertIn(b"200 OK", await held)
        await self.ok_command("STOP")
        self.assertEqual(self.recording(recording_id)["network_coverage"], "partial")
        self.assertEqual(len(self.packets(recording_id)), 1)


    async def test_relay_cannot_target_its_own_fixed_port(self):
        with self.assertRaisesRegex(ValueError, "relay_upstream_port_conflict"):
            Relay(Config(db=self.db, upstream_port=self.upstream.port, listen_port=self.upstream.port))


if __name__ == "__main__":
    unittest.main()
