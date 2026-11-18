# Minimal mock loopback API

This implements the loopback adapter proposed in [native preparation](GPUI-NATIVE-PREPARATION.md), over the existing UIWire/StartAPI facade. It complements private child-process pipes: pipes test process ownership/lifecycle, while this adapter tests the planned HTTP authentication/framing contract. Neither path implements a native Rust/GPUI client.

## Interface

Construct `LoopbackAPI(UIWire(UIBridge(project_id, mock_start_api)))` on the API event loop, await start(), and await close() when finished. It always binds literal 127.0.0.1 on an ephemeral port. There is no configurable public listener, firewall change, external network request or command-line credential. Each start generates a new 32-byte random bearer secret, held only in memory and compared with constant-time comparison. Tests obtain the token directly from the adapter object. A subsequent [mock Python launcher](HTTP-CHILD-LIFECYCLE.md) tests private-pipe credential handoff to a separate HTTP child; native launcher integration remains unimplemented. This is not a packaged production service.

The only route is POST /v1/ui HTTP/1.1. Required headers: Host exactly 127.0.0.1:<port>, Authorization: Bearer <token>, X-API-Version: mock-loopback.v1, X-Request-ID (1–64 ASCII alphanumeric/underscore/hyphen), Content-Type: application/json, and numeric Content-Length. Origin requests, duplicate headers and transfer encoding are rejected. No CORS, redirects, chunking or keep-alive is provided.

The body is the existing mock-ui-request.v1 object. Replies wrap the facade payload in `{contract: mock-loopback.v1, request_id, payload}` and close the connection. A valid authenticated request ID is echoed even for body validation errors; requests rejected earlier may have null correlation. Request ID correlates transport replies, whereas the existing command_id controls durable admission/deduplication. They are not interchangeable. A lost reply has unknown execution outcome; reconnecting must not invent a new command ID or imply cancellation.

Headers are capped by an 8 KiB stream limit, request payloads by 256 KiB, and header/body reads and writes by one-second deadlines. Application payload limits remain those of UIWire (the transport envelope adds a small fixed overhead). Wrong auth returns 401, unsupported method/path/version/framing returns 400, Host/Origin rejection returns 403, oversized body returns 413. Successfully delivered facade errors use HTTP 200 with an explicit error payload; HTTP 200 never implies task success. Error text does not echo credentials, raw requests or internal exception details. Cache-Control is no-store.

close() stops listening, cancels active transport handlers, closes their connections, then waits for server closure. Testing found and corrected the opposite ordering, which waited for incomplete requests to time out first. Closing this transport does **not** cancel or reconcile already admitted tasks; the owner must separately use existing cancellation/cleanup contracts. A transport error therefore must not be represented as a completed or cancelled assessment.

## Executed evidence and limits

Five tests use actual TCP connections to 127.0.0.1 with temporary synthetic P1/P2-format artifacts and mock execution. They cover authenticated recording/start/history, request correlation, duplicate command ID returning the same execution, token rotation and old-token rejection, bad Host/Origin/auth/version, header/body limits, duplicate Content-Length, transfer encoding, missing body deadline, malformed JSON/body version and incomplete connection shutdown without admission.

The five adapter tests above run in one Python test process/event loop. Subsequent [HTTP child tests](HTTP-CHILD-LIFECYCLE.md) separately verify actual cross-process Python HTTP; neither stage verifies Rust-Python. Prior private-pipe tests separately cover actual Python child processes. Native GPUI, Rust client parsing, native launcher token delivery, TLS, hostile local-process isolation, load/concurrency limits, long-running synchronous backend operations and production shutdown orchestration remain unverified. The minimal parser is not a general-purpose HTTP server; backend work must not block its event loop. No inspection skills or judgement logic were added.

Run `python -m unittest discover -s tests -p test_loopback_api.py -v` from pocs/p4-integration, or use the explicit structural runner. No test credentials, private packet data or real device artifacts belong in Git.

Validation: 5 loopback tests and the complete 113-test structural suite passed, zero skips.
