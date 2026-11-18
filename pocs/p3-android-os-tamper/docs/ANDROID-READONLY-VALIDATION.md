# Android read-only extension validation

## Implemented scope

The new android_probe module follows android.readonly.v1. It reuses P1's cross-process device lease, never clears quarantine, accepts no arbitrary shell command, bounds each ADB invocation to five seconds, retains at most 4 KiB per observation, and omits serials and raw ADB error text from the report. It collects only selected environment properties, shell identity, and SELinux mode. No security settings, app data, CA, proxy, bootloader state or application behavior is changed. Result paths must be new. A completed collection is always CHK-07 inconclusive; stock/tampered attestation, a protected-service oracle and causal blocking evidence remain absent.

## Windows automated verification (2026-11-18)

Python 3.12.10, dedicated P3 venv, jsonschema 4.26.0 from PyPI. `python -m unittest discover -s tests -v`: **66 run, 65 passed, 1 skipped**. The eight new tests cover the fixed command allowlist, disconnected transport, timeout/partial preservation, missing values, raw-error privacy, output reuse rejection, quarantine rejection, and output size limit. Existing synthetic contract tests remain in their own suite.

Initial Windows execution revealed existing tests relying on locale-default cp949 for UTF-8 fixtures/results. Test reads/writes now explicitly use UTF-8. The real symlink escape test is skipped only for Windows error 1314 (missing symlink privilege); no Developer Mode, admin privilege or security setting was enabled. Therefore actual Windows symlink rejection is not accepted by this run. The production synthetic engine and manifest/skill hashes are unchanged.

## Actual-device gate, not environment acceptance

A34 disconnected during the preceding P1 WSS GUI recording. P1 closed with a recovery quarantine retained; its owned Appium process was stopped. The new P3 CLI was invoked for the previously selected authorized device and correctly returned **not_run / inconclusive, zero observations**, reason `lease_unavailable_or_recovery_required`. The marker was not removed and no ADB observation command was dispatched. This verifies the real local gate, not actual Android environment collection.

Pending: reconnect/unlock the device, verify prior session termination and retained user-approved hidden API/mock-location baseline, remove only the known recovered lease markers through the existing explicit recovery procedure, then run this probe with a new private output directory. Never infer device-side cleanup while disconnected. Real property/SELinux observations and all protected-service OS tamper verdicts remain unverified. No additional device security changes are required by this read-only probe.

Supporting P1/P2 results are in the combined recording document: HTTPS real GUI record/replay passed; WSS GUI was interrupted and remains unaccepted. A separate PC-only synthetic WSS client verified the integrated TLS/websocket fixture with certificate validation and complete supported-scope network coverage; this is not an Android GUI test.
