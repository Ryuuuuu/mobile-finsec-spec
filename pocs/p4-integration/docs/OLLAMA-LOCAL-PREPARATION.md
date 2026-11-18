# Ollama loopback HTTP adapter preparation

## Contract and chosen boundary

The [official Ollama generate API](https://docs.ollama.com/api/generate) documents POST `/api/generate`, model/prompt, `format: "json"`, `stream: false`, and a final response with model/response/done. `integration/ollama_http.py` implements a deliberately limited non-streaming HTTP transport for that contract using Python stdlib asyncio. No model package installation, download, authentication, or inference was performed. The tests use a newly created local mock server, not an existing service.

This is **not registered in Supervisor**. Its current admission contract requires cooperative cancellation and streaming; this adapter honestly reports both unsupported. Relabeling it fake_cooperative would conceal remote cancellation uncertainty. Main/item execution remains on existing fake providers. This step prepares transport; it does not demonstrate end-to-end model orchestration or tool execution.

## Network and output boundaries

- Constructor accepts only a port and finite timeout. Destination is hard-coded numeric `127.0.0.1`, path `/api/generate`. No DNS, arbitrary URL, redirects, proxy environment, Authorization header, credentials or environment secrets.
- Prompt is at most 8 KiB; model identifier is bounded and cannot contain path separators/header injection. Names containing `cloud` are rejected. This is only a guard, not proof of local inference: a local server can itself forward requests. Before any future real-model trial, independently verify server ownership, configuration, installed local model and absence of cloud forwarding. This task contacted only the test's own loopback server.
- Total connect/write/header/body deadline is configurable 0.01–60 seconds. Header 8 KiB, body 64 KiB. Requires HTTP 200, JSON content type, a single Content-Length and complete bounded body. Duplicate headers/JSON keys, nonfinite numbers, malformed/truncated output and wrong model/done are rejected.
- Chunked encoding, SSE, NDJSON streaming, tool calls, model-name alias reconciliation and remote job discovery/cancel are unsupported. Real server versions may use different framing or canonical names. Fail closed; compatibility has not been established with an installed Ollama server.
- Proposal is an untrusted JSON dictionary returned to the caller. It is not executed, treated as a security verdict, or logged by this module. Future integration must apply existing immutable plan/tool-gateway validation. Raw model text, prompt, HTTP error body and exception strings are absent from status/error metadata; callers must not automatically publish proposal contents.

## Uncertainty and retries

Single active request per instance; concurrent submission returns not_run. Before writing request bytes the adapter marks possible submission. Any subsequent cancellation, timeout, HTTP/protocol failure or connection loss returns unknown and sets `recovery_required`. No automatic retry follows. Late mock completion does not clear that flag. Closing the local TCP connection does not prove model generation stopped. Cancellation is reported as local only with remote termination unconfirmed.

The recovery flag is **in-memory transport state**, not durable Supervisor lease/quarantine. Recreating the adapter could bypass it, so production use must first connect uncertainty to the persistent lease and explicit reconciliation. There is no reset/retry endpoint here. Pre-connection failure is not_run; no work admission is inferred. Even HTTP errors are conservatively treated as uncertain after possible submission.

## Reproducible device-free validation

From `pocs/p4-integration` using the existing P4 venv:

```powershell
python -m unittest discover -s tests -p test_ollama_http.py -v
python -m unittest discover -s tests -v
```

The mock binds only 127.0.0.1 on an ephemeral port. Tests validate exact request fields, a bounded structured response, refusal, busy suppression, timeout, local cancellation, no retry after uncertain results, redirects/errors, malformed/incomplete/oversize bodies, unsupported chunked framing, wrong model/done, duplicate keys and nonfinite numbers, invalid model/prompt/port, and private error sentinel redaction. These are real loopback TCP exchanges with simulated model responses. They do not establish actual model quality, latency, cancellation support or real server compatibility.

Initial sandbox execution stalled in Python's asyncio socketpair construction before adapter execution. A diagnostic with an 8-second watchdog identified that location. Authorized loopback-only execution outside that restriction passed; no firewall/security setting was changed. Tests retain an explicit bounded mock shutdown and do not use an existing local model endpoint.

Remaining acceptance gates: actual locally installed server/version/model verification, framing compatibility, structured proposal schema and scope validation, durable uncertainty ownership across restarts, orphan reconciliation and provider-neutral job handle, then separately authorized main/item integration. No actual model success is claimed.

Validation on Windows/Python 3.12.10: full P4 suite 142 tests, 141 passed and 1 existing Windows symlink-privilege skip. All 6 local HTTP tests passed, including a final rerun after bounding mock server shutdown. Private full-suite log is retained outside Git.
