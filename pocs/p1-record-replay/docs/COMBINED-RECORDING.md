# P1/P2 combined GUI recording

QA-only integrated recording implemented and measured on the authorized Android device; limitations below remain explicit.

The integrated scrcpy GUI owns one input engine and one independent P2 relay loop. Start is a two-party barrier: prepare the input route, await P2 RECORD acknowledgement, persist both recording IDs, then permit GUI input. Requests before the network acknowledgement are outside the common input window. This is not an atomic distributed transaction.

STOP immediately prevents new input and cancels undispatched queued input, then drains serialized work, awaits network STOP and persists the input route. The combined result is completed only if both route and network recording complete. Missing acknowledgement, failed postcondition, interrupted input or cleanup failure produces partial/uncertain state; no automatic input retry or fabricated rollback. A separate local journal links start/end markers and both recordings. Action dispatch/result UTC times may be compared with network request timestamps, but overlapping intervals alone do not establish causality. The disposable app's explicit correlation token supplies stronger fixture-only linkage. P1/P2 do not infer arbitrary app attribution.

A dedicated network QA app will expose native and WebView test buttons with resource IDs and exact sent-count postconditions. Both use only a temporary loopback USB mapping and synthetic token responses. WebView is a separate client path, not evidence of general browser or OkHttp support. No global proxy, CA or additional device policy change is part of this design.

## First device iteration

Native and WebView GUI actions both passed their postconditions. WebView additionally requested `/favicon.ico`; the initial synthetic upstream rejected it by closing the socket, correctly producing partial network coverage and a partial combined result. The fixture now returns a valid empty 204 for favicon. This is not filtered out of capture: one action can produce several requests, including uncorrelated resources. A fresh device run is required before claiming complete coverage. Lost STOP acknowledgement is never automatically retried; partial/uncertain status is retained for manual recovery.

## Final device acceptance

After the favicon correction, a fresh GUI recording completed: two actual mouse clicks on the integrated mirror, native HTTP then WebView HTTP, passed `sent:1` and `sent:2` postconditions. STOP saved the route and P2 recording with combined status **completed**. Three network transactions were retained (two token-bearing requests plus favicon); none were hidden to force a one-action/one-request result.

The local timeline exporter linked the native request to its GUI dispatch/result interval and exact fixture token at about 75 ms after dispatch, and the WebView request at about 169 ms. The favicon arrived about 316 ms after the WebView dispatch and remained **time_interval_only**, not an asserted causal/business-request match. These are single-run observations, not latency benchmarks or cross-device clock guarantees. Both action results succeeded and request sequence was native, WebView, favicon.

A PC-generated synthetic request before RECORD and another after STOP were delivered but excluded from the captured rows. These boundary probes were not GUI actions and are not counted as app-origin recording. GUI clicks outside the combined recording window were rejected and the app state did not advance. The prior broken-favicon run remained partial; acknowledgement-loss/start-cancel/partial-input cases are automated fault-injection tests, not real USB-unplug acceptance.

The existing private TLS test certificate was checked for expiry before reuse (still valid during this run); the integrated GUI scenario uses HTTP only. Earlier separate device HTTPS/WSS results are documented in P2 and are not reclassified as combined-GUI TLS acceptance. No new device security settings or trust stores were changed. GUI and owned services/forwards are cleaned on normal close; actual device data stays local.

## Execute

Build/update only the dedicated P2 network QA APK from `pocs/p2-proxy-relay/android` using the P2 instructions. It now includes native and WebView buttons. The WebView cleartext policy is scoped to this disposable app's `127.0.0.1`; base cleartext remains disabled. Appium must be launched from its installed project directory so the pinned UiAutomator2 driver is found.

From the P1 folder and its venv (including `requirements-mirror.txt`):

```powershell
python -m pc.combined_ui --device YOUR_SERIAL --server-jar C:\Tools\scrcpy\scrcpy-server --output C:\QA\combined-private
```

This QA-only entry point starts a fixed synthetic loopback upstream and P2 relay, owns one temporary USB reverse mapping, and prepares only `dev.finsec.qa.network`. It does not choose a real third-party app or alter the global proxy. Review the whole-device video notice and device preflight. Connect, keep initial condition `ready`, choose RECORD, set next postcondition to `sent:1`, click SEND NATIVE HTTP, set `sent:2`, click SEND WEBVIEW HTTP, then STOP. Replay JSON now opens the saved GUI route after the operator explicitly restores its initial QA state. P2 RECORD acknowledgement precedes replay dispatch; STOP follows the input result. Input success and network coverage are retained separately. A combined partial result does not overwrite a successful input result, or mutate the source route.

