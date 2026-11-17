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
| Standalone QA / native generic v2 | Text `sample QA`, review, local confirm, Back; GUI RECORD then 3 manual-reset replays | Wrong initial checkpoint, password rejection before intent, foreground loss, protected pixels | APK build/signature passed; installation blocked by device verification; record/replay not run |
| Canvas QA / custom drawing generic v2 | Explicit visible-frame opt-in; 2 coordinate taps, postconditions review/done; reset and replay | No-coordinate mode rejection, blank/protected frame not clicked, wrong geometry, selected-package mismatch | APK build/signature passed; installation not attempted while native-app verification is blocked; record/replay not run |
| Installed bank / real protected app | Installation, launcher, foreground acknowledgement only | No authentication, transactions, arbitrary recorded input or screenshots | ADB entry passed; visual verification and replay not run |

Before each Appium session, obtain explicit approval for temporary hidden API policy changes and helper mock-location permission. Save the baseline privately. End sessions, restore/read back settings and report failures before continuing. Do not automatically approve system permission/terms or Play Protect dialogs. Report any required user action immediately.

Run failures are evidence, not reasons to weaken protected capture or retry uncertain inputs. A generic selector failure may require resource namespace, accessibility or context support; a canvas failure may require stronger geometry/visibility contracts. WebViews, Compose semantics, multiple displays, managed profiles, device lock and real transport disconnect remain distinct unverified categories until specifically tested. A synthetic canvas does not certify compatibility with a real WebView or another bank.

For each execution, record passed/failed/not-run, GUI-recorded route provenance, postcondition outcomes, failures with undispatched tails, app state preparation and security restoration. Publish only a non-sensitive summary and resulting source/tests. Never construct a CLI route and count it as GUI recording acceptance.

## Installation preflight observation

Both disposable APKs pass `apksigner verify`; manifest minSdk is 26, targetSdk is 28, and the tested device reports API 35. Native QA installation returned `INSTALL_FAILED_VERIFICATION_FAILURE` twice, including the retry after the user handled the prompt. Neither package was installed. This is a device verification rejection, not a recorder compatibility result; its detailed cause is not yet established. Do not infer signature corruption, disable verification or repeatedly submit installs. Obtain the exact phone warning and selected action before the next attempt. No Appium session or temporary policy change occurred during these attempts.
