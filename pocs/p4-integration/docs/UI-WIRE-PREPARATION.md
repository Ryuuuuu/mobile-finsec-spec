# Serialized mock UI boundary and Rust state preparation

## Scope and decision

The user deferred administrator interaction and has not accepted Microsoft Build Tools terms. No MSVC/SDK installation, license acceptance, WSL installation, reboot or security setting change was attempted. Existing WSL reports that the subsystem is not installed; Docker was not discoverable. Thus there is no confirmed alternate Linux build environment.

Rust/Cargo 1.100.0 (stable x86_64-pc-windows-msvc) and CMake 4.5.0 were installed from official downloads with matching SHA256 files. Their user PATH entries preserve earlier entries and were verified in a fresh PowerShell using persisted Machine/User PATH. A synthetic Rust metadata compilation succeeded; executable linking failed because link.exe is missing. This is a toolchain probe, not GPUI compilation.

To make progress without installer approval, this change implements only the serialized application boundary and an independent Rust selection guard. It deliberately does not select a network framing protocol or claim the proposed authenticated loopback service exists. The [native preparation plan](GPUI-NATIVE-PREPARATION.md) still applies after MSVC/SDK preparation. The previous no-tools observation is historical; only MSVC remains missing from the current discovery probe.

## Implemented connection

`integration.ui_wire.UIWire.exchange(bytes) -> bytes` decodes a bounded JSON request, validates project/version/generation/operation, then calls the existing UIBridge or StartAPI on its owning asyncio thread. It serializes the actual returned envelope. It is neither a server nor authentication: project ID is only a routing check. Do not bind this object directly to an exposed network listener.

Request fields are exactly `contract=mock-ui-request.v1`, `project_id`, `request_generation` (integer 0 through 2^53-1), `operation`, and `arguments`:

|Operation|Arguments|
|---|---|
|recording|ref|
|inspect / submit|request (existing structural-start.v1 object)|
|progress|execution_id, cursor|
|cancel|execution_id|
|history|empty object|
|result|run_id|

Requests/responses are bounded at 256 KiB; duplicate JSON keys, wrong types/versions/project and unexpected fields are rejected. Fixed errors contain no raw exception, input packet or path. An oversized response or service/serialization error reports outcome unknown: a mutation may already have happened. A client must retain the original command ID and query authoritative state, not automatically resubmit with a new ID. Live progress now uses bounded pages (see [page contract](UI-CONTRACT-BRIDGE.md)); source logs above 1 MiB and oversized result/history payloads remain unsupported. This is not lossless transport support.

Success uses the existing mock-ui.v1 envelope. Start/inspect/cancel wrap API data; other methods preserve their projection. Packet bodies remain behind the selected mock executor's existing grant, not in automatic screen messages. The existing source-format P1/P2 fixtures are used, not actual device recordings.

`rust-ui-state/lib.rs` is standard-library-only Rust for project/generation/run rejection and explicit tab selection, with a matching maximum generation. Generation overflow preserves the old selection. It does not parse JSON, perform I/O, deduplicate events or create GPUI entities/windows. An eventual background transport must parse and validate typed payloads before this guard runs, then apply accepted state to GPUI on its UI thread. It must not block the render thread or auto-switch to results.

## Evidence and remaining gates

The JSON tests described here are in-process only. Subsequent [Python-to-Python pipe tests](MOCK-STDIO.md) executed real child-process communication, response deadlines, shutdown and cleanup/restart handling. Those later results do not establish Rust-to-Python IPC or native GPUI execution.

Three new Python async tests **executed and passed**: serialized recording/preflight/start/live/final-history flow, duplicate command reuse, bounded/invalid requests and sanitized errors, cancellation, and history with no connected mock device. These use real facade/runner code with opaque mock skills and synthetic artifacts; no inspection content or assessment logic is added.

Rust library and Rust test sources both **compiled to metadata successfully** with rustc 1.100.0. Rust tests were **not executed** and no executable was linked. This checks parsing/type checking only, not runtime behavior or compatibility with GPUI dependencies. This metadata/JSON stage did not test process shutdown; later mock Python shutdown results are linked above. Actual Rust-to-Python IPC, HTTP authentication, GPUI crate resolution, native rendering and Korean input remain unverified.

Reproduce from pocs/p4-integration with the prepared Python environment:

```text
python -m unittest discover -s tests -p test_ui_wire.py -v
rustc --edition=2021 --crate-type lib --emit=metadata rust-ui-state/lib.rs -o <private-output>/ui-state.rmeta
rustc --edition=2021 --test --emit=metadata rust-ui-state/lib.rs -o <private-output>/ui-state-tests.rmeta
```

After MSVC/SDK installation, execute Rust unit tests, build the official GPUI minimal example, implement the authenticated transport and JSON decoding, then run the real native vertical slice. No test here replaces those gates.
