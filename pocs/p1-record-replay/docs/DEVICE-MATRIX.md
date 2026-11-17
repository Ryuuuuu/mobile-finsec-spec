# Multi-app device acceptance matrix

The generic recorder is not certified compatible with all apps. Mock tests and one fixture pass cannot establish that. Keep device identifiers, captures, route/journal data and exact installed APK hashes private.

## Disposable apps

Build from `android` using the existing official SDK/Gradle toolchain:

```powershell
.\gradlew.bat --no-daemon -PstandaloneQa assembleDebug
# Copy app/build/outputs/apk/debug/app-debug.apk before the next build.
.\gradlew.bat --no-daemon -PstandaloneCanvas assembleDebug
```

The first is `dev.finsec.qa.standalone`: native widgets, editable non-secret draft, review, local confirmation, Back, reset, password-rejection field and capture-protection toggle. The second is `dev.finsec.qa.canvas`: a custom painted control without a target resource ID, plus an observable state label; two coordinate taps advance ready → review → done. Neither has network permission or account access. Both use `dev.finsec.qa.standalone.EntryActivity`, which deliberately differs from `.MainActivity` and exercises dynamic launcher resolution. Application/resource IDs differ between installed packages. Default builds without either flag remain `dev.finsec.poc`.

These packages are installed only when absent. Do not replace an existing package or clear existing app data without separate review. This implementation stores disposable state only in Activity memory. Use the visible reset control before each replay; do not rely on a launcher invocation resetting it. The generic recorder itself has no reset operation.

## Execution plan and evidence status

| App / UI | Normal scenario | Error/boundary scenarios | Current status |
|---|---|---|---|
| Original `dev.finsec.poc` / native synthetic v1 | Existing 10-step GUI record + 3 replays | Existing fixture regression | Previous device pass; new session not run |
| Standalone QA / native generic v2 | Text `sample QA`, review, local confirm, Back; GUI RECORD then 3 reset replays | Password rejection before intent, foreground loss, protected pixels | Installed; actual GUI 4-step recording and 3 GUI replays passed, all 12 replay postconditions passed |
| Canvas QA / custom drawing generic v2 | Explicit visible-frame opt-in; 2 coordinate taps, postconditions review/done; reset and replay | Missing visible-frame confirmation, selected-package mismatch, wrong initial checkpoint | Installed; actual GUI 2-step recording and 3 GUI replays passed, all 6 replay postconditions passed; expected rejection cases passed |
| Installed bank / real protected app | Installation, launcher, foreground acknowledgement only | No authentication, transactions, arbitrary recorded input or screenshots | ADB entry passed; visual verification and replay not run |

Before each Appium session, obtain explicit approval for temporary hidden API policy changes and helper mock-location permission. Save the baseline privately. End sessions, restore/read back settings and report failures before continuing. Do not automatically approve system permission/terms or Play Protect dialogs. Report any required user action immediately.

Run failures are evidence, not reasons to weaken protected capture or retry uncertain inputs. A generic selector failure may require resource namespace, accessibility or context support; a canvas failure may require stronger geometry/visibility contracts. WebViews, Compose semantics, multiple displays, managed profiles, device lock and real transport disconnect remain distinct unverified categories until specifically tested. A synthetic canvas does not certify compatibility with a real WebView or another bank.

For each execution, record passed/failed/not-run, GUI-recorded route provenance, postcondition outcomes, failures with undispatched tails, app state preparation and security restoration. Publish only a non-sensitive summary and resulting source/tests. Never construct a CLI route and count it as GUI recording acceptance.

## Installation preflight observation

Both disposable APKs pass `apksigner verify`; manifest minSdk is 26, targetSdk is 28, and the tested device reports API 35. Initial installs returned `INSTALL_FAILED_VERIFICATION_FAILURE`, including a retry after the user handled a prompt. Subsequent explicitly requested retries succeeded for both packages after the user handled installation confirmation. Verification was not disabled. The earlier rejection's detailed cause remains unknown; it was not a recorder compatibility result.

## Completed device acceptance and resulting fixes

Both successful routes were recorded through the PC GUI and replayed through its file-selection flow; no route was synthesized by CLI. Before each successful replay, only the relevant disposable Activity's in-memory state was reset by force-stop and launcher restart. Existing app data was not cleared. The native route has four actions; the Canvas route has two explicitly confirmed coordinate actions. All six successful replay results are `succeeded`.

Two real failures required fixes and repeat testing:

- STOP during a preview read previously requested cancellation without finalizing the recording. It now discards any undispatched queued input and queues finalization after the read; cancellation during an actual action remains conservative. The later Canvas recording finalized with one STOP click during preview polling.
- Canvas taps previously selected the non-clickable `android:id/content` ancestor and timed out without advancing the painted control. Hit testing now selects only enabled, clickable resource nodes. A Canvas tap then correctly requires explicit coordinate confirmation; native button resource selection remains intact. The failed pre-fix route remains private and is not counted as a pass.

The Canvas GUI rejected a native-package route and an unconfirmed coordinate tap. Replaying Canvas without resetting from `done` failed the initial `ready` checkpoint: result `incomplete`, both steps `not_run`, no replay inputs dispatched. This classification reflects the current timeout handling, not a completed replay.

Separate adapter/engine diagnostics (not counted as GUI recording) verified password rejection before intent/dispatch with the field unchanged, foreground-loss rejection and recovery, and native clickable selection. The disposable capture toggle produced black protected app pixels while its hierarchy remained available; switching protection OFF restored visible QA content. Protected capture was not bypassed. Diagnostic images and device evidence remain local.

All 79 automated tests passed after the two fixes. Temporary hidden API policies were restored and read back as `null` for all three keys; helper mock location returned to `default`. Disposable Activity state was reset, the native QA app returned to `ready` with capture protection OFF, and the owned Appium server was stopped. Existing synthetic-app data and real banking apps were not modified by this acceptance run.

Actual USB disconnection, wrong device geometry, WebView, Compose, multiple displays, device lock and production-bank recording remain unverified on-device. Mock coverage is not a substitute for those tests. Continuous observation before launch and after target exit is a separate current limitation; see [the independent observation proposal](OBSERVATION-DESIGN.md).
