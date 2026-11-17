# Proposal: independent device observation and guarded app input

Status: first-stage external read-only viewer implemented in `pc.observe`, accessible through P1's **Independent read-only observation** button. The original P1 input preview remains an Appium screenshot/source poll guarded by selected-package foreground checks. It cannot show the launcher before the target opens or what replaces it after exit; the independent viewer handles that observation. Input foreground guards remain unchanged.

## Run the first-stage implementation

Install the official Windows release following [upstream instructions](https://github.com/Genymobile/scrcpy/blob/master/doc/windows.md), verify its published SHA-256, and use its executable path. Tested distribution: scrcpy 5.0.1 win64 ZIP, SHA-256 `b12a2c4ee8be317422451fc7dcf8ee20a71b5ea7ef9ad73ddd825a25316227a5`; `scrcpy --version` matched 5.0.1. No third-party repackaging or binary is committed here.

From the P1 directory with the project venv:

```powershell
python -m pc.observe --device YOUR_SERIAL --package dev.finsec.qa.standalone --scrcpy C:\Tools\scrcpy\scrcpy.exe --adb C:\Android\platform-tools\adb.exe
# Alternatively add --scrcpy PATH when launching python -m pc.ui,
# then choose Independent read-only observation.
```

An explicit whole-device display notice appears before starting. The viewer runs without Appium, with `--no-control --no-audio`, no recording flag, and the configured ADB binary. A separate observation panel shows sampled target process count, foreground yes/no/unknown, observation age and a bounded in-memory timeline. Unrelated package names and raw ADB output are not displayed or saved. Hide/stop kills only the owned scrcpy process; restart is manual. Closing this panel stops its viewer. Closing P1 input leaves the independently opened panel alive; the user must close it separately.

**The scrcpy screen is observation-only: clicking it neither operates the phone nor records a route.** Recorded input still uses the original P1 canvas and its guarded Appium session. Direct operation plus recording on the continuous mirror remains unimplemented.

The external viewer does not report decoded-frame timestamps to Python: its process-alive state is explicitly labeled **pixel freshness unknown**. Observation age describes ADB samples, not video freshness. PID changes are observations, not durable process identities or proven crashes; PID reuse/short events can be missed. Historical exit-reason collection, crash fixtures, integrated stale-frame overlays, WebView/Compose and reconnect testing remain follow-up work. No security-detection conclusion is generated.

## Device validation of this stage

On the authorized Android device, with only the two disposable QA apps:

- Before the selected native app was launched, the external viewer displayed the other Canvas QA app; target observation reported zero processes and not foreground.
- Launching native QA updated the same viewer to its native widgets and the observer to one process/foreground. A click on the read-only Canvas view did not advance its state.
- Controlled target force-stop left the viewer displaying the other QA app and target observation returned to zero/not foreground. Back in this fixture resets local state rather than exiting, so it was not counted as normal-exit acceptance.
- An authorized Appium session opened while the viewer remained visible. After session DELETE and shutdown of the owned Appium server, switching from native to Canvas produced a fresh visible screen in the same scrcpy window. This verifies continued display, not merely a surviving process.
- Hide/stop and manual restart worked. Closing the independent observation panel removed its owned scrcpy window. No recording was enabled and no real banking screen was used.

The user explicitly requested retention of the approved test-device settings after this run. Final readback was hidden API policies `1/1/1` and helper mock location `allow`; this run did **not** restore the earlier baseline. That local test instruction is not a new default policy for P1 or other users. The standard adapter still restores its recorded session baseline. Actual device identifiers and diagnostic evidence are excluded from this repository.

## Prepared-device handling versus per-app permission

Viewing through scrcpy required neither an Appium session nor the hidden API/mock-location changes. Those changes are device/helper state, not permissions granted independently to every tested target app.

Source review of the installed UiAutomator2 **6.0.0** found that `performSessionPreExecSetup` calls `setHiddenApiPolicy('1', ...)` for API 28+, independently of `skipDeviceInitialization`; session deletion calls `setDefaultHiddenApiPolicy`. `ignoreHiddenApiPolicyError` only changes error handling, not whether a write is attempted. `skipServerInstallation` skips helper installation checks, not the hidden API policy operation. Thus these flags alone do not establish a no-settings-write session in the tested version. No patched driver or unverified skip configuration was substituted.

A subsequent prepared-device workflow should probe driver/helper versions, installed APK identity and current policy/appops values before session creation. Show only the required changes against the selected device's approved baseline, retain approval for the explicitly authorized device/test scope, and avoid creating a new session merely for read-only viewing. Switching target apps within one long-lived session requires a separately validated target/build rebind and journal boundary; current P1 still binds one session to one target. A no-write connection mode must be demonstrated against the pinned driver's startup and teardown paths before being advertised. Never silently broaden approval to another device or permission.

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
