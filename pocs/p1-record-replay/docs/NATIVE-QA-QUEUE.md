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
