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
