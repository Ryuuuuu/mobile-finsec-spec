"""Actual P3 integration: no provider, real device or network required."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration import p3_adapter


class P3AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-p4-p3-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contract = p3_adapter.snapshot()
        self.counter = 0

    def execute(self, variant="pass", **kwargs):
        self.counter += 1
        return p3_adapter.run_check(
            variant, self.root / f"bundle-{self.counter}",
            run_id="synthetic-run-p4", session_id="synthetic-session-p4",
            attempt_id=f"synthetic-attempt-{self.counter}",
            expected_snapshot=self.contract, **kwargs)

    def test_three_actual_p3_verdicts_and_verified_scopes(self):
        for variant in ("pass", "fail", "inconclusive"):
            with self.subTest(variant=variant):
                report = self.execute(variant)
                result = p3_adapter.validate_reference(report, self.contract)
                self.assertEqual(result["verdict"], variant)
                self.assertEqual(result["execution_status"], "completed")
                self.assertTrue(result["reason"].strip())
                self.assertTrue(result["scope_results"])
                self.assertEqual(result["backend_snapshot"]["ai"], False)
                self.assertTrue((Path(report["bundle"]) / "finalized.json").is_file())

    def test_identity_single_device_and_no_p2_route_references(self):
        report = self.execute()
        record = p3_adapter.p3_protocol.load_json(Path(report["bundle"]) / "run.json")
        fixture = record["input"]
        for key in ("run_id", "session_id", "attempt_id"):
            self.assertEqual(fixture[key], report[key])
        self.assertEqual(set(fixture["device"].values()), {"synthetic-device-p4"})
        self.assertEqual({o["device_id"] for o in fixture["observations"]}, {"synthetic-device-p4"})
        self.assertEqual(fixture["route_refs"], [])
        self.assertEqual(fixture["packet_refs"], [])
        self.assertEqual(record["contract_snapshot"], self.contract)
        self.assertEqual(set(self.contract["skills"]), {"common", "aos"})

    def test_evidence_ids_are_namespaced_by_bundle_and_attempt(self):
        first, second = self.execute(), self.execute()
        self.assertEqual(first["result"]["evidence_refs"], second["result"]["evidence_refs"])
        self.assertFalse(set(first["evidence_refs"]) & set(second["evidence_refs"]))
        for ref in first["evidence_refs"]:
            self.assertIn(first["bundle"], ref)
            self.assertIn(first["attempt_id"], ref)

    def test_cleanup_failure_preserves_verified_fail(self):
        for status in ("failed", "unknown"):
            with self.subTest(cleanup=status):
                result = self.execute("fail", cleanup_fault=status)["result"]
                self.assertEqual(result["verdict"], "fail")
                self.assertEqual(result["execution_status"], "failed")
                self.assertEqual(result["cleanup_status"], status)
                self.assertTrue(result["recovery_required"])
                self.assertTrue(result["follow_up_blocked"])

    def test_changed_snapshot_is_rejected_before_execution(self):
        with patch.object(p3_adapter, "snapshot", return_value={"changed": True}):
            with self.assertRaisesRegex(p3_adapter.P3AdapterError, "SNAPSHOT_CHANGED"):
                self.execute()
        self.assertFalse(list(self.root.iterdir()))

    def test_valid_but_different_expected_snapshot_is_rejected_on_validation(self):
        report = self.execute()
        altered = deepcopy(self.contract)
        altered["manifest"]["title"] += " synthetic change"
        with self.assertRaisesRegex(p3_adapter.P3AdapterError, "SNAPSHOT_CHANGED"):
            p3_adapter.validate_reference(report, altered)

    def test_invalid_skill_hash_is_rejected(self):
        self.contract["skills"]["common"] += "\nchanged"
        with self.assertRaisesRegex(p3_adapter.p3_protocol.ContractError, "SKILL_HASH_MISMATCH"):
            self.execute()

    def test_corrupted_p3_blob_is_rejected(self):
        report = self.execute()
        blob = next((Path(report["bundle"]) / "blobs").iterdir())
        blob.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(p3_adapter.p3_protocol.ContractError):
            p3_adapter.validate_reference(report)

    def test_cross_run_session_and_attempt_references_are_rejected(self):
        report = self.execute()
        for key in ("run_id", "session_id", "attempt_id"):
            with self.subTest(key=key):
                altered = deepcopy(report)
                altered[key] = "synthetic-another-reference"
                with self.assertRaisesRegex(p3_adapter.P3AdapterError, "ID_MISMATCH"):
                    p3_adapter.validate_reference(altered)

    def test_copied_verdict_or_evidence_tampering_is_rejected(self):
        report = self.execute()
        altered = deepcopy(report)
        altered["result"]["verdict"] = "fail"
        with self.assertRaisesRegex(p3_adapter.P3AdapterError, "RESULT_MISMATCH"):
            p3_adapter.validate_reference(altered)
        altered = deepcopy(report)
        altered["evidence_refs"] = altered["result"]["evidence_refs"]
        with self.assertRaisesRegex(p3_adapter.P3AdapterError, "EVIDENCE_MISMATCH"):
            p3_adapter.validate_reference(altered)

    def test_unsupported_variant_device_fault_and_non_synthetic_id_rejected(self):
        for variant in ("../pass", "real", "ios"):
            with self.subTest(variant=variant):
                with self.assertRaises(p3_adapter.P3AdapterError):
                    self.execute(variant)
        with self.assertRaises(p3_adapter.P3AdapterError):
            self.execute(device_id="real-device")
        with self.assertRaises(p3_adapter.P3AdapterError):
            self.execute(cleanup_fault="ignore")
        with self.assertRaises(p3_adapter.p3_protocol.ContractError):
            p3_adapter.run_check("pass", self.root / "invalid", run_id="real-run",
                session_id="synthetic-session", attempt_id="synthetic-attempt",
                expected_snapshot=self.contract)
        self.assertFalse(list(self.root.iterdir()))

    def test_output_directory_is_never_overwritten(self):
        report = self.execute()
        result_path = Path(report["bundle"]) / "result.json"
        previous = result_path.read_bytes()
        with self.assertRaisesRegex(p3_adapter.p3_protocol.ContractError, "OUTPUT_ALREADY_EXISTS"):
            p3_adapter.run_check("fail", Path(report["bundle"]),
                run_id="synthetic-run-p4", session_id="synthetic-session-p4",
                attempt_id="synthetic-another-attempt", expected_snapshot=self.contract)
        self.assertEqual(result_path.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
