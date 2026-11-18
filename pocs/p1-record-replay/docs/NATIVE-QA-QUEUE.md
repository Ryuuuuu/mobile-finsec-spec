# Native QA queue API

This opt-in private-pipe adapter connects the GPUI three-tab POC to existing ReplayQueue, CombinedRun, Appium and P2 NetworkController. It is restricted to `dev.finsec.qa.network`, an already installed disposable cooperating QA app. It does not implement inspection skills, general app automation or security verdicts.

## Private configuration

`python -m pc.qa_queue_stdio --config <private-config.json>` runs from P1 with the existing P1 environment and its P2 dependencies. Configuration fields are `device`, `adb`, local `appium` URL, `output`, `pki`, `allow_existing_appium_settings`, and `routes`. Each route entry has `ref`, `name`, timezone-aware `recorded_at`, and a private `path` to an existing GUI-recorded v2 route. Do not commit a populated device configuration or its outputs. Use a currently valid matching QA PKI/APK; certificate validation is not weakened.

The explicit approval flag is not authorization to make new changes. Preflight requires the previously approved existing baseline (three hidden API policies at 1 and helper mock-location allow), matching recorded device and installed APK. A mismatch stops execution. Preparation starts only the QA fixture activity, using a new fixture token per route. There is no package-data clear, system proxy change or system CA installation. The original QA receipt is backed up and restored byte-for-byte after cleanup.

## Contract and ownership

Readiness is `qa-device-stdio.v1`; requests are `qa-device-request.v1`, project `qa-device-queue`, correlated integer request_generation; responses are `qa-device-ui.v1`. Operations: recordings, submit, progress, cancel, history and result. Requests are bounded to 64 KiB and native responses to 256 KiB. Submit accepts one command_id and 1..100 ordered recording_refs, with one worker/device reservation across the sequence. Identical command retries do not replay; conflicting selections reject. Durable admission is saved before starting. Incomplete or unconfirmed prior cleanup blocks new admission after restart; no automatic replay/resume.

Route contents are validated and snapshotted at API startup. Each route's new replay and network capture get distinct IDs. Existing source packets are not silently loaded. Progress is transient; final history is written only after the cleanup attempt. Cleanup failure remains blocked and cannot be mistaken for a completed queue. Product failure/skip/retry policy is still undecided; this POC stops remaining routes.

EOF requests cancellation and joins the worker. Native transport timeout closes stdin and blocks further requests, but **does not kill the live device child**. The window may close before cleanup finishes: closing it is not proof of cleanup. The external owner must reconcile private final/cleanup records and device reservations before stopping its Appium server or starting another attempt. Do not force-kill or automatically replace an uncertain owner.

ADB subprocesses must not inherit the protocol stdin: use DEVNULL for read-only/control commands; explicit receipt restoration gets a separate input pipe. A real native attempt reproduced timeout/interruption before this fix; the same sequence passed afterward. Synthetic subprocess tests verify pipe isolation without a device.

## Verification

`python -m unittest discover -s tests` passed 145 P1 tests, including four queue API tests and two subprocess ownership tests. Native A34 acceptance: double-send -> single-send, both succeeded, distinct 14/7 packet capture scopes, source/result linkage verified, cleanup verified, receipt restored and maintained settings unchanged. Earlier interrupted execution remained separately queryable. See [native workspace ledger](../../p4-integration/docs/NATIVE-WORKSPACE.md) for the actual UI observations and remaining gaps.

## New capture bridge: separate P1 window

The POC adds `capture` admission using the same exclusive owner as replay. The native Record tab opens one separate existing P1/Tk mirror window; it does not embed a new video/input implementation in GPUI. The operator connects, presses RECORD, performs PC mirror input, and presses STOP. Successful save closes that child window and restores the QA receipt before a route becomes selectable. Configuration additionally requires the existing official scrcpy `server_jar`. Device input, certificate validation and capture restrictions remain unchanged.

The parent persists admission before opening the child. EOF/cancellation writes a private cancellation marker; the child drains its existing cleanup path. No hard kill is used to manufacture a clean outcome. The device reservation is retained through receipt restoration. Unknown child exit or cleanup leaves admission blocked for reconciliation.