Export a local correlation report using the saved input route directory, associated `network-*.sqlite3` and the synthetic fixture token prefix:

```powershell
python -m pc.timeline --input-dir C:\QA\combined-private\INPUT_RECORDING_ID --network-db C:\QA\combined-private\network-LOCAL_ID.sqlite3 --fixture-prefix qa-YOUR_FIXTURE_PREFIX --out C:\QA\combined-private\timeline.json
```

Without a supplied, matching fixture prefix the exporter reports only time-interval candidates. Keep the report private: IDs and local timing are real test evidence. The GUI shows recording state; a full visual timeline inspector is still a product task.

## Limits

Not accepted: arbitrary-app interception or OS-enforced attribution, physical USB loss/reconnect, distributed-clock synchronization, or general production rollback. Scoped TLS/replay and OkHttp follow-up results are recorded below. WebView support here means this cooperative local page and its extra favicon request, not all WebViews. A loss of STOP acknowledgement remains partial/uncertain without automatic retry. P2 continues independently while the GUI drains Appium input; a crash may leave recoverable partial files and requires explicit recovery, not an atomic transaction claim.

Final regression: **P1 100/100 and P2 75/75 passed** on Windows. The updated APK also reran all four separate app-origin HTTP/HTTPS/WS/WSS positive cases successfully. This separate regression does not extend combined-GUI acceptance beyond HTTP.

## Secure replay follow-up (2026-11-18)

Install `requirements-combined.txt`. Select `--protocol https` or `wss` and `--pki C:\QA\private-pki` generated by P2 make_qa_pki.py; the installed disposable QA APK must embed the matching public CA. No OS CA or global proxy is changed. The CA signing key is discarded by the generator; check expiry before reuse and rebuild the QA APK for a new CA. The fixture relay verifies the upstream certificate; the app verifies the listener certificate and hostname. WebView is disabled outside the existing HTTP fixture (no SSL error bypass).

Design change: combined replay uses a new linked input run and network recording for every replay. Network start failure blocks dispatch. Input failure still closes the network window. STOP failure leaves partial/uncertain without automatic STOP retry. Manual input stays disabled while replaying. This is a barrier protocol, not atomic rollback. The source route is never rewritten by replay abort.

The disposable fixture additionally supports `okhttp-http` and `okhttp-https`, using pinned Square OkHttp 4.12.0 (Apache-2.0), HTTP/1.1, fixed loopback URL, app-local CA trust, default hostname verification, no redirects or retry. This is a compatibility sample, not a claim about every OkHttp version or general app routing. Official dependency metadata: https://central.sonatype.com/artifact/com.squareup.okhttp3/okhttp/4.12.0 .

Real-device standalone matrix: HTTP/HTTPS/WS/WSS/OkHttp HTTP/HTTPS each captured 3 requests with pre/post requests delivered but excluded (30 app operations, 18 recorded). HTTPS/WSS/OkHttp HTTPS rejected an unrelated CA with SSLHandshakeException, zero upstream requests and zero stored rows. These are cooperative fixture tokens, not OS-enforced app attribution.

Actual GUI HTTPS: one canvas click recorded, then the saved route replayed after explicit QA restart. Both completed with one successful postcondition and one token-linked HTTPS transaction. Dispatch-to-request intervals were 148.500 ms for recording and 142.904 ms for replay. This latency is observed on the same PC, not a causal proof for arbitrary traffic. WSS GUI recording was interrupted by an actual device disappearance: ADB reported device not found and scrcpy reported ConnectionResetError. The linked run remained partial, route incomplete with zero accepted actions, and P2 STOP acknowledged network_coverage=none. WSS GUI replay is not accepted; reconnect and rerun. The independent WSS app/relay matrix above remains passed. GUI closed and owned Appium was stopped; device-side final settings/reverse cleanup cannot be confirmed while disconnected. No settings beyond the existing approved baseline were requested. P1 110 and P2 75 automated tests passed.

## Reverse ownership follow-up

See [ADB reverse diagnosis and recovery](ADB-REVERSE-RECOVERY.md). The host ADB crash was confirmed; overlapping tcp:0 registrations are a strongly supported mechanism, not yet an isolated device reproduction. The GUI and standalone harness now share a lifetime device reservation and explicit verified reverse-port ownership. Device acceptance of this revision is pending phone authorization.

## Start-failure cleanup ownership (2026-11-18 local regression)

A real local Network/Relay test reproduced an ownership defect: when an existing network recording was active, a new CombinedRun preflight failure or a `recording_busy` rejection still entered abort cleanup and sent an unscoped STOP, ending that existing recording. Both cases failed before the fix. This was synthetic loopback reproduction, not a device observation.

