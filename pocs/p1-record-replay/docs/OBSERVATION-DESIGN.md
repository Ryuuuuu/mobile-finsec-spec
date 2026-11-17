# Proposal: independent device observation and guarded app input

Status: design proposal, not an implemented scrcpy integration. Current P1 preview is an Appium screenshot/source poll guarded by selected-package foreground checks. It cannot show the launcher before the target opens or what replaces it after exit. This is appropriate for preventing input into another app, but insufficient for diagnosing lifecycle transitions. Removing the input foreground guard is not the solution.

## Separate three lifecycles

1. **Device viewer:** start before target launch and remain alive after target exit and Appium disconnect. Prototype as a separate official scrcpy process/window: `scrcpy --serial YOUR_SERIAL --no-control --no-audio`. Do not enable file recording by default. The official [control documentation](https://github.com/Genymobile/scrcpy/blob/master/doc/control.md) describes read-only mode, and [audio documentation](https://github.com/Genymobile/scrcpy/blob/master/doc/audio.md) documents disabling audio. Validate behavior on the actual pinned build before claiming integration compatibility. Appium helper policies are not a prerequisite for starting this independent viewer.
2. **Target observer:** start before the launch request; collect target process identity, foreground changes and available exit evidence independently of the input session. Emit timestamped observations rather than input commands. Restrict stored information to the selected target; unexpected foreground should be a boolean/category by default, not an inventory of the user's apps.
3. **Input recorder/replayer:** retain the device lease, package/build checks, explicit initial state, unique selectors, geometry checks, intent-before-dispatch journal and no automatic uncertain-input retries. Foreground loss immediately disables input and marks an active route incomplete, while the device viewer and observer continue. Never translate clicks on the independent viewer into unrecorded input.

Use separate status fields: viewer connected/frame age, target foreground/process state, and input session/recording state. A stale or disconnected stream must not look like a live frozen target. Show a stale-frame timestamp/overlay and invalidate all input mapping. Read-only viewing and input ownership are separate permissions. Closing the input session restores its temporary policies without killing an explicitly active viewer; closing the whole project stops only its owned processes.

## What can be concluded from exit observations

Record the launch request, launch acknowledgement, foreground transition, process observed/not observed, session errors and exit evidence on one timeline. A process check must account for multiple processes, PID reuse and app restart; absence of one PID is not proof that the entire app exited. Sampling may miss short-lived transitions. ADB connection loss is an observation gap, not an application crash.

Android's [ApplicationExitInfo](https://developer.android.com/reference/android/app/ApplicationExitInfo) distinguishes categories such as Java/native crash, ANR, self-exit, low-memory and user-requested termination. [Historical exit records](https://developer.android.com/reference/android/app/ActivityManager#getHistoricalProcessExitReasons(java.lang.String,int,int)) are bounded and access-controlled; another UID's history requires DUMP permission. Probe the authorized shell's available diagnostics without granting new privileges or installing invasive instrumentation. Unavailable records remain unknown.

**An app disappearing, black frames, a lost Appium session or an exit code does not establish security-tool detection.** Report observed exit/foreground loss and corroborating evidence separately from hypotheses. Claim detection only when explicit authorized evidence supports it. Do not evade checks to force the app to run. Record diagnostic interventions (including our own force-stop/reset) so they are not misclassified as spontaneous exits.

## Capture and privacy boundaries

Whole-device display may expose notifications, the home screen or another app. Offer a clearly labeled, user-enabled observation mode, no automatic persistence, and an immediate pause/hide action. Separate display consent from file-recording consent; the official [recording options](https://github.com/Genymobile/scrcpy/blob/master/doc/recording.md) must remain off unless explicitly chosen. Keep optional evidence local and private. No broad unfiltered logcat upload.

Protected app surfaces may remain blank. Do not promise scrcpy can show FLAG_SECURE content, bypass capture protection, root the device or change verification/hidden policies to improve visibility. If protected content is required for a legitimate test, use an authorized QA build or external observation agreed with the owner. Distinguish protected pixels, transport stall and unknown black-frame cause; do not infer cause from color alone.

## Prototype acceptance before broader deployment

- Viewer starts with no Appium session and remains active across target launch, normal Back/exit, controlled force-stop, crash fixture, and Appium shutdown.
- Input stops on foreground loss even though the viewer continues; independent viewing cannot inject touches, keys or clipboard data.
- Native widgets, custom Canvas and a dedicated crash fixture produce distinct expected timelines. Add WebView/Compose/multi-display cases rather than treating one Canvas pass as broad compatibility.
- Protected capture stays protected; unplug/reconnect yields a visible observation gap and never resumes input automatically.
- Target-only lifecycle summaries contain no unrelated app names, credentials or raw private log bodies; recording stays off by default.
- Temporary Appium policy restoration and owned-process cleanup succeed independently of viewer status. Test crash/recovery paths explicitly.

Implement this in stages: read-only external viewer and lifecycle timeline first, then optionally integrate the video surface. Reusing a decoded frame for coordinate input would require an explicit display/rotation/crop transform and freshness contract; it should not be introduced implicitly with the viewer.
