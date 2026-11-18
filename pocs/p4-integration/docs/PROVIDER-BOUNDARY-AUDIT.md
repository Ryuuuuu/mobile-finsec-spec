# Provider boundary audit and device-free validation

## Available execution path

This workstation check found no `ollama`, `llama-server`, `lms`, `codex`, or `claude` executable on the current PATH and no running Ollama/llama-server/LM Studio process. Available connector tools do not expose an arbitrary text-model inference endpoint. This is a scoped availability check, not a claim that every filesystem location was searched. No credentials were read, no authentication was initiated, no model downloaded, and no paid API called.

P4 currently admits only `fake-a` and `fake-b`. Both names select the **same FakeProvider implementation**. Passing both is a configuration/contract test, not independent provider compatibility. The Provider protocol also returns a FakeJob containing an asyncio task, heartbeat/progress fields and local cancellation state. Provider construction accepts simulation-specific behavior/delay arguments. A real provider cannot be safely enabled merely by changing its name or supplying an API key.

## Confirmed defect and correction

The existing watchdog bounded active jobs, but awaited `start_job` and `get_result` directly. Either async RPC could hang indefinitely before/after the watched task. Both calls now run as tracked tasks through the supervisor watchdog. The existing tool timeout bounds each RPC, and run/item deadlines and cancellation still apply. Error codes distinguish role and phase, for example `MAIN_START_TIMEOUT` and `ITEM_RESULT_TIMEOUT`.

Each boundary emits `provider_call_started`, then `provider_call_finished` or `provider_call_stopped` with role, phase and fixed reason code. Provider exception text is not copied into logs. On uncertain start failure, the lease requires explicit recovery: work could have been admitted without returning its handle. No automatic retry is performed. Result retrieval failure stops remaining items; known tracked work is cleaned up before lease release.

## Sequential execution and retry policy

The main proposal must exactly match selected items. Each item runs only after the previous item has completed tool execution and cleanup. Provider proposals do not execute tools directly. Existing generation/attempt fencing and evidence validation remain unchanged.

Repeated identical command IDs within the same supervisor return the original handle, including a terminal failure; changed payloads conflict. A different command is a new run, not a resumable retry, and cannot pass a retained recovery lease. This in-memory deduplication does not promise cross-process exactly-once admission. Automatic retry/backoff and checkpoint resume are **not implemented**. Introducing them requires provider idempotency keys, a durable attempt budget, transient-vs-ambiguous error classification, cancellation confirmation and a policy excluding already-executed tools.

## Remaining real-provider design work

- Separate a transport-neutral job handle from FakeJob/asyncio task internals; introduce a registry with per-provider capability and model snapshots.
- Keep capability lookup/adapter construction nonblocking; isolate synchronous blocking code outside the event loop.
- Bound remote event-stream shutdown, validate stream failures and schemas, and define heartbeat versus model progress semantics. The cooperative fake stream is not proof that an arbitrary hostile adapter can be stopped.
- Provide remote cancellation acknowledgement and orphan-job reconciliation. A local wrapper being cancelled does not prove remote work terminated.
- Define bounded, redacted model-event logging and durable replay. Existing event files are local synthetic lifecycle records, not an unrestricted raw model transcript.
- Verify authentication, rate limits, structured tool output, cost controls and real transport errors in separately authorized real-provider acceptance.

## Validation

Five added tests cover stalled main/item starts and main/item result retrieval, no implicit retry, recovery blocking after uncertain admission, main-before-items ordering, both fake configurations, and persisted event order/content. They execute real Python tasks and local relay/storage with injected provider faults; no actual model, device, or security verdict is established.

Full-suite result is recorded after completion below. Private logs remain outside Git.

Windows Python 3.12.10 regression: **133 tests run, 132 passed, 1 skipped**. The skipped test requires Windows symlink privilege; no security setting was changed. Five new boundary tests all passed. Command: `python -m unittest discover -s tests -v`.