CombinedRun now tracks whether its RECORD was attempted. A preflight/input preparation failure before dispatch skips network STOP. The Network adapter exposes `NetworkStartRejected` only for a confirmed `recording_busy` response with no applied/state-may-have-changed marker; that path also skips STOP. The saved partial link records `network_not_started`, and the journal records `network_stop_skipped_not_started`. Record and replay use the same start helper. Input is not enabled on these failures, and replay is never dispatched.

Unknown exceptions/timeouts and storage acknowledgements are not converted to definite rejection. Existing uncertain-start compensation and no-repeat-after-uncertain-STOP behavior remain. This does not establish multi-client ownership: the current STOP API has no expected recording ID or fencing token. Safely sharing a relay among independent owners would require a scoped STOP/idempotent-start reconciliation protocol; do not infer that arbitrary concurrent clients are supported from this fix.

Tests run actual P1 Network/P2 Relay plus a fake input engine, covering both preflight failure and busy rejection for record and replay. Existing network recording identity remains active until the test owner explicitly closes its network. The first attempted test interpreter lacked Pillow (P4 structural venv); no packages were installed. Tests were rerun in the already provisioned P1 venv. No window, device, model or inspection skill was exercised.
Validation: P1 test_combined.py 21/21 passed (1.634s); active P4 structural runner 132/132 passed, zero skips (29.236s), including real P1/P2 handoff and lost-STOP tests.
Scoped-stop follow-up: P1 now persists a generated intended recording ID before RECORD, verifies the returned ID and scopes every normal/replay/abort STOP to that ID. P2 supports the additive fields and refuses stopping another active ID. See ../../p2-proxy-relay/docs/EXECUTION-SPEC.md for compatibility and uncertain-response limits. The prior unscoped compensation limitation is mitigated for upgraded cooperating P1/P2; untrusted ownership enforcement remains absent. Updated P1 requires updated P2 and never downgrades to unscoped cleanup.
Delayed-start follow-up: the updated P2 persists cancellation of an expected ID even when STOP arrives before RECORD. The actual CombinedRun timeout/delayed-dispatch test confirms one compensation STOP prevents late activation, preserving incomplete input. This supersedes the earlier delayed-start gap only for the same preassigned ID and updated durable relay store; see P2 execution spec for capacity/downgrade limits.

## Cancellation near replay completion

A new core test reproduced a late-cancellation defect: cancelling while the last action's after-observation was being captured still saved the replay as succeeded. `Engine.execute` now checks cancellation after that observation and before success journaling. `Engine.replay` also checks before overall finalization, covering cancellation during the last action-result write. If the action result was already committed successfully, that individual step stays succeeded while the replay becomes incomplete; no input is retried.

Combined replay separately checks cancellation after network STOP/drain returns. Input may already have a valid succeeded result and the network may have sealed complete supported-scope packets, but a cancellation observed before combined finalization now produces a partial combined link with cancel_requested and replay_cancel_observed, and an incomplete combined return. The original source recording is preserved. This does not reinterpret normal record STOP as cancellation: record finish semantics are unchanged.

An actual Engine/CombinedRun/Relay loopback test records a source route, replays it through the fake input adapter (which triggers a synthetic HTTP request), injects cancellation at the STOP boundary and verifies input succeeded / packets complete / combined partial, no active network recording, and unchanged source bytes. Two core tests cover cancellation during final observation and final action journaling. The cancellation points are deterministic test instrumentation; no live GUI click, real device or model was exercised. These finite checkpoints do not claim OS-level interruption of an in-flight transport or total ordering of every concurrent instruction; cancellation after terminal commit is too late to rewrite that completed outcome.
Cancellation follow-up validation: core 27/27 PASS (4.951s), combined 22/22 PASS (2.926s), P4 structural 137/137 PASS zero skips (26.268s).

## Recording input failures and cleanup storage independence

The next actual-code tests cover cancellation, an Uncertain transport error and action-result journal failure after a fake input adapter has already emitted an HTTP request. A prior acknowledged action remains in the route; the failed second action is not appended. Both already emitted requests remain captured. After scoped abort, P4 receives route partial / packet complete with one recorded action and two packets; structural completion is not capture/input success and does not infer per-action packet attribution. No input or STOP is automatically retried.

