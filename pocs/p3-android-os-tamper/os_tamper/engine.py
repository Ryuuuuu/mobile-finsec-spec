"""Deterministic synthetic observation adapter, evaluator and bundle validator.

This module has no device, network, subprocess or real evidence adapter.
"""

import copy
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .protocol import (ContractError, contract_snapshot, decode, digest, encoded,
                       load_json, validate_contract, validate_input, validate_schema)

LIMITATIONS = [
    "SYNTHETIC ONLY: fixture declarations are not device observations.",
    "No Android/ADB/Appium adapter, financial app assessment or official certification.",
    "Only declared build, service and checkpoints are in scope; no whole-app assurance.",
    "Timestamps and durations are synthetic logical time, not measured tool latency.",
    "Hashes detect corruption; they do not authenticate observation truth or authorship.",
    "Recovery flags do not acquire a device lease or block an external scheduler.",
]


def _scope_result(scope, observations, evidence_map):
    relevant = [o for o in observations if o["scope_id"] == scope["scope_id"]]
    result = {"synthetic": True, "scope_id": scope["scope_id"],
              "service_id": scope["service_id"], "checkpoint_id": scope["checkpoint_id"],
              "verdict": "inconclusive", "reason_code": "OBSERVATION_MISSING",
              "reason": "정상 baseline 또는 변조 시험의 서비스 관측이 부족합니다.",
              "observation_refs": [o["observation_id"] for o in relevant],
              "evidence_refs": [evidence_map[o["observation_id"]] for o in relevant]}
    return result, relevant


def assess(fixture, observations, evidence_map):
    """Interpret independent state/service observations, never an input verdict."""
    results = []
    for scope in fixture["profile"]["scopes"]:
        result, relevant = _scope_result(scope, observations, evidence_map)
        results.append(result)
        def incomplete(code, reason):
            result.update(reason_code=code, reason=reason)
        if not scope["checkpoint_id"]:
            incomplete("ORACLE_UNDEFINED", "보호 서비스 완료/차단 checkpoint 정의가 없습니다.")
            continue
        bad_target = any(
            o["device_id"] != fixture["device"][o["phase"] + "_id"]
            or o["package_id"] != fixture["app"]["package_id"]
            or o["build_sha256"] != fixture["app"]["build_sha256"]
            or o["service_id"] != scope["service_id"]
            or o["checkpoint_id"] != scope["checkpoint_id"] for o in relevant)
        if bad_target:
            incomplete("TARGET_MISMATCH", "관측의 기기·빌드·서비스·checkpoint가 선언 범위와 다릅니다.")
            continue
        phases = {p: [o for o in relevant if o["phase"] == p] for p in ("baseline", "test")}
        semantic_keys = ("state", "state_proof", "outcome", "oracle", "block_reason")
        if any(len({tuple(o[k] for k in semantic_keys) for o in rows}) > 1 for rows in phases.values()):
            incomplete("CONFLICTING_OBSERVATIONS", "동일 phase/scope의 상태 또는 서비스 근거가 상충합니다.")
            continue
        # An allowed service accompanied by a claimed tamper block is internally contradictory.
        if any(o["outcome"] == "allowed" and o["block_reason"] != "none" for o in relevant):
            incomplete("CONFLICTING_OBSERVATIONS", "서비스 허용과 차단 원인이 동시에 선언되었습니다.")
            continue
        if not phases["baseline"] or not phases["test"]:
            continue
        baseline, test = phases["baseline"][0], phases["test"][0]
        if not (baseline["state"] == "stock" and baseline["state_proof"] == "fixture_attestation"
                and baseline["outcome"] == "allowed" and baseline["oracle"] == "service_checkpoint"):
            incomplete("BASELINE_UNPROVEN", "동일 보호 서비스의 순정 정상 이용 baseline이 입증되지 않았습니다.")
        elif test["state"] != "tampered" or test["state_proof"] != "fixture_attestation":
            incomplete("TAMPER_UNPROVEN", "시험 단말의 변조 상태가 입증되지 않았습니다.")
        elif test["oracle"] != "service_checkpoint" or test["outcome"] in ("launch_only", "crash", "unknown"):
            incomplete("SERVICE_UNPROVEN", "보호 서비스 이용/차단 oracle이 없습니다. 실행·crash만으로 판정하지 않습니다.")
        elif test["outcome"] == "allowed":
            result.update(verdict="fail", reason_code="TAMPERED_SERVICE_ALLOWED",
                          reason="합성 변조 상태에서 선언한 보호 서비스 이용 checkpoint가 확인되었습니다.")
        elif test["outcome"] == "blocked" and test["block_reason"] == "os_tamper":
            result.update(verdict="pass", reason_code="TAMPERED_SERVICE_BLOCKED",
                          reason="합성 변조 상태에서 OS 변조에 따른 보호 서비스 차단이 확인되었습니다.")
        else:
            incomplete("BLOCK_CAUSE_UNPROVEN", "차단이 OS 변조 방어 때문인지 입증되지 않았습니다.")
    return results


