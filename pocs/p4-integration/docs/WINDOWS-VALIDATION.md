# Windows device-free execution validation

Environment: Windows 11, Python 3.12.10, dedicated venv with the existing P4 requirements (jsonschema 4.26.0, websockets 16.0). No Android, ADB, Appium, phone approval, security setting, or external model API was used during this work.

## Regression

`python -m unittest discover -s tests -v`: **128 run, 127 passed, 1 skipped**. The skip is real symlink creation rejected by Windows error 1314; outside-run evidence rejection still executes in a separate test. No additional privilege was enabled.

Two production portability defects were reproduced and corrected: locale-default cp949 decoding of UTF-8 final snapshots, and unclosed SQLite history connections that locked temporary workspaces on Windows. A connection-lifetime regression verifies closed handles after both successful reads and SQL errors. Test-only DB handles are also explicitly closed. The short injected timeout fixture was adjusted to reach the intended item timeout rather than occasionally timing out P2 preparation; production deadlines are unchanged.

## Actual local CLI executions

Each scenario ran in a new workspace through a separate `python -m integration demo` process. Each sealed result was then read by a separate `history` process and checked by a separate `validate` process. All **10 history reads returned exactly one final result; all 10 validations returned valid**.

| Scenario | Terminal state | Exit | Reason | Recovery required |
|---|---|---:|---|---|
| normal | completed | 0 | RUN_COMPLETED | no |
| proxy-off | completed | 0 | RUN_COMPLETED | no |
| main-error | failed | 2 | MAIN_ERROR | no |
| main-hang | failed | 3 | MAIN_HANG | no |
| item-hang | failed | 3 | ITEM_HANG | no |
| tool-timeout | failed | 3 | TOOL_TIMEOUT | no |
| cancel | cancelled | 4 | RUN_CANCELLED | no |
| ignored-cancel | cancelled | 4 | RUN_CANCELLED | yes |
| cleanup-failed | failed | 2 | CLEANUP_FAILED | yes |
| disconnect | failed | 2 | DEVICE_DISCONNECTED | yes |

Normal and proxy-off each retained fixture verdict counts pass=1, fail=1, inconclusive=1. Cleanup failure preserved the completed fixture fail and marked the remaining item inconclusive. Other injected failures/cancellations produced two inconclusive rows. Expected nonzero fault exits are successful fault-handling checks, not successful security checks.

## Evidence boundary and remaining work

The CLI, supervisor, SQLite history, local P2 loopback HTTP relay/storage and P3 synthetic engine are real executed code. Provider behavior is fake-a/fake-b; CHK-07 pass/fail/inconclusive are fixture variants. Disconnect, cancellation refusal and cleanup failure are injected scenarios. This is **not real model inference, actual USB disconnection, Android OS attestation, general app traffic attribution, P1/P2 GUI integration, or HTTPS/WSS acceptance through P4**. P3's separate read-only Android probe is not wired into this supervisor.

Private runtime JSON/SQLite output remains outside Git. Only source, tests and this sanitized result summary are published. Next acceptance stages require a real provider adapter with bounded cancellation/tool contracts and an explicitly authorized device adapter path; this run establishes neither.
