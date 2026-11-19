# Fixed own-app instrumentation path

This is the narrow alternative to the [Appium/P2 preflight blocker](GPUI-OBSERVATION-PREVIEW.md). It introduces no inspection skills, model, proxy, raw capture, security settings or general-purpose target/command interface. Sources are in `qa-state-only/`; the host contract is `integration/qa_state_only.py`.

## Contract and limits

Android's standard `Instrumentation` starts only `dev.finsec.qa.stateonly.StateActivity`, checks its fixed `QA_READY` state, calls its one button's `performClick()` on the main thread, verifies `QA_SENT`, and finishes the activity before returning. The manifest requests no permissions. The app has no network or persistent-data code. Instrumentation accepts no selector, action, command, text, target package or URL parameter. This is an own-process UI callback test, **not physical touch injection or replay of a saved P1 route**. It cannot establish arbitrary app compatibility.

The trusted host executes exactly this argument vector, without shell interpolation:

```text
adb -s <selected-device> shell am instrument -w -r dev.finsec.qa.stateonly/dev.finsec.qa.stateonly.StateProbe
```

Only the fixed contract marker, `QA_READY>QA_SENT`, and successful instrumentation completion code are accepted. Unexpected output is discarded and returns `unverified`; no raw response/exception is returned or logged. A 15-second host timeout returns `outcome_unknown`, `cleanup=unverified`, and disables automatic retry. Host timeout does not prove the Android instrumentation stopped. Normal completion reports only `activity_finish_reported`, not a device-wide cleanup guarantee. This trusted helper is not an OS sandbox against malicious replacement code or executables.

## Verified on 2026-11-19

- Three Python contract tests passed (0.002s): exact single instrumentation command, no alternate settings/proxy command, strict output filtering, timeout/no-retry, invalid device rejected before process creation.
- Both Java sources compiled against the installed Android 35 `android.jar` using JDK 21, Java source/target 17. A system-module-path warning was emitted; there were no compilation errors. This proves source/API compatibility only.
- Read-only `pm path dev.finsec.qa.stateonly` on the connected QA device returned no installed package. No instrumentation, app install, settings write, proxy or raw capture was executed.

Reproduce contract tests from P4:

```text
python -m unittest discover -s tests -p test_qa_state_only.py -v
```

## Remaining executable preparation

Package these sources and the supplied manifest as a **new disposable APK** using the existing Android build tools: compile the Java sources against `android.jar`, convert classes with D8, package the manifest with AAPT2, add `classes.dex`, align and sign with a private local test key. Keep keys, APKs and device receipts out of Git. This packaging/signing step is not validated by the Java compilation above. Install only this distinct package, handling any user installation confirmation before continuing; do not replace existing QA apps.

After installation, the fixed host helper can run the command above and expose only its allowlisted result to a future read-only GPUI result adapter. Validate actual returned framing first; unexpected formatting must remain unverified rather than be relaxed into accepting unrelated output. Then verify activity closure and device settings before/after. GPUI display connection, approved plan/version binding, P1 route events and multi-route evidence are **not implemented by this small path** and must not be claimed from its three contract tests. Integrating them requires preserving the existing immutable plan and occurrence contracts; this probe does not silently substitute for saved-route replay.
