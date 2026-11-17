"""Thin adapter for the real P2 relay; all generated traffic is synthetic loopback.

P2's original session/run fields are preserved. The P4 report provides correlation,
not CHK-07 evidence or proof of actual device/app attribution.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import importlib.util
from pathlib import Path
import sys
import uuid


_SOURCE = Path(__file__).resolve().parents[2] / "p2-proxy-relay" / "relay.py"
_MODULE_NAME = "_p4_existing_p2_relay"
if _MODULE_NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_MODULE_NAME, _SOURCE)
    if _spec is None or _spec.loader is None:
        raise RuntimeError("P2_MODULE_UNAVAILABLE")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_NAME] = _module
    _spec.loader.exec_module(_module)
P2 = sys.modules[_MODULE_NAME]

_APP = "dev.finsec.synthetic"
_DEVICE = "synthetic-device-p4"
_REQUEST = (b"GET /synthetic/p4 HTTP/1.1\r\nHost: qa.invalid\r\n"
            b"Content-Length: 0\r\nConnection: close\r\n\r\n")
_BODY = b'{"fixture":"synthetic-only","source":"p4-loopback"}'
_RESPONSE = (b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(_BODY)).encode()
             + b"\r\nConnection: close\r\n\r\n" + _BODY)


class P2Adapter:
    """Own one capture and its resources. Constructor opens no resource.

    The caller owns and must join the capture Task before cleanup. A cancelled
    cleanup await propagates cancellation, but its owned cleanup Task continues;
    a later cleanup() awaits that same Task. Ownership cannot be released until
    cleanup reports completed. Filesystem stalls are not forcibly interrupted.
    """

    def __init__(self, output: Path, run_id: str, session_id: str,
                 device_id: str = _DEVICE):
        if device_id != _DEVICE or not all(isinstance(x, str) and x for x in (run_id, session_id)):
            raise ValueError("P2_SYNTHETIC_TARGET_REQUIRED")
        self.output = Path(output).resolve()
        self.db = self.output / "p2.sqlite"
        self.run_id, self.session_id, self.device_id = run_id, session_id, device_id
        self.relay = None
        self.server = None
        self.upstream_port = None
        self.relay_port = None
        self._handlers = set()
        self._writers = set()
        self._capture_task = None
        self._capture_started = False
        self._cleanup_task = None
        self._operations = []
        self._upstream_received = 0

    async def _owned(self, operation):
        # Cancelling an asyncio Future does not stop P2's SQLite executor thread.
        # Keep the enclosing operation alive and join it before closing resources.
        task = asyncio.create_task(operation)
        self._operations.append(task)
        return await asyncio.shield(task)

    async def _upstream(self, reader, writer):
        task = asyncio.current_task()
        self._handlers.add(task)
        self._writers.add(writer)
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 1)
            # P2 rewrites only Connection: close for this fixed, bodyless request.
            if request != _REQUEST:
                raise RuntimeError("P2_UNEXPECTED_SYNTHETIC_REQUEST")
            self._upstream_received += 1
            writer.write(_RESPONSE)
            await asyncio.wait_for(writer.drain(), 1)
        except (OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            pass
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, TimeoutError):
                pass
            self._writers.discard(writer)
            self._handlers.discard(task)

    async def _command(self, command, **kwargs):
        response = await self._owned(self.relay.command({
            "schema_version": 1, "command_id": "p4-" + uuid.uuid4().hex,
            "command": command, **kwargs,
        }))
        if not response.get("ok"):
            # A failed P2 command may still have applied; leave resources owned.
            raise RuntimeError("PROXY_ERROR:" + str(response.get("error", "unknown")))
        return response["result"]

    async def _exchange(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.relay_port)
        self._writers.add(writer)
        try:
            writer.write(_REQUEST)
            await asyncio.wait_for(writer.drain(), 1)
            response = await asyncio.wait_for(reader.read(), 2)
            if response != _RESPONSE or self._upstream_received != 1:
                raise RuntimeError("PROXY_ERROR:unexpected_response")
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, TimeoutError):
                pass
            self._writers.discard(writer)

    async def capture(self, proxy_on: bool = True) -> dict:
        if type(proxy_on) is not bool:
            raise ValueError("P2_PROXY_MODE_INVALID")
        if self._capture_started or self._cleanup_task is not None:
            raise RuntimeError("P2_CAPTURE_ALREADY_USED")
        self._capture_started = True
        self._capture_task = asyncio.current_task()
        try:
            return await self._capture(proxy_on)
        finally:
            self._capture_task = None

    async def _capture(self, proxy_on):
        self.output.mkdir(parents=True, exist_ok=True)
        # Never overwrite or reuse a previous capture and its command journal.
        if self.db.exists() or self.db.is_symlink():
            raise RuntimeError("P2_OUTPUT_EXISTS")
        self.server = await asyncio.start_server(self._upstream, "127.0.0.1", 0)
        self.upstream_port = self.server.sockets[0].getsockname()[1]
        self.relay = P2.Relay(P2.Config(
            db=self.db, upstream_port=self.upstream_port, listen_port=0,
            io_timeout=0.5, relay_off_drain_ms=100, record_stop_response_drain_ms=100,
        ))
        await self._owned(self.relay.start())
        if proxy_on:
            await self._command("ON")
            self.relay_port = self.relay.port
        recording = await self._command("RECORD", device_id=self.device_id, app_id=_APP)
        if proxy_on:
            await self._exchange()
        stopped = await self._command("STOP")
        packets = P2.query(self.db, "packets", recording_id=recording["recording_id"])
        if not packets.get("ok"):
            raise RuntimeError("PROXY_ERROR:packet_query")
        report = {
            "schema_version": "1.0", "synthetic": True, "source": "real_p2_loopback",
            "run_id": self.run_id, "session_id": self.session_id,
            "device_id": self.device_id, "app_id": _APP,
            "db": str(self.db), "p2_session_id": self.relay.session_id,
            "recording_id": recording["recording_id"],
            "packet_ids": [p["packet_id"] for p in packets["result"]],
            "network_coverage": stopped["network_coverage"],
            "persisted_packets": stopped["persisted_packets"], "proxy_on": proxy_on,
            "attribution": "unverified", "causal_for_chk07": False,
        }
        validate_reference(report)
        return report

    def _resources(self):
        relay = self.relay
        return {
            "operations_terminated": all(task.done() for task in self._operations),
            "upstream_listener_closed": self.server is None or not self.server.is_serving(),
            "upstream_handlers_terminated": not self._handlers,
            "streams_closed": not self._writers,
            "relay_closed": relay is None or not relay.started or relay.closed,
            "relay_listener_closed": relay is None or relay.server is None,
            "relay_handlers_terminated": relay is None or not relay.tasks,
            "relay_writer_terminated": relay is None or relay.writer_task is None or relay.writer_task.done(),
            "store_closed": relay is None or (relay.store.conn is None and relay.store.lock is None),
        }

    async def _cleanup(self):
        failures = []
        try:
            if self._operations:
                # In particular, an interrupted start may still be creating its
                # DB on an executor thread while relay.started is False.
                await asyncio.gather(*self._operations, return_exceptions=True)
            if self.relay is not None:
                await self.relay.close()  # P2 internally STOPs, OFFs, flushes, closes store.
        except Exception as exc:
            failures.append(type(exc).__name__)
        finally:
            if self.server is not None:
                self.server.close()
            for writer in list(self._writers):
                writer.close()
            handlers = list(self._handlers)
            for task in handlers:
                task.cancel()
            if handlers:
                await asyncio.gather(*handlers, return_exceptions=True)
            if self.server is not None:
                await self.server.wait_closed()
        resources = self._resources()
        if failures:
            return {"status": "failed", "reason_code": "P2_CLEANUP_ERROR", "resources": resources}
        if not all(resources.values()):
            return {"status": "unknown", "reason_code": "P2_RESOURCES_UNCONFIRMED", "resources": resources}
        return {"status": "completed", "reason_code": None, "resources": resources}

    async def cleanup(self) -> dict:
        current = asyncio.current_task()
        if self._capture_task is not None and self._capture_task is not current and not self._capture_task.done():
            return {"status": "unknown", "reason_code": "P2_CAPTURE_ACTIVE", "resources": self._resources()}
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup())
        # CancelledError deliberately propagates. The resource task remains owned.
        return copy.deepcopy(await asyncio.shield(self._cleanup_task))


def validate_reference(report: dict) -> bool:
    """Validate P4 correlation against actual sealed P2 DB content; no verdict.

    The containing run finalizer must separately compare report.run_id/session_id
    to its own immutable snapshot and restrict the DB to that run's output tree.
    """
    def require(condition):
        if not condition:
            raise RuntimeError("P2_REFERENCE_INVALID")

    require(isinstance(report, dict))
    required = {"schema_version", "synthetic", "source", "run_id", "session_id", "device_id",
                "app_id", "db", "p2_session_id", "recording_id", "packet_ids", "network_coverage",
                "persisted_packets", "proxy_on", "attribution", "causal_for_chk07"}
    require(required <= report.keys())
    require(report["schema_version"] == "1.0" and report["synthetic"] is True
            and report["source"] == "real_p2_loopback")
    require(report["device_id"] == _DEVICE and report["app_id"] == _APP)
    require(report["attribution"] == "unverified" and report["causal_for_chk07"] is False)
    require(all(isinstance(report[k], str) and report[k] for k in ("run_id", "session_id", "db")))
    require(type(report["proxy_on"]) is bool and type(report["persisted_packets"]) is int)
    require(isinstance(report["packet_ids"], list) and all(isinstance(x, str) for x in report["packet_ids"]))
    require(len(report["packet_ids"]) == len(set(report["packet_ids"])))
    db = Path(report["db"])
    require(db.name == "p2.sqlite" and db.is_file() and not db.is_symlink())
    recordings = P2.query(db, "recordings")
    require(recordings.get("ok"))
    require(len(recordings["result"]) == 1)
    record = recordings["result"][0]
    require(record["recording_id"] == report["recording_id"]
            and record["session_id"] == report["p2_session_id"] and record["run_id"] is None)
    require(record["status"] == "completed" and record["network_coverage"] == report["network_coverage"])
    require(record["attribution"]["device_id"] == _DEVICE and record["attribution"]["app_id"] == _APP
            and record["attribution"]["confidence"] == "unverified")
    expected_count = 1 if report["proxy_on"] else 0
    expected_coverage = "complete_for_supported_scope" if report["proxy_on"] else "none"
    require(report["persisted_packets"] == record["persisted_packets"] == expected_count)
    require(report["network_coverage"] == expected_coverage)
    packets = P2.query(db, "packets", recording_id=report["recording_id"])
    require(packets.get("ok"))
    require([p["packet_id"] for p in packets["result"]] == report["packet_ids"]
            and len(packets["result"]) == expected_count)
    for sequence, row in enumerate(packets["result"], 1):
        detail = P2.query(db, "detail", packet_id=row["packet_id"])
        require(detail.get("ok"))
        packet = detail["result"]
        require(packet["recording_id"] == report["recording_id"]
                and packet["session_id"] == report["p2_session_id"] and packet["run_id"] is None
                and packet["sequence"] == sequence and packet["incomplete"] is False
                and packet["error"] is None and packet["endpoint"]["host"] == "127.0.0.1")
        for key, expected in (("request", _REQUEST), ("response", _RESPONSE)):
            message = packet[key]
            require(isinstance(message, dict) and message["truncated"] is False)
            try:
                raw = base64.b64decode(message["raw_base64"], validate=True)
            except (ValueError, TypeError):
                raise RuntimeError("P2_REFERENCE_INVALID") from None
            digest = hashlib.sha256(raw).hexdigest()
            require(raw == expected and message["sha256"] == message["stored_sha256"] == digest
                    and message["size"] == message["stored_size"] == len(raw))
    return True
