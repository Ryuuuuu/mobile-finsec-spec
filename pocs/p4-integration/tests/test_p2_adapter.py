"""Real P2 code, fixed synthetic HTTP, ephemeral loopback ports and SQLite."""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from contextlib import closing
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integration.p2_adapter import P2, P2Adapter, validate_reference


class P2AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="p4-p2-test-")
        self.adapter = P2Adapter(Path(self.temp.name), "synthetic-run-p4", "synthetic-session-p4")

    async def asyncTearDown(self):
        # Restore any fault before attempting the adapter's idempotent cleanup.
        await self.adapter.cleanup()
        self.temp.cleanup()

    async def test_real_capture_and_payload_validation_preserve_p2_ids(self):
        report = await self.adapter.capture()
        self.assertTrue(validate_reference(report))
        self.assertEqual(report["source"], "real_p2_loopback")
        self.assertEqual(report["run_id"], "synthetic-run-p4")
        self.assertEqual(report["persisted_packets"], 1)
        self.assertEqual(report["network_coverage"], "complete_for_supported_scope")
        self.assertFalse(report["causal_for_chk07"])
        self.assertNotIn("verdict", report)
        packet = P2.query(self.adapter.db, "detail", packet_id=report["packet_ids"][0])["result"]
        self.assertIsNone(packet["run_id"])
        self.assertEqual(packet["session_id"], report["p2_session_id"])
        self.assertNotEqual(packet["session_id"], report["session_id"])
        self.assertEqual(self.adapter.relay.relay_state, "on")  # STOP is not OFF.

    async def test_proxy_off_seals_empty_recording_without_claiming_capture(self):
        report = await self.adapter.capture(proxy_on=False)
        self.assertTrue(validate_reference(report))
        self.assertEqual(report["network_coverage"], "none")
        self.assertEqual(report["packet_ids"], [])
        self.assertEqual(report["persisted_packets"], 0)
        self.assertEqual(self.adapter.relay.relay_state, "off")
        self.assertIsNone(self.adapter.relay_port)

    async def test_cleanup_recovers_ports_and_db_lock_and_preserves_query(self):
        report = await self.adapter.capture()
        ports = (self.adapter.upstream_port, self.adapter.relay_port)
        cleanup = await self.adapter.cleanup()
        self.assertEqual(cleanup["status"], "completed")
        self.assertTrue(all(cleanup["resources"].values()))
        self.assertEqual(await self.adapter.cleanup(), cleanup)
        self.assertTrue(validate_reference(report))
        for port in ports:
            with self.assertRaises(OSError):
                await asyncio.open_connection("127.0.0.1", port)
            server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", port)
            server.close()
            await server.wait_closed()
        reopened = P2.Relay(P2.Config(db=self.adapter.db, upstream_port=ports[0]))
        await reopened.start()
        try:
            self.assertEqual(reopened.relay_state, "off")
        finally:
            await reopened.close()

    async def test_constructor_and_unused_cleanup_allocate_no_resources(self):
        self.assertFalse(self.adapter.db.exists())
        self.assertIsNone(self.adapter.server)
        cleanup = await self.adapter.cleanup()
        self.assertEqual(cleanup["status"], "completed")
        self.assertFalse(self.adapter.db.exists())
        with self.assertRaisesRegex(RuntimeError, "ALREADY_USED"):
            await self.adapter.capture()

    async def test_capture_cannot_overwrite_previous_database(self):
        self.adapter.db.write_bytes(b"owned-by-previous-run")
        with self.assertRaisesRegex(RuntimeError, "OUTPUT_EXISTS"):
            await self.adapter.capture()
        self.assertEqual(self.adapter.db.read_bytes(), b"owned-by-previous-run")
        self.assertIsNone(self.adapter.server)

    async def test_reference_rejects_wrong_recording_session_and_coverage(self):
        report = await self.adapter.capture()
        for key, value in (("recording_id", "other"), ("p2_session_id", "other"),
                           ("network_coverage", "none"), ("packet_ids", []),
                           ("causal_for_chk07", True), ("synthetic", False)):
            with self.subTest(field=key):
                changed = copy.deepcopy(report)
                changed[key] = value
                with self.assertRaisesRegex(RuntimeError, "REFERENCE_INVALID"):
                    validate_reference(changed)

    async def test_reference_rejects_actual_db_payload_corruption(self):
        report = await self.adapter.capture()
        await self.adapter.cleanup()
        with closing(sqlite3.connect(self.adapter.db)) as connection, connection:
            connection.execute("UPDATE packets SET request=?", (b"corrupted",))
        with self.assertRaisesRegex(RuntimeError, "REFERENCE_INVALID"):
            validate_reference(report)

    async def test_upstream_failure_is_partial_and_cleanup_still_closes_resources(self):
        original = self.adapter._exchange

        async def fail_upstream():
            self.adapter.server.close()
            await self.adapter.server.wait_closed()
            await original()

        with patch.object(self.adapter, "_exchange", fail_upstream):
            with self.assertRaisesRegex(RuntimeError, "PROXY_ERROR"):
                await self.adapter.capture()
        cleanup = await self.adapter.cleanup()
        self.assertEqual(cleanup["status"], "completed")
        records = P2.query(self.adapter.db, "recordings")["result"]
        self.assertEqual(records[0]["network_coverage"], "partial")
        packets = P2.query(self.adapter.db, "packets", recording_id=records[0]["recording_id"])["result"]
        self.assertTrue(packets[0]["incomplete"])
        self.assertIn("upstream:", packets[0]["error"])

    async def test_cleanup_waits_for_capture_task_termination(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.adapter._exchange

        async def delayed():
            entered.set()
            await release.wait()
            await original()

        with patch.object(self.adapter, "_exchange", delayed):
            task = asyncio.create_task(self.adapter.capture())
            await entered.wait()
            cleanup = await self.adapter.cleanup()
            self.assertEqual(cleanup["status"], "unknown")
            self.assertEqual(cleanup["reason_code"], "P2_CAPTURE_ACTIVE")
            self.assertFalse(self.adapter.relay.closed)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        cleanup = await self.adapter.cleanup()
        self.assertEqual(cleanup["status"], "completed")
        self.assertTrue(all(cleanup["resources"].values()))

    async def test_cancelled_cleanup_propagates_and_owned_cleanup_is_joinable(self):
        await self.adapter.capture()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.adapter.relay.close

        async def delayed_close():
            entered.set()
            await release.wait()
            await original()

        with patch.object(self.adapter.relay, "close", delayed_close):
            caller = asyncio.create_task(self.adapter.cleanup())
            await entered.wait()
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
            self.assertFalse(self.adapter._cleanup_task.done())
            release.set()
            cleanup = await self.adapter.cleanup()
        self.assertEqual(cleanup["status"], "completed")

    async def test_cancel_during_start_joins_owned_operation_before_release(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = P2.Relay.start

        async def delayed_start(relay):
            entered.set()
            await release.wait()
            await original(relay)

        with patch.object(P2.Relay, "start", delayed_start):
            capture = asyncio.create_task(self.adapter.capture())
            await entered.wait()
            capture.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await capture
            self.assertFalse(self.adapter.relay.started)
            cleanup = asyncio.create_task(self.adapter.cleanup())
            await asyncio.sleep(0)
            self.assertFalse(cleanup.done())
            release.set()
            result = await cleanup
        self.assertEqual(result["status"], "completed")
        self.assertTrue(self.adapter.relay.closed)
        self.assertTrue(result["resources"]["operations_terminated"])

    async def test_cleanup_error_remains_failed_and_does_not_claim_release(self):
        await self.adapter.capture()
        original = self.adapter.relay.close

        async def failed_close():
            raise OSError("synthetic cleanup fault")

        with patch.object(self.adapter.relay, "close", failed_close):
            result = await self.adapter.cleanup()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason_code"], "P2_CLEANUP_ERROR")
        self.assertFalse(result["resources"]["relay_closed"])
        self.assertEqual(await self.adapter.cleanup(), result)
        # Test harness releases its own resources; adapter retains failed outcome.
        await original()

    async def test_only_synthetic_device_and_boolean_mode_are_accepted(self):
        with self.assertRaisesRegex(ValueError, "SYNTHETIC_TARGET"):
            P2Adapter(Path(self.temp.name), "run", "session", device_id="actual-device")
        with self.assertRaisesRegex(ValueError, "PROXY_MODE"):
            await self.adapter.capture(proxy_on=1)


if __name__ == "__main__":
    unittest.main()
