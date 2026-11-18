# Python launcher and separate mock HTTP child

This joins the already tested [loopback facade](LOOPBACK-API.md) and [owned-child lifecycle](MOCK-STDIO.md). It is a synthetic Python reference launcher, not a desktop product launch or Rust/GPUI test.

## Minimum lifecycle

`HTTPChild(disposable_root)` launches `python -m integration.mock_http_child --mock-root <root>` directly without a shell. The worker uses the same mock API factory/recording registry as the stdio worker; it does not implement another inspection runner. The parent waits for a bounded, validated `mock-http-child.v1` descriptor on its private inherited stdout pipe. The descriptor contains literal 127.0.0.1, ephemeral port, generated bearer token and fixed synthetic project. Credentials are never command-line arguments, URL parameters, environment variables or intentionally persisted files. Do not log the in-memory ready descriptor.

Subsequent exchange calls use Python http.client directly (no environment proxy), bounded response reading, socket timeouts and request-correlation validation. No automatic retry occurs. Transport failure makes outcome unknown and prevents further exchanges. This synchronous reference client must run outside a UI render thread. Startup validation uses the existing cleanup/retry mechanism, including retained ownership if startup cleanup fails.

Closing the inherited input pipe requests child shutdown. The child stops the HTTP listener/active connections, cancels pending mock API jobs, waits up to one second and checks the lease. It exits 0 only if no tracked job remains pending and the lease is free; otherwise it returns 3. The parent's existing deadline can force-kill an unresponsive owned child. Exit code 0 is process/lease cleanup confirmation, **not task success**; inspect sealed results for execution state. Forced exit or a lost response never authorizes replay or automatic lease/admission reset.

An actual subprocess test exposed a close race: a socket accepted just before shutdown could begin its handler after the cancellation snapshot, delaying exit until its read timeout. The adapter now closes callbacks that start after the server has stopped. Same-process shutdown tests alone had not exposed this boundary.

## Executed tests

Three tests use a real separate Python HTTP server process and real 127.0.0.1 connections:

- Private-pipe bootstrap, request/start/progress/result flow, graceful exit, new-process token rotation, old-token HTTP rejection, durable duplicate-command recovery_required and prior-result lookup. The token is checked absent from child argv and generated fixture files; OS-wide memory/log inspection is not claimed.
- A test-only cooperative blocking executor is observed in_progress, then an incomplete HTTP connection and parent EOF trigger graceful shutdown. The socket closes, parent sees exit 0 without forced termination, and the sealed execution result says cancelled.
- Forced process termination after accepted admission followed by restart does not repeat that command. Whether the task completed before forced termination is intentionally unspecified.

The bootstrap descriptor remains in parent/child memory, and local processes with sufficient access are outside this POC isolation model. A genuine native launcher, cross-user permissions, credential storage integration, daemonization, external descendant cleanup, abrupt parent death, long-running real tools/models, real devices and Rust/GPUI integration remain unverified. No inspection skills or judgement logic were added. The tests use opaque mock skills only.

Reproduce from pocs/p4-integration with `python -m unittest discover -s tests -p test_http_child.py -v`, or use the explicit structure-only runner. All temporary child processes and listeners are closed by test cleanup.

Validation: 3 separate-process HTTP tests and all 116 structural tests passed, zero skips.
