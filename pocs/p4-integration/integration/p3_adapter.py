"""Thin adapter to the unchanged P3 evaluator; all observations remain synthetic.

This synchronous call does not provide live cancellation or a device adapter.
The supervisor must track actual completion, including when its caller cancels.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

P3_ROOT = Path(__file__).resolve().parents[2] / "p3-android-os-tamper"
if str(P3_ROOT) not in sys.path:
    sys.path.insert(0, str(P3_ROOT))

from os_tamper import engine as p3_engine  # noqa: E402
from os_tamper import protocol as p3_protocol  # noqa: E402


class P3AdapterError(ValueError):
    """The P4 reference does not match a verified P3 synthetic bundle."""


def snapshot() -> dict:
    """Read and validate the real P3 common+AOS Skill/manifest contract."""
    return deepcopy(p3_protocol.contract_snapshot())


def _evidence_refs(bundle: str, attempt_id: str, result: dict) -> list[str]:
    # P3 evidence IDs are bundle-local. Never merge bare IDs across attempts.
    return [f"{attempt_id}:{bundle}#{ref}" for ref in result["evidence_refs"]]


def _validate_snapshot(value: dict) -> None:
    if not isinstance(value, dict) or set(value) != {"manifest", "skills"}:
        raise P3AdapterError("P3_SNAPSHOT_INVALID")
    p3_protocol.validate_contract(value["manifest"], value["skills"])


def run_check(variant: str, output: Path, *, run_id: str, session_id: str,
              attempt_id: str, expected_snapshot: dict,
              device_id: str = "synthetic-device-p4",
              cleanup_fault: str = "completed") -> dict:
    """Run one checked-in fixture using real P3 code and verify persisted output.

    P2 packets are deliberately absent: they cannot establish CHK-07 causality.
    P3 timestamps remain synthetic logical fixture time, not P4 wall-clock time.
    """
    if variant not in ("pass", "fail", "inconclusive"):
        raise P3AdapterError("P3_VARIANT_UNSUPPORTED")
    if device_id != "synthetic-device-p4":
        raise P3AdapterError("P3_DEVICE_UNSUPPORTED")
    if cleanup_fault not in ("completed", "failed", "unknown"):
        raise P3AdapterError("P3_CLEANUP_FAULT_INVALID")
    expected_snapshot = deepcopy(expected_snapshot)
    _validate_snapshot(expected_snapshot)
    if snapshot() != expected_snapshot:
        raise P3AdapterError("P3_SNAPSHOT_CHANGED")
    fixture = p3_protocol.load_json(P3_ROOT / "fixtures" / f"{variant}.json")
    fixture.update(project_id="synthetic-project-p4", run_id=run_id,
                   session_id=session_id, attempt_id=attempt_id)
    fixture["device"] = {"baseline_id": device_id, "test_id": device_id}
    for observation in fixture["observations"]:
        observation["device_id"] = device_id
    fixture["faults"]["cleanup"] = cleanup_fault
    # Keep route_refs/packet_refs empty exactly as required by the P3 schema.
    p3_protocol.validate_input(fixture)
    output = Path(output)
    result = p3_engine.run(fixture, output)
    report = {
        "result": result, "bundle": str(output), "attempt_id": attempt_id,
        "run_id": run_id, "session_id": session_id,
        "source": "real_p3_synthetic", "synthetic": True,
        "evidence_refs": _evidence_refs(str(output), attempt_id, result),
    }
    validate_reference(report, expected_snapshot=expected_snapshot)
    return report


def validate_reference(report: dict, expected_snapshot: dict | None = None) -> dict:
    """Validate bundle, identity, copied result and namespaced evidence references.

    The enclosing run validator must additionally require ``bundle`` to reside
    in its own output directory. P3 validates its own exact files and symlinks.
    """
    keys = {"result", "bundle", "attempt_id", "run_id", "session_id",
            "source", "synthetic", "evidence_refs"}
    if (not isinstance(report, dict) or set(report) != keys
            or report["source"] != "real_p3_synthetic"
            or report["synthetic"] is not True
            or not isinstance(report["bundle"], str) or not report["bundle"]):
        raise P3AdapterError("P3_REFERENCE_INVALID")
    if expected_snapshot is not None:
        _validate_snapshot(expected_snapshot)
    result = p3_engine.validate_bundle(Path(report["bundle"]))
    record = p3_protocol.load_json(Path(report["bundle"]) / "run.json")
    if expected_snapshot is not None and record["contract_snapshot"] != expected_snapshot:
        raise P3AdapterError("P3_SNAPSHOT_CHANGED")
    if any(report[key] != result[key] for key in ("run_id", "session_id", "attempt_id")):
        raise P3AdapterError("P3_REFERENCE_ID_MISMATCH")
    if report["result"] != result:
        raise P3AdapterError("P3_REFERENCE_RESULT_MISMATCH")
    if report["evidence_refs"] != _evidence_refs(report["bundle"], report["attempt_id"], result):
        raise P3AdapterError("P3_REFERENCE_EVIDENCE_MISMATCH")
    fixture = record["input"]
    if (fixture["device"] != {"baseline_id": "synthetic-device-p4", "test_id": "synthetic-device-p4"}
            or fixture["route_refs"] or fixture["packet_refs"]):
        raise P3AdapterError("P3_REFERENCE_SCOPE_MISMATCH")
    return result
