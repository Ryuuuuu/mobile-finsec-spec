# P4 structure-only POC — active scope

Current work tests orchestration and data/UI contracts using opaque mock skills, synthetic recordings and mock executors/providers. **Do not implement or test inspection-skill contents, tool choices or vulnerability judgement logic.** The user authors those skills separately.

## Current acceptance command

From `pocs/p4-integration`, using the prepared Python environment with dependencies from `requirements.txt`:

```text
python scripts/run_structure_tests.py
```

This explicit suite list excludes historical P3-backed tests and the legacy demo CLI. It uses local mock servers/processes where required, with no actual device, actual model service or credentials. Do not replace it with unrestricted `unittest discover`. Rust metadata compilation and eventual native GPUI tests are separate gates, not part of this Python command.

The active APIs are `StructureSupervisor`, `StartAPI`, `UIBridge` and `UIWire`. `Supervisor` and `python -m integration demo` are historical P3-backed paths, not the current entry points. No production GPUI screen, authenticated IPC or real model/device integration is established by these tests.

Validation on Windows/Python 3.12.10: the explicit runner executed 92 structural tests, all passed, zero skips. This does not execute Rust tests or a GPUI window.

## Current design and validation links


[Structure-only scope](docs/STRUCTURE-ONLY-SCOPE.md) supersedes further check-content/verdict testing. User-authored skills and tools are outside current implementation scope. Use opaque mock skills and the selected structural tests; do not use the historical full suite as current acceptance.

Use [StructureSupervisor](docs/STRUCTURAL-SUPERVISOR.md) for the active mock-only orchestration path. The historical Supervisor alias and demo CLI remain legacy P3-backed compatibility paths, outside current acceptance.

[Recording context handoff](docs/RECORDING-CONTEXT.md) covers synthetic P1/P2 references, unselected-recording app-launch intent, explicit missing/partial states and sequential mock-agent delivery.

[Offline P1/P2 file handoff](docs/ARTIFACT-HANDOFF.md) tests current route JSON/link and SQLite formats with synthetic files; it is not real-device or model validation.

[On-demand packet bytes](docs/PACKET-ACCESS.md) adds scoped, revocable mock-agent access to synthetic P2 request/response BLOBs with independent completeness and truncation states.

[Live logs and final history](docs/RUN-HISTORY.md) separate execution lifecycle from sealed result storage and list multiple UTC-dated runs. Assessment labels are fixed test values only.

[Start/preflight API](docs/START-PREFLIGHT.md) validates mock device/item selection and prerequisites independently of models, with disabled reasons, command deduplication and disconnect checks.

[Integrated structural acceptance](docs/INTEGRATED-STRUCTURE.md) connects start selection through source-format synthetic recording, live logs, scoped packet bytes, sealed results and multi-run history; includes failure/restart boundaries.

[GPUI contract alignment via mock UI](docs/UI-CONTRACT-BRIDGE.md) tests record/check/result projections, live cursor behavior, finalized history, disconnected/partial/cancel states. No GPUI implementation is claimed.

[Native GPUI preparation](docs/GPUI-NATIVE-PREPARATION.md) records missing build prerequisites, a read-only probe and a reproducible mock screen/API integration plan. Native compilation and rendering remain not run.

[Serialized UI boundary and Rust preparation](docs/UI-WIRE-PREPARATION.md): actual Python JSON round-trip tests pass; independent Rust state/test metadata compiles. No GPUI window or cross-process transport is claimed.

## Historical demos (not current instructions)

The previous P2/P3-coupled architecture, full-suite command and CLI examples are retained only in [the archived README](docs/LEGACY-P4-README.md). They predate the structure-only user instruction and must not be used as current acceptance.
