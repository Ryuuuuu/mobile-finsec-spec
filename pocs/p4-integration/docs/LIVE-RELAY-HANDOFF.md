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

Product integration constraint: the current P4 offline reader cannot consume a completed capture while the shared P2 writer remains open. A product that keeps the proxy running during inspection needs an explicitly sealed, consistent snapshot/export with recording identity and integrity metadata, or must stop/close the writer before handoff. A successful STOP must not be presented as packet-analysis readiness. Snapshot publication was absent at this initial test stage; the follow-up implementations below address the Python path. Copying the live SQLite main file alone is not an acceptable substitute. The synthetic tests do not cover abrupt process termination, concurrent external database writers or packets racing exactly with command admission.
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

The earlier continuous-proxy constraint is now addressed at the minimal Python export/handoff level. Automatic snapshot scheduling, UI readiness/progress/error events, registry ownership/retention and native Rust/GPUI integration remain design work. The next section implements a minimal Python route/link bundle publication path. A terminal database row does not certify complete collection: the unchanged P4 reader remains responsible for exposing partial/corrupt status. There is no atomicity claim across independently saved route/link and network files.
Snapshot follow-up validation: focused tests 9/9 passed; full structural runner 125/125 passed, zero skips (20.044 seconds), Windows/Python 3.12.10.

## Route/link/packet bundle publication (implemented follow-up)

`integration.recording_bundle.publish_bundle(link_path, route_path, db_path, output_root)` is a trusted local worker-thread POC. It reads bounded terminal P1 link/route bytes, exports only the link's selected terminal P2 recording into a private staging directory, rechecks the original P1 bytes for changes, and runs the existing P4 reader over all staged artifacts. Missing/corrupt/unsupported artifacts and mismatched route identity are rejected; valid partial states remain partial. A manifest records common and network recording IDs, individual completeness states and SHA-256 hashes. Only after validation does a same-volume directory rename expose a generated `recording-*` directory and return its paths. Consumers must ignore `.bundle-*` staging directories. Existing records are never chosen as publication destinations.

This is atomic visibility of a prepared local bundle, not an atomic transaction across P1 and P2 producers. The selected link is trusted provenance: matching IDs cannot detect a deliberately forged internally consistent link. Re-reading bytes detects ordinary concurrent source changes, not malicious change-and-revert or hostile filesystem races. The manifest is integrity metadata, not a signature; P4 now checks the manifest and artifact hashes as described below; this is not an authenticated manifest protocol. Publication does not make the files OS-immutable. Product registry ownership, access control, retention, crash durability/stale-stage recovery and native UI readiness events remain unimplemented. A process kill or power failure is not covered by Python exception cleanup.

Actual P1/P2 loopback tests verify: two completed recordings sharing a live DB yield one selected bundle, which remains usable after its original route file is replaced; a route from another recording is rejected without publishing anything; real truncated-response capture stays partial through bundle/P4 delivery; a source change during export and an injected failure after packet export leave no staged or public bundle. The relay remains on. These are Python filesystem/runtime tests with a fake device and synthetic traffic, not GUI, device or model acceptance.
Bundle follow-up validation: focused tests 12/12 passed; full structural runner 128/128 passed, zero skips (21.494 seconds), Windows/Python 3.12.10.

## Bundle consumption through the actual P4 loading path

The common `read_artifacts` entry point now verifies a present bundle manifest, and requires it for generated `recording-<32 hex>` directories. It checks the contract, fixed filenames/same directory, common/network IDs, completeness states, stored hashes versus both the parsed artifact hashes and current bytes, and manifest stability during loading. Invalid bundles return `bundle_status=invalid`, no actions/packets/grants, and unavailable recording mode. Valid bundles report `bundle_status=verified`; partial capture stays partial. This is consistency verification of trusted local metadata, not authenticated provenance. Historical loose fixture directories retain their existing missing/partial semantics.

The child startup registry ignores `.bundle-*` staging entries. The UI bridge marks invalid bundles as `status=invalid`. The structural supervisor reuses the same reader and stores a final `not_run` result with `INVALID_RECORDING_BUNDLE` before loading skills or invoking an executor; this is not an inspection verdict. A damaged bundle is never silently replaced by the no-recording launch intent.

Separate Python child-process tests now publish a synthetic bundle, register it, select it over the real private-pipe UI API, run the mock executor, and read the saved result. A partial capture retains its status and expected raw-request hash. A manifest ID mismatch, a whitespace-only route mutation after startup, and missing manifest are rejected at query time. Submitting the mutated bundle stores `not_run` and produces no executor receipt. Staging directories do not prevent child startup. These tests extend the prior direct-supervisor tests; they are not Rust, GPUI, actual device or model execution.

Explicit registry refresh is implemented in the next section; automatic publisher-to-running-registry notification remains absent. The existing packet grant still checks its database hash on later reads. Hostile local mutation after validation, authenticated signatures and filesystem ACL enforcement remain outside this trusted-root POC.
Consumer follow-up validation: private-pipe recording tests 5/5 passed; full structural runner 130/130 passed, zero skips (22.242 seconds), Windows/Python 3.12.10.