A separate test reproduced a cleanup defect: CombinedRun.abort wrote its gap log before sending STOP, so an OSError on that journal left its P2 recording active. Abort now performs independent best-effort persistence, always reaches its one scoped STOP attempt, marks input incomplete, and attempts route/link persistence even if another write fails. Cleanup write failures set storage_incomplete where saving remains possible and are raised to the caller, not swallowed. If STOP has a known reply, a subsequent log-write error no longer becomes network_stop_uncertain; unknown STOP remains unknown with no retry. The attempt is marked terminated after cleanup attempts so a repeated abort does not repeat STOP.

Record finish's initial input_closed/save barrier is now inside its error-handling block, so failure there also reaches abort. An in-memory completed state before final persistence no longer suppresses failure cleanup; only a terminated/idle run skips it. Normal record/replay semantics and previously completed source data are preserved by existing identity guards.

These are deterministic OSError/Uncertain injections, not physical disk-full or device-disconnect tests. If all writes fail, no code can promise durable error evidence; in-memory state/caller error and the attempted cleanup are the available outcome. OS process death during cleanup, transport that never returns, GUI event ordering and real device behavior remain separate gates.
Recording-failure follow-up validation: focused real-code handoff 22/22 PASS (7.188s), P1 combined 22/22 PASS (2.078s), full structural runner 142/142 PASS zero skips (29.535s), Windows/Python 3.12.10.

## Owned Network shutdown lifecycle

A real Network/Relay test reproduced a resource leak: when relay close raised a storage error, fixture server close/task cleanup were skipped, while the outer finally stopped the event loop. The fixture listener stayed serving and the loop remained unclosed; the test reported pending task/socket warnings. Shutdown now independently closes that listener, cancels/joins fixture tasks, shuts down async generators/default executor and closes the loop after its thread exits, even if the relay reports failure. The original error remains visible, including on repeated close.

A timeout waiting for shutdown is not cleanup confirmation. Network retains one shutdown future and the running loop; a later close waits for that same future rather than starting duplicate cleanup. Commands are rejected once shutdown begins. The terminal future allows thread/loop closure; an unconfirmed thread stop remains an error. Successful repeated close is idempotent. A deterministic gate test exercises timeout, blocked commands, release and subsequent confirmed close with exactly one relay-close invocation. This is a single-owner close API, not a tested arbitrary concurrent-caller shutdown API.

CombinedWindow's existing queued cleanup now poisons its reservation if Network.close fails, while still attempting owned reverse cleanup. A no-window unit test verifies this callback path with mocks; it is not GUI/device acceptance. The GUI does not automatically reconcile a pending network shutdown after its window has exited: a product supervisor/recovery flow remains required, and uncertainty is deliberately retained. A permanently stuck OS operation is not proven terminable by this POC. Constructor failure paths and arbitrary process kill are separate lifecycle gates.

No installs, live device interactions or inspection skills were used. This follow-up modifies the actual P1 Network wrapper; the P4 structural runner does not exercise that wrapper and was not redundantly rerun for a passing unrelated code path.
Network lifecycle validation: test_combined.py 25/25 PASS (2.252s), Windows/P1 venv, with ResourceWarning promoted to error; no pending-task/unclosed-resource warning observed in the final log. Includes actual Network/Relay loopback tests and one explicitly mocked no-window cleanup hook test.

## Network initialization failure and retry

A real invalid-output-path test reproduced another leak: Network created its fixture listener/thread before Store initialization failed, then raised without closing them. Constructor failure now enters the same owned close path. TLS certificate loading and optional WebSocket imports happen before loop/thread creation. Optional resources are initialized as absent so cleanup can handle failure before relay creation. A real filesystem-invalid destination test confirms cleanup before a subsequent fresh Network succeeds.

For a timed-out setup, cleanup waits for the original setup future before closing anything it eventually creates. It does not start a second setup or infer that timeout cancelled resource creation. If the bounded cleanup wait also expires, construction raises an initialization/cleanup-unconfirmed error with a local cleanup_network owner reference. That owner rejects new commands and a controller can later call close on the retained future. A gate test verifies exactly one setup, explicit unresolved ownership, release and confirmed teardown. This handle is local Python state, not an API payload or a durable recovery record.

An automatic GUI recovery controller, persistence across process exit, arbitrary OS allocation failure and permanent stuck transport remain unimplemented/unverified. Callers must retain/reconcile the exposed pending owner rather than treating the constructor exception as proof that resources were never created. This follow-up supersedes the earlier constructor-failure gap for the tested paths only.

Validation: test_combined.py 28/28 PASS (2.396s), with ResourceWarning promoted to error; no pending-task/unclosed-resource warning in the final log. Uses actual local Network/Relay, a real invalid directory target, a preflight-order guard and a controlled startup delay. No GUI, device, model, installation or inspection skill execution. P4's unrelated structural suite was not rerun.