def build_bundle(fixture, snapshot, cancel=False):
    """Pure execution model; fault budgets are synthetic logical milliseconds."""
    fixture = copy.deepcopy(validate_input(fixture))
    validate_contract(snapshot["manifest"], snapshot["skills"])
    base = {"schema_version": "1.0", "synthetic": True, "source": "synthetic_fixture"}
    base.update({key: fixture[key] for key in ("project_id", "session_id", "run_id", "check_id", "attempt_id")})
    elapsed = 0
    start = datetime.fromisoformat(fixture["timestamp"].replace("Z", "+00:00"))
    def timestamp():
        return (start + timedelta(milliseconds=elapsed)).astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    events, entries, blobs, collected = [], [], {}, []
    def emit(kind, payload, refs=None, tool=None):
        seq = len(events) + 1
        event = dict(base, event_id=f"synthetic-event-{seq:04d}", sequence=seq,
                     timestamp=timestamp(), clock="synthetic_logical", elapsed_ms=elapsed,
                     type=kind, payload=payload, evidence_refs=refs or [], tool_call_id=tool)
        events.append(event)
        return event["event_id"]
    emit("run_created", {"synthetic": True})
    status, error_code = "completed", None
    scopes = fixture["profile"]["scopes"]
    if not scopes or any(s["checkpoint_id"] is None for s in scopes):
        status, error_code = "not_run", "PRECONDITION_MISSING"
    elif cancel:
        status, error_code = "cancelled", "RUN_CANCELLED_BEFORE_START"
    emit("preflight", {"synthetic": True, "eligible": status == "completed", "reason_code": error_code})
    faults = fixture["faults"]
    def interrupt():
        kind = faults["interrupt_kind"]
        if kind != "none" and len(collected) == faults["interrupt_after"]:
            return {"timeout": ("timed_out", "TOOL_TIMEOUT"), "cancel": ("cancelled", "RUN_CANCELLED"),
                    "tool_error": ("failed", "TOOL_ERROR")}[kind]
        return None
    if status == "completed":
        for index, observation in enumerate(fixture["observations"]):
            interruption = interrupt()
            if interruption:
                status, error_code = interruption
                break
            tool = f"synthetic-tool-{index+1:04d}"
            emit("observation_attempt", {"synthetic": True, "observation_id": observation["observation_id"]}, tool=tool)
            timeouts = snapshot["manifest"]["timeouts"]
            remaining = timeouts["total_timeout_ms"] - elapsed
            cost = observation["cost_ms"]
            if cost > timeouts["step_timeout_ms"] or cost > remaining:
                elapsed += max(0, min(cost, timeouts["step_timeout_ms"], remaining))
                status, error_code = "timed_out", "TOOL_TIMEOUT"
                break
            elapsed += cost
            evidence_id = f"synthetic-evidence-{index+1:04d}"
            relative = f"blobs/{evidence_id}.json"
            event_id = emit("observation_collected", {"synthetic": True, "observation_id": observation["observation_id"]}, [evidence_id], tool)
            envelope = dict(base, evidence_id=evidence_id, event_id=event_id, tool_call_id=tool,
                            captured_at_utc=timestamp(), clock="synthetic_logical", observation=observation)
            data = encoded(envelope)
            blobs[relative] = data
            entries.append(dict(base, evidence_id=evidence_id, observation_id=observation["observation_id"],
                                event_id=event_id, tool_call_id=tool, scope_id=observation["scope_id"],
                                captured_at_utc=timestamp(), clock="synthetic_logical", media_type="application/json",
                                collection_method="synthetic_fixture", original_or_derived="original_fixture_copy",
                                derived_from=[], byte_length=len(data), content_hash=digest(data), relative_blob_ref=relative))
            collected.append(observation)
        if status == "completed" and interrupt():
            status, error_code = interrupt()
    if error_code:
        emit("execution_interrupted", {"synthetic": True, "execution_status": status, "reason_code": error_code})
    evidence_map = {e["observation_id"]: e["evidence_id"] for e in entries}
    scope_results = assess(fixture, collected, evidence_map)
    collected_ids = set(evidence_map)
    for scope in scope_results:
        if scope["verdict"] == "pass" and any(
            o["scope_id"] == scope["scope_id"] and o["observation_id"] not in collected_ids
            for o in fixture["observations"]
        ):
            scope.update(verdict="inconclusive", reason_code="INCOMPLETE_OBSERVATION_SET",
                         reason="차단 근거는 있으나 해당 scope의 예정 관측이 완료되지 않았습니다.")
    verdict = "inconclusive"
    reason_code, reason = "INCOMPLETE_SCOPE", "선언 범위의 필수 관측 또는 선행조건이 부족합니다."
    if any(s["verdict"] == "fail" for s in scope_results):
        verdict, reason_code, reason = "fail", "TAMPERED_SERVICE_ALLOWED", "한 개 이상 합성 scope에서 변조 상태의 보호 서비스 이용이 입증되었습니다."
    elif scope_results and all(s["verdict"] == "pass" for s in scope_results):
        verdict, reason_code, reason = "pass", "ALL_SCOPES_BLOCKED", "모든 선언 합성 scope에서 OS 변조에 따른 보호 서비스 차단이 확인되었습니다."
    elif error_code:
        reason_code, reason = error_code, "실행 중단 또는 선행조건 부족으로 필수 증거가 완결되지 않았습니다."
    elif len(scope_results) == 1:
        reason_code, reason = scope_results[0]["reason_code"], scope_results[0]["reason"]
    emit("verification", {"synthetic": True, "verdict": verdict, "reason_code": reason_code})
    cleanup = faults["cleanup"]
    errors = [{"synthetic": True, "code": error_code, "phase": "execution"}] if error_code else []
    if cleanup != "completed":
        errors.append({"synthetic": True, "code": "CLEANUP_" + cleanup.upper(), "phase": "cleanup"})
        if status == "completed":
            status = "failed"
    emit("cleanup", {"synthetic": True, "cleanup_status": cleanup})
    blocked = cleanup != "completed"
    limitations = LIMITATIONS + ["미완료 scope: " + s["scope_id"] for s in scope_results if s["verdict"] == "inconclusive"]
    result = dict(base, execution_status=status, verdict=verdict, reason_code=reason_code, reason=reason,
                  cleanup_status=cleanup, follow_up_blocked=blocked, recovery_required=blocked,
                  errors=errors, tested_scope={"synthetic": True, "platform": "aos", "app": fixture["app"],
                    "device": fixture["device"], "profile_id": fixture["profile"]["profile_id"], "scopes": scopes},
                  scope_results=scope_results, limitations=limitations,
                  evidence_refs=[e["evidence_id"] for e in entries],
                  observation_refs=[o["observation_id"] for o in collected],
                  started_at=fixture["timestamp"], ended_at=timestamp(),
                  duration_monotonic_ms=elapsed, clock="synthetic_logical",
                  config_hash=digest(encoded(fixture)), skill_version=snapshot["manifest"]["skill_version"],
                  skill_hashes={k: v["sha256"] for k, v in snapshot["manifest"]["skills"].items()},
                  backend_snapshot={"synthetic": True, "adapter": "synthetic_fixture", "version": "1.0.0", "ai": False})
    emit("run_finalized", {"synthetic": True, "execution_status": status, "verdict": verdict})
    run_record = dict(base, input=fixture, contract_snapshot=snapshot, cancel_requested=cancel,
                      selected_check_ids=["CHK-07"], clock="synthetic_logical", tool_version="1.0.0")
    index_record = dict(base, evidence=entries)
    files = {"run.json": encoded(run_record), "result.json": encoded(result),
             "evidence-index.json": encoded(index_record),
             "events.jsonl": b"".join(encoded(e).replace(b"\n", b"") + b"\n" for e in events), **blobs}
    marker = dict(base, finalized=True, finalization_version="1.0", result_hash=digest(files["result.json"]))
    files["finalized.json"] = encoded(marker)
    return result, files