## Explicit running-service discovery

The approved workspace/run design assigns recording selection and authoritative project state to the Python service. The earlier startup-only registry could not discover a newly published bundle without restarting that service. A minimal explicit `recordings` operation (empty arguments, existing project/generation envelope) now rescans the trusted recording directory and returns opaque references, completeness summaries, `selectable` and a disabled reason. It adds no watcher or arbitrary client path. Both existing pipe and loopback transports share this wire dispatch; new end-to-end evidence below is for pipes.

A scan ignores `.bundle-*` preparation directories, keeps the existing 20-entry bound, validates published bundles through the common reader, and swaps the admissible registry once the scan finishes. Incomplete/corrupt/missing artifacts remain visible as disabled rows and are absent from the new selection registry. Valid partial states are selectable and remain partial. If the directory scan fails (invalid name/path or limit), the reply is unavailable and stale selection entries are cleared; already admitted jobs retain their copied file paths and their own validation/grants. No automatic retry, scan on every input, destructive repair or data deletion occurs. Consumers must apply the existing request-generation check before rendering a reply.

Actual separate Python process tests start with no records, publish a bundle after startup, refresh/discover/select/run it, then remove its packet file and verify refresh disables selection without altering saved history. A second test introduces an invalid directory, verifies unavailable plus refused stale selection, removes the test-only obstruction and refreshes successfully without restarting the child. Existing partial-bundle and post-startup mutation tests remain in the suite. No UI or device has been exercised.

This is a synchronous bounded POC scan: large directories/payload hashing latency, asynchronous worker offload, caching, filesystem notifications, background refresh during long-running work and race-proof filesystem ownership are not validated. Production must keep disk work away from the Rust render thread and avoid starving Python control/cancel processing. The implemented explicit refresh supersedes the earlier startup-only discovery limitation; automatic publisher notifications remain absent.
Refresh follow-up validation: private-pipe recording tests 7/7 passed; full structural runner 132/132 passed, zero skips (23.294 seconds), Windows/Python 3.12.10.
Follow-up ownership regression: actual P1 Network/Relay tests found and fixed abort STOP after preflight failure or confirmed recording_busy rejection; see ../../p1-record-replay/docs/COMBINED-RECORDING.md. Unknown-start compensation is unchanged; scoped STOP for independent clients remains a design gap.

## Relay shutdown and persistence failures across the handoff

Existing P2 tests already covered abrupt child-process termination, interrupted-record recovery, capture-write failure and command journal errors. The added integration tests therefore target propagation through actual P1 CombinedRun and the P4 reader/grants rather than duplicating those unit scenarios.

1. Relay closure before P1 STOP: orderly `Relay.close()` seals its packets, but P1 did not finish its own input barrier. Its later STOP fails, input/combined state remains partial and is never promoted from the complete packet state. This is a lifecycle surprise to P1, not a simulated process kill.
2. Injected SQLite failure during STOP packet finalization: P1 records uncertainty/incomplete input without retrying STOP. A new P2 Relay instance recovers the persisted unfinished row as interrupted/partial with a process_interrupted gap; already committed synthetic packet bytes remain accessible through P4. The gap is P2's recovery classification, not evidence of a literal OS crash in this test.
3. Injected command-journal failure after packet seal: packets legitimately remain complete, but P1 input/combined status stays partial and the mock executor sees both distinct states. Structural executor completion never means complete capture.

The first scenario exposed a real lifecycle defect: a command after Relay.close queried command history, reopening the closed WAL-mode database and leaving sidecars which made P4 report unsealed storage. The relay now rejects commands with relay_closed under the command/close lock before querying storage, including STATUS after closure. A direct test guards against any command-history access and checks that no WAL reappears. Reopening requires a new Relay instance, not ON against the closed instance.

These tests inject SQLite exceptions at real persistence methods; they do not exhaust the physical disk, simulate torn filesystem writes, or prove power-loss durability. Existing real P2 process-kill tests remain separate evidence. No device, model, GUI or inspection skill is involved.
Shutdown/storage follow-up validation: actual-code handoff tests 16/16 PASS (5.856s), P2 relay 40/40 PASS (10.880s), full structural runner 136/136 PASS zero skips (24.637s), Windows/Python 3.12.10.
Replay cancellation follow-up: actual P1 Engine/CombinedRun and P2 loopback replay now checks cancellation at the network STOP boundary. Input and packets may independently be complete while the combined result remains partial; source recording bytes stay unchanged. See ../../p1-record-replay/docs/COMBINED-RECORDING.md. This does not add replay-result support to the offline P4 route reader, which continues rejecting replay links as unsupported.
Recording-input follow-up: cancellation, simulated disconnect and action-journal failure after emitting an actual loopback request preserve one accepted action/two packets as partial route + complete packets in P4. Cleanup-journal failure no longer prevents scoped STOP. See ../../p1-record-replay/docs/COMBINED-RECORDING.md for evidence and storage limits.
