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

This QA-only entry point starts a fixed synthetic loopback upstream and P2 relay, owns one temporary USB reverse mapping, and prepares only `dev.finsec.qa.network`. It does not choose a real third-party app or alter the global proxy. Review the whole-device video notice and device preflight. Connect, keep initial condition `ready`, choose RECORD, set next postcondition to `sent:1`, click SEND NATIVE HTTP, set `sent:2`, click SEND WEBVIEW HTTP, then STOP. No combined replay is advertised; the button explicitly reports that it is unimplemented.

Export a local correlation report using the saved input route directory, associated `network-*.sqlite3` and the synthetic fixture token prefix:

```powershell
python -m pc.timeline --input-dir C:\QA\combined-private\INPUT_RECORDING_ID --network-db C:\QA\combined-private\network-LOCAL_ID.sqlite3 --fixture-prefix qa-YOUR_FIXTURE_PREFIX --out C:\QA\combined-private\timeline.json
```

Without a supplied, matching fixture prefix the exporter reports only time-interval candidates. Keep the report private: IDs and local timing are real test evidence. The GUI shows recording state; a full visual timeline inspector is still a product task.

## Limits

Not accepted: OkHttp, arbitrary-app interception or OS-enforced attribution, combined HTTPS/WSS, replay synchronization, physical USB loss/reconnect, distributed-clock synchronization, or general production rollback. WebView support here means this cooperative local page and its extra favicon request, not all WebViews. A loss of STOP acknowledgement remains partial/uncertain without automatic retry. P2 continues independently while the GUI drains Appium input; a crash may leave recoverable partial files and requires explicit recovery, not an atomic transaction claim.

Final regression: **P1 100/100 and P2 75/75 passed** on Windows. The updated APK also reran all four separate app-origin HTTP/HTTPS/WS/WSS positive cases successfully. This separate regression does not extend combined-GUI acceptance beyond HTTP.
