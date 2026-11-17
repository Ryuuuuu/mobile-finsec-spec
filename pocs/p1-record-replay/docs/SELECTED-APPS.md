# Selected installed-app QA (route v2)

P1 now accepts an explicitly selected installed Android package. This supersedes the synthetic-only target restriction in the original execution specification. The synthetic `dev.finsec.poc` workflow and v1 routes remain supported. This is not a promise that every app or screen is automatable.

## Run

From the P1 root, with the existing Python venv and ADB on PATH:

```powershell
python -m pc.ui --device YOUR_SERIAL --list-apps
python -m pc.ui --device YOUR_SERIAL --package org.example.qa --launch-only
python -m pc.ui --device YOUR_SERIAL --package org.example.qa --output C:\private-p1-runs
```

Choose the package at startup; restart the GUI to switch targets. `--list-apps` lists user-installed packages, not labels. System packages can be specified directly. Launcher resolution uses Android's MAIN/LAUNCHER resolver for the selected package and current user. Missing, disabled, foreign-package or ambiguous resolver results fail closed. The launcher may redirect to another activity in the same package. `--launch-only` opens no Appium session and reports start acknowledgement, not visual screen or authentication success.

The GUI's Launch button uses ADB without reset. Connect first reads package metadata, all installed APK hashes, launcher and security baseline. Before any session creation, a separate confirmation describes helper installation, three hidden API policy changes, mock-location permission and in-memory preview. Declining creates no session. A baseline JSON is saved locally before proceeding. Normal close restores and reads back the three policies and helper permission. Helper APK installation is not rolled back. Failed cleanup keeps the lease quarantine: stop Appium, inspect the saved baseline and recover manually before another run. Crash, disconnect or unknown session-creation outcome cannot guarantee automatic restoration; no automatic retry is attempted.

No general-app reset, reinstall, clear-data or FLAG_SECURE toggle is provided. Appium uses `noReset=true`, `forceAppLaunch=false`, and general apps use `autoLaunch=false`. This preserves existing data during setup, but actions the user records/replays can change app and server data. Use an authorized test account and reversible scenario, and review every route before replay. Do not use real banking login or financial transactions as an acceptance fixture.

## Record and replay

1. Launch the app explicitly and connect after reviewing the preflight. Arrange the starting state manually.
2. Select a full resource ID from the observed hierarchy (or type it) in **Initial at RECORD / next action postcondition**. Optionally enter its exact expected text. Press RECORD; this condition must be observed before input is enabled.
3. Before each tap/back/wait, set the expected resulting condition. Click the PC preview, or use Back / Wait. Physical phone touches are not recorded.
4. For text, choose a full target resource ID and non-secret test literal. The GUI confirms local plaintext storage. Password-marked or unobservable password attributes are rejected before intent is persisted. This is a field-type check, not a general sensitive-data detector: never enter secrets in other fields or checkpoints.
5. STOP saves a complete route only after successful actions. Cancel, ambiguous selectors, missing conditions or uncertain transport leave an incomplete run which cannot replay.
6. Manually restore the recorded initial state before **each** replay. Review the route and confirm its effects. Device, selected package, version, every base/split APK hash and initial condition must match. A mismatch sends no input; remaining steps are `not_run`. Each dispatched step still requires its postcondition.

General route v2 retains the v1 action grammar and bounds, but has the selected `package_id`, `secure: "unknown"`, a user-declared `initial`, and target `apk_sha256s` mapping APK basenames to SHA-256 values. v1 remains fixture-only. Resource IDs belong to the selected package or Android; other namespaces, accessibility-only selectors, WebView contexts and apps without a unique launcher are not supported. Package/APK identity is not proof that server-side state or account identity is unchanged.

## Observation, privacy and failure boundaries

General mode saves no screenshot/XML evidence. Preview still reads them in memory; route and journal files contain device identity, resource IDs, entered text and checkpoint text in plaintext. Keep the output directory private and outside Git. Error messages can also contain app-provided text. Avoid sensitive screens entirely. There is no recording redaction guarantee.

FLAG_SECURE and other screenshot restrictions are never bypassed. Black pixels are not classified automatically. A screenshot response does not prove usable app content. The GUI clears stale mappings on capture error or foreground loss. ID-based steps can work when pixels are restricted if the hierarchy and conditions are available; this does not establish visual correctness. Coordinate input requires explicit CLI opt-in, visible-frame confirmation, exact geometry and a maximum of three fallbacks. It must not be used on protected/blank frames. Rotation, display mismatch or missing mapping blocks coordinate input.

No automatic permission/terms-dialog acceptance, login handling, network interception or retries of uncertain inputs. Interruptions by another package pause the preview and fail active work. Stop and inspect the device when locks, RSA, permission or terms screens need human attention.

## Validation and remaining acceptance work

Automated tests cover fixture v1 regression, v2 round trip, no saved general evidence, target mismatch, split APK changes, initial-condition requirement, resource namespaces, password rejection before intent, capture failure, foreground loss, disconnect, dynamic/missing launcher, launch failure, no-reset/no-autolaunch capabilities, security approval gating and restoration verification. Existing tests cover geometry, duplicate selectors, disk failure, cancellation, ordering, GUI busy/held-frame behavior and Tk shutdown. These use non-sensitive doubles and a local W3C HTTP server; they are not device acceptance evidence.

Real banking app verification is limited to installed package, resolved launcher and ADB launch/foreground acknowledgement. No banking login, transaction, screen/XML capture or record/replay acceptance is performed. General-app GUI/device acceptance remains necessary on authorized disposable apps: multiple launchers/profiles, launcher redirects, split updates, custom canvases/WebViews, keyboard/dialog transitions, background interruptions, rotation, lock/disconnect, protected screenshots, permission-denied helper setup and crash recovery. Record results separately as passed/failed/not run. Production design still needs explicit account/environment identity, transactional reset fixtures, secret handling, context-aware selectors and durable recovery across crashes; a resource checkpoint alone cannot prove those properties.
