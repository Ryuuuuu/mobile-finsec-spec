# Declarative per-check timing: synthetic matching only

Timing metadata is independent of the inspection skill body, which the user authors. A versioned `qa-observation-timing.v1` rule contains `check_id`, a condition kind (`state` or `event`), an allowlisted synthetic value, `before_dispatch`/`after_postcondition`, and required sanitized evidence (`qa_state` only). It contains no executable expression, selector, command, tool, model, raw payload or skill text.

The pure `match_timing` function accepts at most 10 frozen rules and 200 predefined QA events, with the complete validated applicability matrix and existing immutable route occurrences. Each event binds recording ID/version/hash, occurrence, explicit step, phase, synthetic state and event label. Route mismatch and duplicate event identity are rejected. Only `QA_READY/QA_SENT/QA_OTHER`, `QA_ENTER/QA_SUBMIT` and the existing two phases are accepted.

For every selected check and occurrence, zero candidates yields `UNMATCHED`, exactly one yields `MATCHED`, and multiple candidates yield `AMBIGUOUS`. Repeated screens are not resolved by choosing first/last. Unmatched/ambiguous reports have no selected step, phase or event ID; candidate count remains visible. Unknown/not-applicable applicability remains separate. The matcher returns data only; it never generates replay actions or executes a reviewer.

Preview must identify metadata version/condition/evidence and each route version, occurrence, resolved step/phase or explicit match gap. A trusted synthetic fixture may convert only uniquely matched data into observation checkpoints. No match becomes a v2 `PLAN_CHECKPOINT_MISSING` reporting gap; missing acquisition at an existing checkpoint remains `EVIDENCE_INSUFFICIENT`. Matching does not prove the observation will occur during replay. All observation verdicts remain inconclusive.

The metadata digest is included in v2 plan approval as `observation_metadata_hash`; metadata changes invalidate approval even if an existing checkpoint would remain the same. V1 omits the new field from its canonical hash and rejects nonempty metadata, preserving existing v1 approvals. Pre-metadata v2 in-memory callers default to the empty digest; serialized v2 plan rehydration/migration is not implemented. Existing finalized results are not rewritten.

Synthetic tests verify separate before/after resolution for two check IDs on the same route; independent occurrences; repeated-screen ambiguity vs unmatched; bounded scope/reason/evidence rejection; deterministic output; metadata approval invalidation. There are no real skills, UI/device actions, model requests or network operations in this matcher. This does not establish real-app matching accuracy or automatic applicability assessment.

## Independent synthetic GPUI follow-up

The observation-only Rust launcher now explicitly selects Python `--plan-mode v2`. Python API/CLI defaults remain v1; the device workspace and existing bridge are unchanged. The outer stdio request/response contract remains v1 with additive fields. The fixed v2 fixture approves a digest of rules plus matching outcomes and pins that report to the started run; loading a newer preview cannot relabel an earlier result.

| Check | Execution 1 | Execution 2 | Evidence coverage |
|---|---|---|---|
| before-check | matched before_dispatch; sealed state; fake review times out | UNMATCHED, zero candidates; PLAN_CHECKPOINT_MISSING | 1/2 |
| after-check | AMBIGUOUS, two candidates; PLAN_CHECKPOINT_MISSING | matched after_postcondition; EVIDENCE_INSUFFICIENT | 0/2 |

Internal occurrences remain 0/1; all user-facing rows use execution 1/2. Final per-check summaries replace the hard-coded mock-check summary. Report-only rows omit absent step/phase. Approved UNMATCHED versus AMBIGUOUS reasons remain separate read-only final matching rows, not fabricated checkpoints or scheduled actions. All verdicts remain inconclusive. The API's matching report is retained in memory alongside the finalized result, not embedded in the engine's saved result.json; restarted reconstruction of that metadata is not implemented.

Verification (2026-11-19): Python matching 3, applicability 6, stdio 3, observation 17, fake P1 bridge 5 tests passed. Rust focused observation tests and an explicit Rust-to-Python child pipe run passed; offline Windows binary build succeeded. The pipe checks approval/version rejection, replay completed while review pending, both coverage totals, plan/evidence gaps, and final matching metadata. These are synthetic executions, not hardware or real AI.

One bounded Windows UI pass visibly loaded both rules and four matching rows, approved and ran the fixture, and showed replay completed/finalized with before-check execution 1 evidence 1 / REVIEW_TIMEOUT and after-check execution 2 evidence 0 / EVIDENCE_INSUFFICIENT. Results clicks (including one rebind/retry) left Check visible while accessibility reads repeatedly reported unavailable. Thus the final tab and its separate Load final result button were not reached: final 1/2 versus 0/2 rendering is **not visually verified**. Source/format and actual child-pipe tests do not substitute for this remaining UI check. No navigation cause was established; no settings or installation was changed. Local run artifacts and review cases stay private.
