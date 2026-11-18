# Ordered combined replay queue

The combined Tk GUI now selects multiple saved route JSONs, displays action counts/recording IDs, allows Move up/down, and runs the reviewed order through the existing `CombinedRun.replay`. Its existing device reservation and single worker remain the owners. A route's input replay, scoped P2 STOP acknowledgement and terminal result persistence must complete before the next route starts. Each entry retains its source recording ID/content hash, new replay run ID, combined ID and network recording ID. Repeating a sequence creates new results rather than overwriting source recordings or prior results.

`ReplayQueue` validates/deep-copies all routes before dispatch, rejects concurrent calls, and persists ordered intent before any operation. The queue cancellation remains set even when the per-route engine clears its local cancellation flag. Unknown/partial/failed/cancelled outcomes stop remaining entries as not_run. Storage failure blocks subsequent calls on that owner. No automatic retry or continuation is performed.

**The user has not selected the final failure policy.** Stop-all, skip, explicit retry or manual resume remain product choices; conservative stopping here is a POC guard, not a finalized product policy. Durable queue admission/restart reconciliation and cross-project ownership remain separate integration work. The queue file is evidence, not an auto-resume instruction. The POC's storage block is in-memory; after a crash, inspect incomplete queue/combined/network records before permitting another attempt.

## Initial state and use

Run the existing combined GUI with an authorized QA target and verified fixture/network configuration. Connect, choose **Select ordered replay queue**, select reviewed routes, arrange their order, then **Run ordered queue**. The queue does not clear app data, reset arbitrary apps, install a CA, change global proxy settings or bypass secure capture. Each recorded initial condition must be satisfied. An explicit fixture owner may supply a preparation callback; the A34 acceptance used only the disposable network QA app restart with its approved loopback port and synthetic token. No general-app reset behavior is inferred from this fixture.

The record catalog/ordered mock queue in native GPUI remains a separate structural POC. **This commit validates actual device dispatch from the P1 Tk combined GUI, not GPUI-to-device dispatch.** The next native integration should call this same queue owner through a bounded asynchronous API with immutable route references, admission identity, progress, cancellation and reconciliation rather than duplicate its execution logic in Rust.

## Actual A34 acceptance, 2026-11-18

A previous GUI-recorded one-tap WSS route and a freshly GUI-recorded two-tap WSS route were used. The new route was captured by RECORD and actual PC mirror clicks, with exact sent:1 and sent:2 postconditions; it was not fabricated by a CLI. Both routes matched the current installed QA APK and device. A private fixture owner backed up receipt data before testing and prepared ready state before each route without clearing app data.

|GUI-selected order|Input result|Separate P2 packet rows|Capture coverage|
|---|---|---|---|
|one-tap -> two-tap|both succeeded|7, 14|complete_for_supported_scope, no gaps|
|two-tap -> one-tap, reordered in GUI|both succeeded|14, 7|complete_for_supported_scope, no gaps|

All four replay IDs and network IDs were distinct, all source/result links matched, all steps succeeded, and 42 packet IDs were unique with contiguous per-record sequence numbers. A single WSS send produced one handshake, open/close events and four frames; two sends produced twice those counts. The next combined run started 0.431s and 0.437s after the previous combined terminal event in the two queues, so the observed scopes did not overlap. This demonstrates only the cooperating QA app/loopback capture scope, not general app attribution or arbitrary banking-app compatibility.

The GUI displayed Queue succeeded after each sequence. Normal close restored the backed-up QA receipt byte-for-byte, removed owned reverse mappings, stopped the owned Appium listener, and left no active/quarantine marker. User-requested hidden API policies=1 and helper mock-location=allow remained unchanged. Device captures, serials, packet payloads and TLS material remain private.

## Automated scope

Six queue regression tests use the real Engine/CombinedRun with a fake device and network boundary: three distinct ordered routes and repeat isolation; partial network scope; cancellation during RECORD acknowledgement; intent-write failure/duplicate admission; terminal-write failure; preparation failure. They do not count as real cancellation/disconnect/disk-full trials on A34. Existing P1 regression tests remain required. Product-scale queue durability and GPUI device integration are not claimed.

Final Windows P1 suite: 139 tests passed in 11.376s, zero skips. An initial regression exposed close() on a partially constructed test window without a queue; close now tolerates that state. The real GUI acceptance occurred before the final storage-failure retry guard was added; the added guard was covered by automated failure injection, not a destructive live disk-full trial.
