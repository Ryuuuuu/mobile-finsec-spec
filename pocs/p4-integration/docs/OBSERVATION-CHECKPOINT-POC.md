# Synthetic observation checkpoint POC

Implements a limited exerciser of [the approved observation contract](../../../docs/spec/10-observation-checkpoints.md), using `integration/observation_poc.py` and `tests/test_observation_poc.py`. It is not connected to native GPUI, P1's actual input engine, P2 packet access, A34, a model, or any inspection skill. The earlier actual native cancellation acceptance is [separate evidence](../../p1-record-replay/docs/NATIVE-QA-QUEUE.md).

## Executed scope

The fixture-only runner consumes an approved immutable plan with route/version/hash, occurrence, stable step and checkpoint IDs. A shared in-process synthetic device slot rejects overlapping starts. Two fixed normal-UI route fixtures execute in order; each checkpoint has a distinct run/attempt/plan/check/route/step/phase-derived evidence key. This is synthetic input progression, not a real device replay claim.

Before moving to the next synthetic input, the host awaits bounded snapshot acquisition and seals an immutable QA state. Capture timeout/missing evidence/privacy exclusion/mismatch are distinct gaps. AI response is not awaited by replay: a sequential fixed fake reviewer runs as asynchronous tasks on sealed DTOs. Replay completed, review pending and finalized result are separately observable. Review timeout includes queued time and cannot extend indefinitely. The synthetic device slot is released when replay stops, even while review remains pending.

The fake reviewer is fixed code with **no supplied callback, script, model, plugin or tool interface**. Its only data argument is a frozen snapshot DTO. It does not launch a child process and is not an OS sandbox. Arbitrary reviewer objects are rejected; real reviewer capability explicitly remains unavailable. Python in-process objects are not a security boundary against hostile code. A claim that an untrusted child cannot access the filesystem/shell/device/network requires independent host isolation validation; it is not established here. No tool connection or assessment skill is added to work around this limit.

The synthetic vocabulary accepts only QA_READY/QA_SENT/QA_OTHER and bounded identifiers. Raw unknown screen text, input and packet bodies are never persisted or passed to the fake reviewer. This is a fixture restriction, not a general privacy redactor. No sensitive original screenshot/packet is collected. Observation results remain inconclusive/observation-only with enforcement_verified=false; this POC contains no security judgement implementation.

Rows retain each check/route/occurrence separately. Missing evidence for one of two required routes yields 1/2 route coverage with its reason. A successful row never fills another row. Duplicate events retain one object; conflicting content under the same key is rejected. Explicit rerun generates a fresh attempt and new evidence. Cancellation keeps sealed files and leaves subsequent route checkpoints not reached. Post-finalization review replies append a late-response event without changing result.json. Event persistence failure stops replay; final result publication uses a flushed temporary file followed by rename. This does not establish crash-atomic filesystem/database transactions.

## Validation and reproduction

From P4 with the existing Python environment:

```text
python -m unittest discover -s tests -p test_observation_poc.py -v
python scripts/run_structure_tests.py
```

Focused cases cover two-route isolation and input order; frozen evidence; duplicate versus new attempts and late replies; 1/2 coverage; mismatch versus not reached; fake review timeout while replay and device-slot release finish first; bounded pre-input capture; capture timeout; cancellation preservation; synthetic private-marker exclusion; unsupported real reviewer rejection; plan/version mismatch; overlapping start and explicit rerun; event and final-publication failures; fake review error separate from replay success. All files are disposable synthetic fixtures. No inspection-content correctness is tested.

Validation on Windows/Python 3.12: final focused suite **13/13 passed (0.553s)**. The structural suite ran **167 tests: 165 passed, 2 skipped (38.812s)** before the final focused-only change separating route content hash from selection occurrence. That change also added an explicit repeated-route regression and passed all 13 focused tests; a new whole-suite count is not claimed. The two skipped existing TLS/WSS handoff cases require OpenSSL or ephemeral-PKI dependencies absent from the P4 environment. This run does not count them as protocol validation. Initial restricted-shell asyncio execution stalled and was stopped by its exact owned process IDs; the reported runs completed in the approved normal execution environment.

## Decisions and remaining gaps

- **Nonblocking means no AI response wait**, not skipping the time boundary of evidence acquisition. Short bounded acquisition happens before the next screen-changing input. Timeout is recorded instead of labeling a later screen as earlier evidence.
- The prototype supports only before_dispatch and after_postcondition QA state checkpoints, already-resolved applicable routes, and fixed capture/review limits. Unknown/not-applicable planning UI, route_end, byte/queue backpressure, full manifests, real durable restart reconciliation and real process cancellation remain unimplemented. Unsupported plan phases are rejected rather than claimed successful.
- Real child isolation is a blocker for executable reviewer integration. Recommendation: keep that capability unavailable until a separately approved host isolation test proves the restriction. Alternative is to keep this data-only fake reviewer for structural tests; do not treat an ordinary Python subprocess as isolated.
- Capture/storage calls here model cooperative bounded operations; an OS filesystem call that never returns is not proven bounded. A permanently hung real child and its recovery policy remain unresolved, as in the existing native recorder POC.
- No review/replay/assessment product policy was silently generalized: this fixture retains the existing stop-on-input-failure/cancel behavior; read-only observation gaps alone do not stop subsequent synthetic inputs. All final verdicts in this exercise remain inconclusive, including complete observational coverage.
