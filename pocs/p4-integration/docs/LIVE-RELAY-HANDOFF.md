# Existing P1/P2 runtime code to P4, without a device

## Toolchain gate first

An ordinary std-based Rust hello program was compiled with the already bundled rust-lld. Linking failed because Windows SDK import libraries (kernel32, ntdll, userenv, ws2_32, dbghelp and synchronization) are absent. Merely changing the linker therefore does not make the normal std/Cargo/GPUI path available. No toolchain install, license acceptance, OS change or attempted CRT emulation was performed. The previous [native no_std pipe smoke](NATIVE-RUST-PIPE.md) remains a narrow successful gate, not product code or a normal Rust HTTP client.

## Actual existing-code integration

The next useful gate connects existing P1 `Engine` and `CombinedRun` to an actual P2 `Relay` and SQLite writer, then reads the resulting artifacts through the P4 reader/supervisor/packet grant. P1's already existing Fake device adapter is the only device side; the upstream HTTP server is synthetic loopback. No Appium/ADB, GUI recording, real app or model is involved.

The test runs synchronous P1 calls in a worker thread and bridges network control calls to the real P2 asyncio loop. RECORD/STOP use the real command implementation. A P1 action is recorded between the barriers; a real loopback TCP request is forwarded and captured; STOP completes; the relay is closed before the bounded immutable P4 reader consumes storage. No database rows or final coverage states are manually edited for these tests.

Three executed scenarios:

|Scenario|Boundary verified|
|---|---|
|Normal HTTP response|Actual P1 route/link and P2 recording load as complete for their supported scope; one action and matching synthetic request bytes reach the mock P4 executor|
|Upstream closes before declared Content-Length|Real P2 parser/capture marks partial; CombinedRun's saved link remains partial and P4 preserves partial packet status|
|STOP finishes but its acknowledgement is lost|A test bridge drops the actual STOP reply; CombinedRun records network_stop_uncertain and a partial route/link, never automatically issues STOP again; P4 preserves the partial route|

The third failure is controlled response-loss injection, not an observed network loss or a failed P2 STOP. The underlying packet capture may be complete while the input/combined state is partial. The P4 mock executor may complete its structural handoff without asserting capture completeness or a vulnerability judgement. Raw synthetic request text is absent from the saved final result.

This checks ordering, file compatibility and preservation of failure states across existing runtime implementations. It does not prove a user GUI click caused a network request, perform timestamp-to-action attribution, replay a device route or validate whole-app traffic collection. Tests reuse trusted synthetic fixtures and do not implement or test inspection skills.

Reproduce from pocs/p4-integration: `python -m unittest discover -s tests -p test_live_relay_handoff.py -v`. The current explicit structural runner includes the same three tests. Temporary listeners, relay writers and files are cleaned up. No production runtime defect was found in these scenarios, so existing P1/P2 behavior was not modified.
Validation: Windows/Python 3.12.10 targeted scenarios 3/3 passed; full explicit structure runner 119/119 passed, zero skips (18.322 seconds).

## Sequential recording and publication boundary

The follow-up actual-code tests exercise two additional integration boundaries:

- STOP acknowledgment is not a storage seal. After a successful combined finish, the real P2 writer still owns WAL storage. P4 returns `packet_status=unsealed` and no packet payload. Closing the relay seals storage; re-reading the same files then yields complete packets and a successful structural handoff. No WAL files are manually removed and no live database is opened with immutable mode.
- Two sequential P1 combined recordings share one real P2 database. Five requests are forwarded (before, first recording, between, second recording, after); only the two in-recording requests are captured, one per recording. Distinct common IDs and P2 packet IDs remain isolated. A real packet grant reads its own synthetic body, returns `missing` for the other recording's packet under its own ID, and `denied` when the caller substitutes the other common ID.

The five focused tests passed on Windows/Python 3.12.10. These are actual local runtime and TCP boundaries with a fake device, not GUI/device/model tests. No runtime fix was required.

Product integration constraint: the current P4 offline reader cannot consume a completed capture while the shared P2 writer remains open. A product that keeps the proxy running during inspection needs an explicitly sealed, consistent snapshot/export with recording identity and integrity metadata, or must stop/close the writer before handoff. A successful STOP must not be presented as packet-analysis readiness. Snapshot publication is not implemented or claimed by this POC; copying the live SQLite main file alone is not an acceptable substitute. The synthetic tests do not cover abrupt process termination, concurrent external database writers or packets racing exactly with command admission.
Follow-up full regression: 121/121 structural tests passed, zero skips (18.868 seconds).

## Selected-record snapshot POC (implemented follow-up)

`integration.recording_snapshot.export_recording(source, destination, recording_id)` provides a trusted local worker-thread entry point. It opens the live source normally in SQLite read-only mode (not immutable), starts a read transaction, and accepts only a selected terminal recording (`completed`, `interrupted`, or `failed`). It creates a fresh v1 SQLite file containing only that recording and its packets, preserving metadata and BLOBs verbatim. It does not copy unrelated rows, command history or original SQLite free pages. After closing the new database, a same-directory hard link publishes the complete file without overwriting an existing destination. Unsupported hard links fail closed. The return descriptor carries the recording ID, size and SHA-256; the existing P4 reader and scoped packet grants consume the new file unchanged.

This relies on [SQLite WAL snapshot isolation](https://www.sqlite.org/isolation.html): a read transaction sees committed state at its start while separate writers can commit. It is a filtered transactional export, not a main-file copy or a complete-database backup. The caller must resolve trusted paths and IDs from its registry and run it off the UI/event-loop thread. This function is not exposed as an untrusted HTTP operation.

Bounds: at most 100 packets, 64 KiB metadata per row, 16 MiB output/page budget, default 5-second cooperative deadline (maximum 30 seconds), bounded SQLite busy wait. A read transaction can delay WAL checkpoint reclamation, so cancellation/deadline and storage quotas need product integration. The deadline is checked during copying and by SQLite's progress handler; it is not a hard OS deadline for stalled filesystem calls. Failure removes private temporary files; no output is published for active/missing records, size overflow or timeout. Existing output is never replaced. Filesystem crash durability, hostile path races/ACLs, low-disk failure, process-kill recovery and large-capture scale have not been established.

Executed tests use the existing P1 engine and P2 relay:

- A test barrier holds the export read transaction open while a second real recording receives a request and commits STOP. The first snapshot contains only the first recording and one packet; P4 mock handoff reads its bytes while the original relay remains on and forwards another request.
- A real short upstream response remains partial through snapshot and P4 handoff.
- An active recording is refused without disrupting capture; existing destination bytes are preserved.
- A tiny size budget and injected copy delay beyond the deadline publish nothing and remove temporary files; the relay remains usable.

The deterministic test barrier/delay are test instrumentation, not production scheduling or observed network faults. An initial test-only SQLite handle leak caused Windows temporary cleanup failure; explicit connection closure fixed it. No device, model, inspection skill or GPUI is exercised.

The earlier continuous-proxy constraint is now addressed at the minimal Python export/handoff level. Automatic snapshot scheduling, UI readiness/progress/error events, registry ownership/retention, route/link bundle publication and native Rust/GPUI integration remain design work. A terminal database row does not certify complete collection: the unchanged P4 reader remains responsible for exposing partial/corrupt status. There is no atomicity claim across independently saved route/link and network files.
Snapshot follow-up validation: focused tests 9/9 passed; full structural runner 125/125 passed, zero skips (20.044 seconds), Windows/Python 3.12.10.
