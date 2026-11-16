"""Strict local contracts. No external schema resolution or device access."""

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CHECK_DIR = ROOT / "checks" / "CHK-07"
MAX_BYTES = 1024 * 1024
RULE = {"rule_contract": "CHK-07.synthetic.v1", "synthetic": True, "schema_version": "1.0"}


class ContractError(ValueError):
    """Invalid contract or incomplete/corrupted synthetic output."""


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ContractError("DUPLICATE_JSON_KEY")
        obj[key] = value
    return obj


def decode(data):
    if len(data) > MAX_BYTES:
        raise ContractError("JSON_SIZE_LIMIT")
    def invalid_constant(_):
        raise ContractError("NON_FINITE_JSON_NUMBER")
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ContractError("NON_FINITE_JSON_NUMBER")
        return number
    try:
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=invalid_constant,
                          parse_float=finite_float)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("MALFORMED_JSON") from exc


def load_json(path):
    with Path(path).open("rb") as stream:
        return decode(stream.read(MAX_BYTES + 1))


def validate_schema(value, name):
    schema = load_json(ROOT / "schemas" / (name + ".schema.json"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    error = next(validator.iter_errors(value), None)
    if error:
        # Do not echo arbitrary user-supplied content or credentials in diagnostics.
        location = "/".join(str(part) for part in error.absolute_path)
        raise ContractError(f"SCHEMA_INVALID:{name}:{location}:{error.validator}")


def validate_input(value):
    validate_schema(value, "input")
    try:
        parsed = datetime.fromisoformat(value["timestamp"].replace("Z", "+00:00"))
        if parsed.year >= 9999:
            raise ValueError("timestamp leaves no room for logical duration")
    except ValueError as exc:
        raise ContractError("INVALID_TIMESTAMP") from exc
    for array, key in ((value["observations"], "observation_id"),
                       (value["profile"]["scopes"], "scope_id")):
        ids = [item[key] for item in array]
        if len(ids) != len(set(ids)):
            raise ContractError("DUPLICATE_ID:" + key)
    scopes = {s["scope_id"] for s in value["profile"]["scopes"]}
    if any(o["scope_id"] not in scopes for o in value["observations"]):
        raise ContractError("UNKNOWN_SCOPE_REFERENCE")
    faults = value["faults"]
    if (faults["interrupt_kind"] == "none") != (faults["interrupt_after"] is None):
        raise ContractError("CONFLICTING_FAULT_CONFIGURATION")
    if faults["interrupt_after"] is not None and faults["interrupt_after"] > len(value["observations"]):
        raise ContractError("UNREACHABLE_FAULT_CONFIGURATION")
    return value


def validate_contract(manifest, skills):
    validate_schema(manifest, "manifest")
    if manifest.get("schema_version") != "1.0" or manifest.get("check_id") != "CHK-07":
        raise ContractError("MANIFEST_VERSION_OR_CHECK")
    if manifest.get("rule_contract") != RULE["rule_contract"] or manifest.get("synthetic") is not True:
        raise ContractError("MANIFEST_RULE_CONFLICT")
    if manifest.get("supported_platforms") != ["aos"] or manifest.get("adapter") != "synthetic_fixture":
        raise ContractError("UNSUPPORTED_ADAPTER_OR_PLATFORM")
    if manifest.get("timeouts") != {"step_timeout_ms": 1000, "total_timeout_ms": 10000}:
        raise ContractError("MANIFEST_TIMEOUT_CONFLICT")
    if manifest.get("skill_version") != "1.0.0":
        raise ContractError("SKILL_VERSION_UNSUPPORTED")
    if set(manifest.get("skills", {})) != {"common", "aos"} or set(skills) != {"common", "aos"}:
        raise ContractError("REQUIRED_SKILL_MISSING")
    for platform, content in skills.items():
        entry = manifest["skills"][platform]
        if entry.get("path") != platform + "/SKILL.md":
            raise ContractError("SKILL_PATH_INVALID")
        if entry.get("sha256") != digest(content.encode("utf-8")):
            raise ContractError("SKILL_HASH_MISMATCH")
        blocks = re.findall(r"```json\s*\n(.*?)\n```", content, re.DOTALL)
        if len(blocks) != 1 or encoded(decode(blocks[0].encode())) != encoded(RULE):
            raise ContractError("SKILL_RULE_CONFLICT")
    for key in ("title", "source_reference", "source_scope_status", "implementation_group",
                "implementation_status", "requirements", "expected_evidence", "pass_rule",
                "fail_rule", "inconclusive_rule", "cleanup", "cancel"):
        if not manifest.get(key):
            raise ContractError("MANIFEST_REQUIRED_FIELD:" + key)
    if manifest["source_scope_status"] != "provisional" or manifest["implementation_group"] != "E":
        raise ContractError("MANIFEST_SCOPE_CONFLICT")
    return manifest


def contract_snapshot(check_dir=None):
    check_dir = Path(check_dir) if check_dir is not None else CHECK_DIR
    try:
        manifest = load_json(check_dir / "manifest.yaml")
        skills = {p: (check_dir / p / "SKILL.md").read_text(encoding="utf-8") for p in ("common", "aos")}
    except (OSError, UnicodeError) as exc:
        raise ContractError("MANIFEST_OR_SKILL_UNREADABLE") from exc
    validate_contract(manifest, skills)
    return {"manifest": manifest, "skills": skills}


def load_contract(check_dir=None):
    return contract_snapshot(check_dir)["manifest"]