def write_file(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def run(fixture, output, cancel=False):
    if type(cancel) is not bool:
        raise ContractError("INVALID_CANCEL_FLAG")
    result, files = build_bundle(fixture, contract_snapshot(), cancel)
    output = Path(output)
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ContractError("OUTPUT_ALREADY_EXISTS") from exc
    (output / "blobs").mkdir()
    for relative, data in files.items():
        if relative != "finalized.json":
            write_file(output / relative, data)
    # Validate persisted evidence before claiming successful finalization.
    _validate_bundle(output, require_marker=False)
    marker_temp = output / ".finalized.tmp"
    write_file(marker_temp, files["finalized.json"])
    os.replace(marker_temp, output / "finalized.json")
    return result


def _validate_bundle(output, require_marker=True):
    output = Path(output)
    if output.is_symlink() or not output.is_dir():
        raise ContractError("BUNDLE_PATH_INVALID")
    actual = set()
    for path in output.rglob("*"):
        if path.is_symlink():
            raise ContractError("SYMLINK_FORBIDDEN")
        if path.is_file():
            actual.add(path.relative_to(output).as_posix())
        elif path.relative_to(output).as_posix() != "blobs":
            raise ContractError("UNEXPECTED_DIRECTORY")
    try:
        record = load_json(output / "run.json")
        if type(record.get("cancel_requested")) is not bool:
            raise ContractError("INVALID_CANCEL_FLAG")
        result, expected = build_bundle(record["input"], record["contract_snapshot"], record["cancel_requested"])
        if not require_marker:
            expected.pop("finalized.json")
        if actual != set(expected):
            raise ContractError("BUNDLE_FILES_MISSING_OR_UNEXPECTED")
        for relative, data in expected.items():
            path = output / relative  # Paths generated by code, never taken from untrusted refs.
            with path.open("rb") as stream:
                found = stream.read(len(data) + 1)
            if found != data:
                raise ContractError("BUNDLE_CONTENT_OR_REFERENCE_MISMATCH:" + relative)
        # Structural schema checks supplement exact semantic replay and integrity checks.
        for name, filename in (("result", "result.json"), ("run", "run.json"),
                               ("evidence-index", "evidence-index.json")):
            validate_schema(load_json(output / filename), name)
        for line in expected["events.jsonl"].splitlines():
            validate_schema(decode(line), "event")
        for relative in expected:
            if relative.startswith("blobs/"):
                validate_schema(load_json(output / relative), "evidence")
        if require_marker:
            validate_schema(load_json(output / "finalized.json"), "finalized")
    except (OSError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ContractError("BUNDLE_INVALID_OR_UNREADABLE") from exc
    return result


def validate_bundle(output):
    """Validate finalized output without rewriting or changing its original verdict."""
    return _validate_bundle(output)