Only a nonempty completed route with matching completed P1/P2 linkage and verified cleanup is published under `saved-recordings`. Entries have generated names/timestamps and scoped immutable references; path scope and linkage are checked again on reload. Existing configured routes remain listed. Failed or cancelled captures are not silently promoted. Original packet data is retained privately beside the capture; list metadata does not imply packet contents were loaded by an agent.

Validation on 2026-11-19: 148 P1 tests passed. New cases cover publication/restart/selected replay, incorrect linkage or external paths, unconfirmed cleanup, and shared capture/replay exclusion with cancellation. GPUI build passed. After the user resumed screen interaction, actual native acceptance passed:

- Record tab opened the separate P1 mirror. Connect -> RECORD -> one PC mirror WSS tap -> STOP created a new route and automatically returned after cleanup.
- Refresh showed two existing routes plus the new named/timestamped capture. The first attempt used an incorrect operator-entered postcondition (`sent 1` instead of actual `sent:1`); it remained interrupted, was excluded from the catalog, and cleanup succeeded. This was an operator error, not a successful recording.
- New capture -> existing double-send route was selected in GPUI and replayed sequentially on A34. Results showed both succeeded with separate 7/14 packet scopes. The source capture's own seven packet rows retained a third distinct scope.
- Source recording identity matched the first replay, original QA receipt bytes matched all three attempt backups, reverse mappings were empty, active/quarantined leases were zero, and user-maintained settings remained unchanged. Normal native close also stopped the owned Appium server.

Real evidence stays private. This proves a native-launched separate P1 recording/replay flow for the cooperating QA app; it does not prove embedded GPUI mirroring, arbitrary-app automation, custom naming/editing, native active-cancel acceptance, or inspection/model execution. Names are generated and refresh is explicit. Automated restart/catalog tests use synthetic fixtures; no native UI restart acceptance is claimed.

## Cancellation, loss and restart acceptance (device-free)

Follow-up to `4245317`, 2026-11-19: five new regression tests in `tests/test_native_failure_boundaries.py`; full P1 suite **153 passed**. No device/GUI input, physical USB interruption, OS network/security change, inspection skill or new integration was used. No production-code defect was reproduced, so this change adds tests rather than new recovery policy.

| Boundary | Exercised path and observation |
| --- | --- |
| Loss/timeout/cancel after dispatch | Actual Engine -> CombinedRun -> ReplayQueue with a synthetic adapter that acknowledges one input then raises connection uncertainty/timeout or requests cancellation. One input only; scoped RECORD/STOP; remaining routes not_run; immediate retry rejected. Every pre-existing synthetic evidence file retains its SHA-256. |
| Capture cancellation | Actual capture subprocess owner with a local synthetic child replacing Tk/device code. Cancellation marker is delivered, child exits normally, final status is interrupted, no new selectable capture is published. A completed cleanup permits a new explicit command; the old command is never automatically replayed after restart. |
| Child exits without cleanup result | Real local child exits with code 7 and no proof. Admission remains unresolved; fresh API instance blocks new work; no capture is published. |
| Delayed cleanup | Real local child acknowledges cancellation but waits on a test gate. Owner remains live, progress remains in_progress, final history stays empty, overlapping start and restarted API admission are blocked. Releasing the test gate allows verified cleanup and normal exit; no hard kill is used. |
| Parent pipe disappears | Separate Python API process receives a real pipe EOF after submit. Worker receives cancellation and exits. Clean versus unconfirmed cleanup is persisted distinctly; restart permits new work only for the clean case. The old command returns recovery_required in both cases. Pre-existing synthetic files are unchanged. |

These are current POC behaviors, not an agreed product stop/skip/resume policy. The timeout case injects an exception after simulated dispatch; it does not unplug A34 or claim an actual Appium timeout. Pipe EOF models the existing native deadline/disconnect action, but the Rust timer itself is not exercised in these new tests. Cancellation marker handling uses a synthetic child, so active native Tk cancellation remains separately unverified. A permanently hung capture child has no bounded forced-termination policy: the owner may keep waiting and new work remains blocked. This is an explicit unresolved limitation, not successful resource recovery. Actual previously captured device evidence was not modified or used as test fixtures.

Reproduce the focused device-free cases from P1 with the existing environment:

```text
python -m unittest discover -s tests -p test_native_failure_boundaries.py -v
```
