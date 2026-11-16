"""Independent acceptance tests: synthetic fixtures only, never a real device."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from os_tamper.engine import run, validate_bundle
from os_tamper.protocol import ContractError, load_contract, load_json, validate_input
import os_tamper.protocol as protocol

ROOT = Path(__file__).resolve().parents[1]


class SyntheticPocTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-p3-tests-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.counter = 0

    def fixture(self, name="pass"):
        return json.loads((ROOT / "fixtures" / f"{name}.json").read_text())

    def output(self):
        self.counter += 1
        return self.base / f"synthetic-output-{self.counter}"

    def execute(self, fixture=None, **kwargs):
        fixture = self.fixture() if fixture is None else fixture
        output = self.output()
        result = run(fixture, output, **kwargs)
        self.assertEqual(result, validate_bundle(output))
        self.assertTrue(result["synthetic"])
        self.assertTrue(result["reason"].strip())
        self.assertTrue(result["reason_code"])
        return result, output

    def inconclusive(self, fixture, status="completed"):
        result, output = self.execute(fixture)
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertEqual(result["execution_status"], status)
        return result, output

    def add_scope(self, fixture, include_observations=False, outcome="blocked"):
        scope = deepcopy(fixture["profile"]["scopes"][0])
        scope["scope_id"] = "synthetic-scope-second"
        scope["service_id"] = "synthetic-service-second"
        scope["checkpoint_id"] = "synthetic-checkpoint-second"
        fixture["profile"]["scopes"].append(scope)
        if include_observations:
            for observation in deepcopy(fixture["observations"][:2]):
                observation["observation_id"] += "-second"
                for field in ("scope_id", "service_id", "checkpoint_id"):
                    observation[field] = scope[field]
                if observation["phase"] == "test":
                    observation["outcome"] = outcome
                    observation["block_reason"] = "os_tamper" if outcome == "blocked" else "none"
                fixture["observations"].append(observation)
        return fixture

    def rewrite(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def contract_copy(self):
        directory = self.base / "synthetic-contract"
        shutil.copytree(protocol.CHECK_DIR, directory)
        return directory

    def test_three_verdicts_repeat_three_times_with_identical_artifacts(self):
        for name in ("pass", "fail", "inconclusive"):
            with self.subTest(verdict=name):
                snapshots = []
                for _ in range(3):
                    result, output = self.execute(self.fixture(name))
                    self.assertEqual(result["verdict"], name)
                    self.assertEqual(result["execution_status"], "completed")
                    snapshots.append({str(p.relative_to(output)): p.read_bytes()
                                      for p in output.rglob("*") if p.is_file()})
                self.assertEqual(snapshots[0], snapshots[1])
                self.assertEqual(snapshots[1], snapshots[2])

    def test_stock_baseline_alone_is_not_pass(self):
        fixture = self.fixture()
        fixture["observations"] = fixture["observations"][:1]
        self.inconclusive(fixture)

    def test_no_observations_is_not_pass(self):
        fixture = self.fixture()
        fixture["observations"] = []
        self.inconclusive(fixture)

    def test_unknown_stock_or_missing_state_proof_is_not_pass(self):
        for field, value in (("state", "unknown"), ("state", "stock"),
                             ("state_proof", "missing")):
            with self.subTest(field=field, value=value):
                fixture = self.fixture()
                fixture["observations"][1][field] = value
                self.inconclusive(fixture)

    def test_launch_crash_unknown_and_absent_oracle_are_not_pass(self):
        for field, value in (("outcome", "launch_only"), ("outcome", "crash"),
                             ("outcome", "unknown"), ("oracle", "none")):
            with self.subTest(field=field, value=value):
                fixture = self.fixture()
                fixture["observations"][1][field] = value
                self.inconclusive(fixture)

    def test_unattributed_service_block_is_not_pass(self):
        for reason in ("other", "unknown", "none"):
            with self.subTest(reason=reason):
                fixture = self.fixture()
                fixture["observations"][1]["block_reason"] = reason
                self.inconclusive(fixture)

    def test_missing_or_invalid_normal_service_baseline_is_inconclusive(self):
        fixture = self.fixture("fail")
        fixture["observations"] = fixture["observations"][1:]
        self.inconclusive(fixture)
        for field, value in (("outcome", "blocked"), ("oracle", "none"),
                             ("state", "unknown"), ("state_proof", "missing")):
            with self.subTest(field=field, value=value):
                fixture = self.fixture("fail")
                fixture["observations"][0][field] = value
                self.inconclusive(fixture)

    def test_target_or_service_mismatch_is_inconclusive(self):
        for field, value in (("device_id", "synthetic-wrong-device"),
                             ("build_sha256", "b" * 64),
                             ("service_id", "synthetic-wrong-service"),
                             ("checkpoint_id", "synthetic-wrong-checkpoint")):
            for phase_index in (0, 1):
                with self.subTest(field=field, phase=phase_index):
                    fixture = self.fixture()
                    fixture["observations"][phase_index][field] = value
                    self.inconclusive(fixture)

    def test_conflicting_observations_in_one_scope_do_not_prove_a_verdict(self):
        for field, value in (("outcome", "allowed"), ("state", "stock"),
                             ("block_reason", "other"), ("state_proof", "missing")):
            with self.subTest(field=field):
                fixture = self.fixture()
                conflict = deepcopy(fixture["observations"][1])
                conflict["observation_id"] = "synthetic-observation-conflict"
                conflict[field] = value
                fixture["observations"].append(conflict)
                self.inconclusive(fixture)

    def test_empty_scope_and_undefined_checkpoint_are_not_run(self):
        fixture = self.fixture()
        fixture["profile"]["scopes"] = []
        fixture["observations"] = []
        self.inconclusive(fixture, "not_run")
        fixture = self.fixture()
        fixture["profile"]["scopes"][0]["checkpoint_id"] = None
        self.inconclusive(fixture, "not_run")

    def test_partial_scope_prevents_global_pass(self):
        fixture = self.add_scope(self.fixture())
        self.inconclusive(fixture)

    def test_all_scopes_must_pass(self):
        fixture = self.add_scope(self.fixture(), True)
        result, _ = self.execute(fixture)
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(len(result["scope_results"]), 2)

    def test_coherent_fail_precedes_missing_independent_scope(self):
        fixture = self.add_scope(self.fixture("fail"))
        result, _ = self.execute(fixture)
        self.assertEqual(result["verdict"], "fail")
        self.assertTrue(result["limitations"])

    def test_coherent_fail_precedes_conflicting_independent_scope(self):
        fixture = self.add_scope(self.fixture("fail"), True)
        conflict = deepcopy(fixture["observations"][-1])
        conflict["observation_id"] = "synthetic-observation-second-conflict"
        conflict["state"] = "stock"
        fixture["observations"].append(conflict)
        result, _ = self.execute(fixture)
        self.assertEqual(result["verdict"], "fail")
        self.assertIn("inconclusive", [s["verdict"] for s in result["scope_results"]])

    def test_faults_before_and_during_observation_are_inconclusive(self):
        for kind, status in (("timeout", "timed_out"), ("cancel", "cancelled"),
                             ("tool_error", "failed")):
            for after in (0, 1):
                with self.subTest(kind=kind, after=after):
                    fixture = self.fixture()
                    fixture["faults"].update(interrupt_after=after, interrupt_kind=kind)
                    result, _ = self.inconclusive(fixture, status)
                    self.assertEqual(result["cleanup_status"], "completed")

    def test_completed_vulnerability_survives_later_fault(self):
        for kind, status in (("timeout", "timed_out"), ("cancel", "cancelled"),
                             ("tool_error", "failed")):
            with self.subTest(kind=kind):
                fixture = self.add_scope(self.fixture("fail"), True)
                fixture["faults"].update(interrupt_after=2, interrupt_kind=kind)
                result, _ = self.execute(fixture)
                self.assertEqual(result["verdict"], "fail")
                self.assertEqual(result["execution_status"], status)

    def test_explicit_cancel_skips_observation_but_records_cleanup(self):
        result, _ = self.execute(cancel=True)
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertEqual(result["execution_status"], "cancelled")
        self.assertEqual(result["cleanup_status"], "completed")
        self.assertEqual(result["observation_refs"], [])

    def test_cleanup_failed_and_unknown_preserve_validated_vulnerability(self):
        for status in ("failed", "unknown"):
            with self.subTest(status=status):
                fixture = self.fixture("fail")
                fixture["faults"]["cleanup"] = status
                result, _ = self.execute(fixture)
                self.assertEqual(result["verdict"], "fail")
                self.assertEqual(result["execution_status"], "failed")
                self.assertEqual(result["cleanup_status"], status)
                self.assertTrue(result["follow_up_blocked"])
                self.assertTrue(result["recovery_required"])

    def test_successful_cleanup_does_not_imply_pass(self):
        result, _ = self.execute(self.fixture("inconclusive"))
        self.assertEqual(result["cleanup_status"], "completed")
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertFalse(result["follow_up_blocked"])

    def test_unknown_version_field_platform_and_real_mode_rejected(self):
        changes = (("schema_version", "999"), ("synthetic", False),
                   ("mode", "real"), ("platform", "ios"),
                   ("unexpected", "synthetic-extra"), ("check_id", "CHK-08"))
        for field, value in changes:
            with self.subTest(field=field):
                fixture = self.fixture()
                fixture[field] = value
                with self.assertRaises(ContractError):
                    validate_input(fixture)

    def test_missing_required_input_rejected_before_output_creation(self):
        fixture = self.fixture()
        del fixture["device"]
        output = self.output()
        with self.assertRaises(ContractError):
            run(fixture, output)
        self.assertFalse(output.exists())

    def test_duplicate_scope_or_observation_identifiers_rejected(self):
        fixture = self.fixture()
        fixture["profile"]["scopes"].append(deepcopy(fixture["profile"]["scopes"][0]))
        with self.assertRaises(ContractError):
            validate_input(fixture)
        fixture = self.fixture()
        fixture["observations"].append(deepcopy(fixture["observations"][0]))
        with self.assertRaises(ContractError):
            validate_input(fixture)

    def test_external_evidence_route_packet_and_command_inputs_rejected(self):
        for field, value in (("evidence_path", "/tmp/synthetic-private.json"),
                             ("command", "synthetic-no-command"),
                             ("route_refs", ["synthetic-route"]),
                             ("packet_refs", ["synthetic-packet"])):
            with self.subTest(field=field):
                fixture = self.fixture()
                fixture[field] = value
                with self.assertRaises(ContractError):
                    validate_input(fixture)

    def test_malformed_duplicate_key_and_nonfinite_json_rejected(self):
        path = self.base / "synthetic-invalid.json"
        for content in ('{', '{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}',
                        '{"a":-Infinity}', '{"a":1e400}', '{"a":-1e400}'):
            with self.subTest(content=content):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ContractError):
                    load_json(path)

    def test_valid_fractional_utc_timestamp_and_invalid_dates(self):
        fixture = self.fixture()
        fixture["timestamp"] = "2026-11-16T00:00:00.123Z"
        validate_input(fixture)
        for timestamp in ("2026-02-30T00:00:00Z", "2026-11-16T25:00:00Z", "not-a-date"):
            with self.subTest(timestamp=timestamp):
                fixture["timestamp"] = timestamp
                with self.assertRaises(ContractError):
                    validate_input(fixture)

    def test_non_synthetic_identifiers_are_rejected(self):
        for field in ("project_id", "session_id", "run_id", "attempt_id"):
            with self.subTest(field=field):
                fixture = self.fixture()
                fixture[field] = "not-synthetic"
                with self.assertRaises(ContractError):
                    validate_input(fixture)

    def test_contract_and_required_skills_load(self):
        manifest = load_contract()
        self.assertEqual(manifest["check_id"], "CHK-07")
        self.assertEqual(manifest["source_scope_status"], "provisional")
        self.assertLessEqual(len(list(protocol.CHECK_DIR.rglob("SKILL.md"))), 3)

    def test_missing_common_skill_rejected(self):
        directory = self.contract_copy()
        (directory / "common" / "SKILL.md").unlink()
        with self.assertRaises(ContractError):
            load_contract(directory)

    def test_modified_aos_skill_hash_rejected(self):
        directory = self.contract_copy()
        path = directory / "aos" / "SKILL.md"
        path.write_text(path.read_text() + "\nSynthetic changed rule.\n")
        with self.assertRaises(ContractError):
            load_contract(directory)

    def test_manifest_unknown_version_rejected(self):
        directory = self.contract_copy()
        path = directory / "manifest.yaml"
        manifest = json.loads(path.read_text())
        manifest["schema_version"] = "999"
        self.rewrite(path, manifest)
        with self.assertRaises(ContractError):
            load_contract(directory)

    def test_malformed_manifest_root_rejected_as_contract_error(self):
        directory = self.contract_copy()
        path = directory / "manifest.yaml"
        for value in ([], "synthetic-invalid-manifest", None):
            with self.subTest(value=value):
                self.rewrite(path, value)
                with self.assertRaises(ContractError):
                    load_contract(directory)

    def test_manifest_required_policies_and_schema_references_rejected_when_missing(self):
        directory = self.contract_copy()
        path = directory / "manifest.yaml"
        original = json.loads(path.read_text())
        for field in ("steps", "fixture_schema", "result_schema", "side_effect_policy",
                      "idempotency_policy", "initial_state_verification"):
            with self.subTest(field=field):
                manifest = deepcopy(original)
                del manifest[field]
                self.rewrite(path, manifest)
                with self.assertRaises(ContractError):
                    load_contract(directory)

    def test_skill_rule_conflict_rejected_even_with_updated_hash(self):
        directory = self.contract_copy()
        path = directory / "aos" / "SKILL.md"
        original_content = path.read_text()
        manifest_path = directory / "manifest.yaml"
        original_manifest = json.loads(manifest_path.read_text())
        changes = (("CHK-07.synthetic.v1", "CHK-07.synthetic.conflicting"),
                   ('"synthetic":true', '"synthetic":1'))
        for before, after in changes:
            with self.subTest(replacement=after):
                self.assertIn(before, original_content)
                content = original_content.replace(before, after)
                path.write_text(content, encoding="utf-8")
                manifest = deepcopy(original_manifest)
                manifest["skills"]["aos"]["sha256"] = hashlib.sha256(content.encode()).hexdigest()
                self.rewrite(manifest_path, manifest)
                with self.assertRaises(ContractError):
                    load_contract(directory)

    def test_oversize_json_rejected(self):
        path = self.base / "synthetic-oversize.json"
        path.write_bytes(b" " * (protocol.MAX_BYTES + 1))
        with self.assertRaises(ContractError):
            load_json(path)

    def test_logical_step_timeout_records_incomplete_observation(self):
        fixture = self.fixture()
        fixture["observations"][1]["cost_ms"] = 1001
        result, _ = self.inconclusive(fixture, "timed_out")
        self.assertNotIn(fixture["observations"][1]["observation_id"], result["observation_refs"])
        self.assertEqual(result["cleanup_status"], "completed")

    def test_logical_total_timeout_is_independent_of_step_budget(self):
        fixture = self.fixture()
        fixture["observations"][0]["cost_ms"] = 1000
        fixture["observations"][1]["cost_ms"] = 1000
        for number in range(10):
            observation = deepcopy(fixture["observations"][1])
            observation["observation_id"] = f"synthetic-repeat-{number}"
            fixture["observations"].append(observation)
        result, _ = self.execute(fixture)
        self.assertEqual(result["execution_status"], "timed_out")
        self.assertEqual(result["duration_monotonic_ms"], 10000)
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertEqual(result["scope_results"][0]["reason_code"], "INCOMPLETE_OBSERVATION_SET")
        self.assertLess(len(result["observation_refs"]), len(fixture["observations"]))
        self.assertEqual(result["cleanup_status"], "completed")

    def test_allowed_with_simultaneous_block_claim_is_inconclusive(self):
        fixture = self.fixture("fail")
        fixture["observations"][1]["block_reason"] = "os_tamper"
        self.inconclusive(fixture)

    def test_unknown_scope_and_conflicting_fault_configuration_rejected(self):
        fixture = self.fixture()
        fixture["observations"][1]["scope_id"] = "synthetic-undefined-scope"
        with self.assertRaises(ContractError):
            validate_input(fixture)
        fixture = self.fixture()
        fixture["faults"]["interrupt_after"] = 0
        with self.assertRaises(ContractError):
            validate_input(fixture)

    def test_uncollected_same_scope_observation_prevents_pass(self):
        fixture = self.fixture()
        later = deepcopy(fixture["observations"][1])
        later["observation_id"] = "synthetic-later-observation"
        fixture["observations"].append(later)
        fixture["faults"].update(interrupt_after=2, interrupt_kind="cancel")
        result, _ = self.inconclusive(fixture, "cancelled")
        self.assertEqual(len(result["observation_refs"]), 2)
        self.assertEqual(result["scope_results"][0]["reason_code"], "INCOMPLETE_OBSERVATION_SET")

    def test_submillisecond_timestamp_is_preserved(self):
        fixture = self.fixture()
        fixture["timestamp"] = "2026-11-16T00:00:00.000123Z"
        result, output = self.execute(fixture)
        self.assertEqual(result["started_at"], fixture["timestamp"])
        self.assertEqual(result["ended_at"], "2026-11-16T00:00:00.020123Z")
        events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
        self.assertEqual(events[0]["timestamp"], fixture["timestamp"])

    def test_unknown_manifest_field_and_text_rule_conflicts_rejected(self):
        directory = self.contract_copy()
        path = directory / "manifest.yaml"
        original = json.loads(path.read_text())
        for field in ("unexpected", "pass_rule", "fail_rule", "inconclusive_rule"):
            with self.subTest(field=field):
                manifest = deepcopy(original)
                manifest[field] = "Synthetic conflicting behavior"
                self.rewrite(path, manifest)
                with self.assertRaises(ContractError):
                    load_contract(directory)

    def test_unreachable_fault_configuration_rejected_before_output(self):
        fixture = self.fixture()
        fixture["faults"].update(interrupt_kind="timeout", interrupt_after=len(fixture["observations"]) + 1)
        output = self.output()
        with self.assertRaises(ContractError):
            run(fixture, output)
        self.assertFalse(output.exists())

    def test_final_marker_fsync_failure_never_publishes_completion(self):
        fixture = self.fixture()
        _, successful = self.execute(fixture)
        file_count = sum(p.is_file() for p in successful.rglob("*"))
        output = self.output()
        failures = [None] * (file_count - 1) + [OSError("synthetic final fsync failure")]
        with patch("os_tamper.engine.os.fsync", side_effect=failures) as sync:
            with self.assertRaises((OSError, ContractError)):
                run(fixture, output)
            self.assertEqual(sync.call_count, file_count)
        self.assertTrue((output / "result.json").exists())
        self.assertFalse((output / "finalized.json").exists())
        with self.assertRaises(ContractError):
            validate_bundle(output)

    def test_storage_failure_does_not_create_finalization_marker(self):
        output = self.output()
        with patch("os_tamper.engine.write_file", side_effect=OSError("synthetic disk full")):
            with self.assertRaises((OSError, ContractError)):
                run(self.fixture(), output)
        self.assertFalse((output / "finalized.json").exists())
        with self.assertRaises(ContractError):
            validate_bundle(output)

    def test_index_path_length_hash_membership_and_duplicates_rejected(self):
        cases = (("relative_blob_ref", "../synthetic-outside.json"),
                 ("relative_blob_ref", "https://example.invalid/synthetic.json"),
                 ("relative_blob_ref", "/tmp/synthetic-outside.json"),
                 ("byte_length", 0), ("content_hash", "0" * 64),
                 ("run_id", "synthetic-other-run"),
                 ("attempt_id", "synthetic-other-attempt"),
                 ("check_id", "CHK-08"))
        for field, value in cases:
            with self.subTest(field=field, value=value):
                _, output = self.execute()
                path = output / "evidence-index.json"
                index = json.loads(path.read_text())
                index["evidence"][0][field] = value
                self.rewrite(path, index)
                with self.assertRaises(ContractError):
                    validate_bundle(output)
        _, output = self.execute()
        path = output / "evidence-index.json"
        index = json.loads(path.read_text())
        index["evidence"].append(deepcopy(index["evidence"][0]))
        self.rewrite(path, index)
        with self.assertRaises(ContractError):
            validate_bundle(output)

    def test_deleted_or_changed_completion_marker_rejected(self):
        for mutation in ("delete", "change"):
            with self.subTest(mutation=mutation):
                _, output = self.execute()
                marker = output / "finalized.json"
                if mutation == "delete":
                    marker.unlink()
                else:
                    self.rewrite(marker, {"synthetic": True})
                with self.assertRaises(ContractError):
                    validate_bundle(output)

    def test_output_cannot_overwrite_existing_bundle(self):
        fixture = self.fixture()
        _, output = self.execute(fixture)
        before = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
        with self.assertRaises((ContractError, FileExistsError)):
            run(fixture, output)
        after = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_empty_existing_output_directory_is_not_reused(self):
        output = self.output()
        output.mkdir()
        with self.assertRaises((ContractError, FileExistsError)):
            run(self.fixture(), output)
        self.assertEqual(list(output.iterdir()), [])

    def test_changed_or_missing_blob_rejected(self):
        for mutation in ("change", "delete"):
            with self.subTest(mutation=mutation):
                _, output = self.execute()
                blob = next((output / "blobs").glob("*.json"))
                if mutation == "delete":
                    blob.unlink()
                else:
                    blob.write_bytes(blob.read_bytes() + b" ")
                with self.assertRaises(ContractError):
                    validate_bundle(output)

    def test_symlink_blob_escape_rejected(self):
        _, output = self.execute()
        blob = next((output / "blobs").glob("*.json"))
        target = self.base / "synthetic-outside.json"
        target.write_bytes(blob.read_bytes())
        blob.unlink()
        blob.symlink_to(target)
        with self.assertRaises(ContractError):
            validate_bundle(output)

    def test_missing_run_events_index_or_result_rejected(self):
        for name in ("run.json", "events.jsonl", "evidence-index.json", "result.json"):
            with self.subTest(name=name):
                _, output = self.execute()
                (output / name).unlink()
                with self.assertRaises(ContractError):
                    validate_bundle(output)

    def test_result_verdict_and_reason_tampering_rejected(self):
        for field, value in (("verdict", "pass"), ("reason", ""),
                             ("evidence_refs", []), ("observation_refs", []),
                             ("run_id", "synthetic-another-run"),
                             ("synthetic", False)):
            with self.subTest(field=field):
                _, output = self.execute(self.fixture("fail"))
                path = output / "result.json"
                result = json.loads(path.read_text())
                result[field] = value
                self.rewrite(path, result)
                with self.assertRaises(ContractError):
                    validate_bundle(output)

    def test_result_unknown_evidence_reference_rejected(self):
        _, output = self.execute()
        path = output / "result.json"
        result = json.loads(path.read_text())
        result["evidence_refs"].append("synthetic-no-such-evidence")
        self.rewrite(path, result)
        with self.assertRaises(ContractError):
            validate_bundle(output)

    def test_event_duplicate_reordered_or_foreign_run_rejected(self):
        for mutation in ("duplicate", "reverse", "foreign_run"):
            with self.subTest(mutation=mutation):
                _, output = self.execute()
                path = output / "events.jsonl"
                events = [json.loads(line) for line in path.read_text().splitlines()]
                if mutation == "duplicate":
                    events.append(deepcopy(events[0]))
                elif mutation == "reverse":
                    events.reverse()
                else:
                    events[0]["run_id"] = "synthetic-another-run"
                path.write_text("".join(json.dumps(event) + "\n" for event in events))
                with self.assertRaises(ContractError):
                    validate_bundle(output)

    def test_core_has_no_network_or_subprocess_side_effects(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network is forbidden")), \
             patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess is forbidden")):
            self.execute()

    def test_cli_completed_verdicts_and_validate_exit_zero(self):
        for verdict in ("pass", "fail", "inconclusive"):
            with self.subTest(verdict=verdict):
                output = self.output()
                completed = subprocess.run(
                    [sys.executable, "-m", "os_tamper", "run", "--input", str(ROOT / "fixtures" / f"{verdict}.json"),
                     "--output", str(output)], cwd=ROOT, text=True, capture_output=True, timeout=15)
                self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
                self.assertEqual(validate_bundle(output)["verdict"], verdict)
                validated = subprocess.run(
                    [sys.executable, "-m", "os_tamper", "validate", "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True, timeout=15)
                self.assertEqual(validated.returncode, 0, validated.stderr + validated.stdout)

    def test_cli_faults_cancel_and_prerequisite_exit_codes(self):
        cases = [("timeout", 3), ("cancel", 4), ("tool_error", 2), ("cleanup", 2), ("not_run", 5)]
        for fault, code in cases:
            with self.subTest(fault=fault):
                fixture = self.fixture()
                if fault == "cleanup":
                    fixture["faults"]["cleanup"] = "failed"
                elif fault == "not_run":
                    fixture["profile"]["scopes"] = []
                    fixture["observations"] = []
                else:
                    fixture["faults"].update(interrupt_kind=fault, interrupt_after=0)
                path = self.base / f"synthetic-{fault}.json"
                self.rewrite(path, fixture)
                output = self.output()
                completed = subprocess.run(
                    [sys.executable, "-m", "os_tamper", "run", "--input", str(path), "--output", str(output)],
                    cwd=ROOT, text=True, capture_output=True, timeout=15)
                self.assertEqual(completed.returncode, code, completed.stderr + completed.stdout)
                validate_bundle(output)
        output = self.output()
        completed = subprocess.run(
            [sys.executable, "-m", "os_tamper", "run", "--input", str(ROOT / "fixtures" / "pass.json"),
             "--output", str(output), "--cancel"], cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 4, completed.stderr + completed.stdout)
        self.assertEqual(validate_bundle(output)["execution_status"], "cancelled")

    def test_cli_malformed_input_exit_two_without_output(self):
        path = self.base / "synthetic-malformed.json"
        path.write_text("{", encoding="utf-8")
        output = self.output()
        completed = subprocess.run(
            [sys.executable, "-m", "os_tamper", "run", "--input", str(path), "--output", str(output)],
            cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 2, completed.stderr + completed.stdout)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
