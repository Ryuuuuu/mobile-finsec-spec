# Content-neutral Supervisor separation

Active orchestration uses `from integration.supervisor import StructureSupervisor`. The old implementation moved unchanged to `legacy_supervisor.py`; the old `Supervisor`/`StopRun`/`Handle` names remain lazy compatibility exports for historical demos. Importing the active class does not import P3, its skills, evaluator, history validator or P2. The historical CLI is not the active structural acceptance path. Do not run it for current user-skill validation.

`StructureSupervisor(root, skill_root, executor).run(items, platform)` injects an async executor with `run(context, progress)`. Context contains only the chosen item's detached common + selected AOS/iOS opaque skill snapshot and item ID. The default MockExecutor returns execution completion, not a security verdict. No skill instructions, assessment tool choices or judgement rules are created/interpreted. Results have no verdict field.

All selected skills load before any executor starts. Missing common or selected platform file is `not_run/SKILL_LOAD_FAILED`, not an executed check failure. The executor runs sequentially, after an exclusive shared SQLite synthetic-device lease and fenced attempt authorization. `mock.execute` is a separate allowed lease operation requiring an active attempt. Successful item cleanup rotates the generation before the next item. Same-root supervisors cannot concurrently own the modeled device; this is not physical A34 or multi-device scheduling.

A completed reply must exactly equal `{"execution_status":"completed"}`. Exception, unexpected termination/None and invalid reply fail the current item. A total item deadline and last-progress deadline separately monitor hang; repeated progress does not bypass the total deadline. Cancellation records cancelled. Subsequent items remain not_run, previous completed rows remain completed. Raw exception text is not saved. Mock progress is cooperative, not proof a malicious worker is healthy; blocking the event loop or OS process termination is outside this POC.

Cleanup cancels owned work, waits 50 ms, and retains durable recovery ownership if work survives. Another supervisor sharing that lease stays blocked even after late task completion. There is no automatic retry, ownership stealing or reconciliation. These tests validate cooperative asyncio tasks and SQLite persistence across supervisor instances, not an OS reboot or remote model termination. Ollama is not connected to this executor interface because its cancellation uncertainty still needs durable integration.

Each run records ordered lifecycle events and per-item execution states in a private `result.json` through a temporary file + rename. It excludes skill bodies, model output and verdicts. Storage failure raises and is not a persisted success; there is no history database or full fsync/power-loss transaction guarantee in this structural path. Record integrity/signature validation and immutable content-addressed skill persistence remain separate work. The record tracks roles, not user skill content.

## Validation and reproducibility

From `pocs/p4-integration`, run unittest discovery for `test_structure_supervisor.py`, `test_skill_structure.py`, `test_ollama_http.py`, `test_providers.py`, `test_lease.py`. Do not run the historical P3-backed suite as current acceptance. All skills are generated temporary opaque mock text; no device or actual model is contacted.

Seven new async tests cover common-only/AOS/iOS delivery and sequential completion, missing selected skill, exception/unexpected exit/hang with retained prior completion and omitted follow-ups, total deadline despite progress, same-device exclusion across two supervisors, external cancellation, and durable recovery after cancellation-resistant work. A discovered lease-acquire `None` handling defect was corrected: busy/recovery now yields not_run rather than a generic execution failure. The stalled initial failure test was stopped; the corrected run passed.

Future product work: formal provider-neutral executor/job contracts, stream-based progress/liveness, durable model uncertainty ownership, content-neutral GUI/history validation, bounded process isolation and multi-device registry. User-authored check skills and their tools/verdict rules remain outside this scope.

Final validation: 47 selected structural tests passed, zero skips on Windows/Python 3.12.10. Fresh-process import verification confirmed no os_tamper, p3_adapter or legacy_supervisor module was loaded by StructureSupervisor. 109 traceability links resolve. The old judgement suite was not executed.

The [recording reference contract](RECORDING-CONTEXT.md) adds common-ID P1 route/P2 packet metadata to each mock item context and saved result. It preserves missing/incomplete data independently of execution status; no real artifact reader or replay is enabled.
