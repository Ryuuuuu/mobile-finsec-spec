# P4 structure-only POC — active scope

Current work tests orchestration and data/UI contracts using opaque mock skills, synthetic recordings and mock executors/providers. **Do not implement or test inspection-skill contents, tool choices or vulnerability judgement logic.** The user authors those skills separately.

## Current acceptance command

From `pocs/p4-integration`, using the prepared Python environment with dependencies from `requirements.txt`:

```text
python scripts/run_structure_tests.py
```

This explicit suite list excludes historical P3-backed tests and the legacy demo CLI. It uses local mock servers/processes where required, with no actual device, actual model service or credentials. Do not replace it with unrestricted `unittest discover`. Rust metadata compilation and eventual native GPUI tests are separate gates, not part of this Python command.

The active APIs are `StructureSupervisor`, `StartAPI`, `UIBridge` and `UIWire`. `Supervisor` and `python -m integration demo` are historical P3-backed paths, not the current entry points. No production GPUI screen or real model/device integration is established by these tests. The minimal authenticated mock loopback adapter is validated separately below; it is not production IPC.

Validation on Windows/Python 3.12.10: the explicit runner executed 155 structural tests, all passed, zero skips. TLS/WSS handoff tests used the existing P2 venv with cryptography; without OpenSSL/cryptography those cases explicitly skip and do not count as protocol validation. This does not execute Rust tests or a GPUI window.

## Current design and validation links

[State-only QA instrumentation](docs/QA-STATE-ONLY.md) provides a separate fixed own-app test contract without Appium/P2. Contract tests, local signed APK verification and one authorized A34 button/state probe passed. GPUI connection and saved-route replay remain unverified; this is an own-process fixture callback test.

[GPUI fixed observation preview](docs/GPUI-OBSERVATION-PREVIEW.md) verifies a dedicated synthetic 3-tab GPUI-kit window, plan approval/version rejection and A/B coverage/review result display through an actual Python child. It is separate from the real-device workspace and has no real model or device connection.

[A34 fixed QA state observation](docs/QA-STATE-DEVICE-VALIDATION.md) verifies two existing GUI-recorded QA routes through the actual replay bridge and allowlisted state-only acquisition. CLI harness, delayed fake reviewer only; no GPUI observation-plan UI, real AI or arbitrary-app claim.

[P1 observation bridge](docs/P1-OBSERVATION-BRIDGE.md) connects actual P1 replay boundaries to fixed synthetic-state review, testing route order, snapshot timing, delayed review and cancellation. Device/network peers are mock; GPUI observation-plan UI and real reviewer isolation are not implemented.

[Observation checkpoint POC](docs/OBSERVATION-CHECKPOINT-POC.md) tests approved immutable plans, separate synthetic-route evidence, coverage gaps, deduplication, cancellation and a delayed fixed fake reviewer without blocking synthetic replay. Real child isolation, model/inspection execution and device/GPUI wiring are not claimed.


[Structure-only scope](docs/STRUCTURE-ONLY-SCOPE.md) supersedes further check-content/verdict testing. User-authored skills and tools are outside current implementation scope. Use opaque mock skills and the selected structural tests; do not use the historical full suite as current acceptance.

Use [StructureSupervisor](docs/STRUCTURAL-SUPERVISOR.md) for the active mock-only orchestration path. The historical Supervisor alias and demo CLI remain legacy P3-backed compatibility paths, outside current acceptance.

[Recording context handoff](docs/RECORDING-CONTEXT.md) covers synthetic P1/P2 references, unselected-recording app-launch intent, explicit missing/partial states and sequential mock-agent delivery.

[Offline P1/P2 file handoff](docs/ARTIFACT-HANDOFF.md) tests current route JSON/link and SQLite formats with synthetic files; it is not real-device or model validation.

[On-demand packet bytes](docs/PACKET-ACCESS.md) adds scoped, revocable mock-agent access to synthetic P2 request/response BLOBs with independent completeness and truncation states.

[Live logs and final history](docs/RUN-HISTORY.md) separate execution lifecycle from sealed result storage and list multiple UTC-dated runs. Assessment labels are fixed test values only.

[Start/preflight API](docs/START-PREFLIGHT.md) validates mock device/item selection and prerequisites independently of models, with disabled reasons, command deduplication and disconnect checks.

[Integrated structural acceptance](docs/INTEGRATED-STRUCTURE.md) connects start selection through source-format synthetic recording, live logs, scoped packet bytes, sealed results and multi-run history; includes failure/restart boundaries.

[GPUI contract alignment via mock UI](docs/UI-CONTRACT-BRIDGE.md) tests record/check/result projections, live cursor behavior, finalized history, disconnected/partial/cancel states. No GPUI implementation is claimed.

[Native GPUI preparation](docs/GPUI-NATIVE-PREPARATION.md) records the now-verified Windows toolchain and initial native build/input/pipe probes. [Three-tab native workspace](docs/NATIVE-WORKSPACE.md) adds ordered multiple-record selection and mock execution through a real Python child; real multi-route device replay remains unimplemented.

[Serialized UI boundary and Rust preparation](docs/UI-WIRE-PREPARATION.md) covers in-process Python JSON tests and Rust metadata-only compilation. Subsequent [Python-to-Python pipe tests](docs/MOCK-STDIO.md) verify actual child-process communication and cleanup; Rust HTTP/native GPUI remain unverified; the later limited native pipe gate is linked below.

## Historical demos (not current instructions)

The previous P2/P3-coupled architecture, full-suite command and CLI examples are retained only in [the archived README](docs/LEGACY-P4-README.md). They predate the structure-only user instruction and must not be used as current acceptance.

[Actual mock child-process IPC](docs/MOCK-STDIO.md) tests Python-to-Python private pipes, EOF, forced termination, restart admission persistence and selected synthetic P1/P2 artifact handoff. The later native Rust pipe smoke gate is linked below.

[Mock loopback API](docs/LOOPBACK-API.md) validates actual local TCP authentication, token rotation, bounded/versioned requests, correlation and transport shutdown. Rust/GPUI remain unverified; subsequent cross-process HTTP evidence is linked below.

[Python HTTP child lifecycle](docs/HTTP-CHILD-LIFECYCLE.md) tests private-pipe bootstrap credentials, actual separate-process HTTP, in-progress shutdown and restart protection. This is not native desktop integration.

[Native Rust–Python pipe gate](docs/NATIVE-RUST-PIPE.md) builds and runs a narrow Windows no_std executable using the already bundled LLVM linker: 6 shared Rust guard checks, 3 direct Python round trips and 3 invalid-input cases. Cargo/libtest, Rust HTTP and GPUI remain unverified.

[Existing P1/P2 runtime handoff](docs/LIVE-RELAY-HANDOFF.md) tests the real recording engine/barriers and live loopback relay feeding P4, with a fake device only. Normal, truncated-response and lost-STOP-reply states are preserved. Sequential recordings remain isolated; STOP alone leaves live storage unsealed. A bounded selected-record snapshot now enables Python handoff while the relay stays on; validated route/link/packet bundles now publish together and are verified by the child loading path; invalid bundles finish as not_run without invoking an executor. Automatic UI scheduling, registry ownership and crash recovery remain unimplemented.

Explicit recordings refresh discovers published bundles in a running Python child, disables damaged entries and clears stale selection after scan failure. This is a bounded synchronous API, not a native UI or filesystem watcher.
