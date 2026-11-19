# Explicit applicability reporting — synthetic Plan v2

At `abeb017`, finalization obtained both selected checks and expected route occurrences only from checkpoint rows. An applicable selected occurrence without a checkpoint could therefore disappear from coverage. This additive reporting mode implements the existing [applicability specification](../../../docs/spec/10-observation-checkpoints.md) without changing input dispatch or review-worker behavior.

## Bounded input and validation

Opt in with `Plan(schema_version=2, selected_check_ids=(...), applicability=(Applicability(...), ...))`. Existing `Route` and `Checkpoint` identifiers remain unchanged. A frozen `Applicability` cell identifies `check_id`, `recording_id`, zero-based `occurrence`, `status`, and `reason`; its route version/hash is bound by the containing immutable plan. The complete Cartesian matrix is mandatory, including unknown and excluded selections.

Limits: 1–10 selected checks, 1–10 route occurrences, at most 100 cells, 0–100 checkpoints, and existing 1–20 explicit steps per route. Only these synthetic reason pairs are accepted:

| Status | Reason code | Applicable denominator |
|---|---|---|
| `applicable` | `QA_REQUIRED` | Included |
| `not_applicable` | `QA_NOT_APPLICABLE` | Excluded, separately visible |
| `unknown` | `QA_SCOPE_UNKNOWN` | Excluded, separately visible |

Free-text reasons, incomplete/duplicate matrices, foreign selections, mutable matrix containers, duplicate check selections, and checkpoints for unknown/excluded/unselected checks are rejected before creating a run directory. Changing applicability changes the approved plan hash. These are fixture codes, not inspection logic or automatic applicability decisions.

## Reporting only

Finalization derives each check's denominator from applicable cells, independently of checkpoints. For an applicable cell with no checkpoint it appends `row_kind=applicability_gap`, `collection/reason=PLAN_CHECKPOINT_MISSING`, `review=NOT_REVIEWED`, no evidence, and `verdict=inconclusive`. The row includes check/recording/version/hash/occurrence but has null checkpoint/step/phase/expected fields. It is never inserted into the engine checkpoint map, replay actions, capture calls or review tasks. Existing explicit route steps are replayed unchanged; no missing action is invented.

Unknown/excluded cells similarly remain as `APPLICABILITY_UNKNOWN` / `NOT_APPLICABLE` rows with their bounded applicability reason. Final `applicability[]` preserves every validated cell. Check summaries separately expose `routes_unknown` and `routes_not_applicable`; 0 applicable routes yields 0/0, always inconclusive, never a pass. Existing checkpoints with missing evidence retain `EVIDENCE_INSUFFICIENT`; unreached checkpoints retain their replay-status reason. A plan omission remains a plan omission even if replay is cancelled.

## Compatibility

V1 remains the default for all existing fixture, bridge, CLI and GPUI callers. Its canonical plan hash explicitly omits the new empty fields, preserving prior approvals and evidence identities; it rejects attempts to silently supply applicability in v1. Its result contract remains `synthetic-observation.v1`, including its historical checkpoint-derived coverage limitation. V2 explicitly emits `synthetic-observation.v2` with applicability reporting; consumers must opt in and handle report-only/null-step rows. No existing caller was silently migrated. **GPUI does not render this new mode yet and was not opened or tested in this pass.** Existing v1 UI contract tests do not establish v2 UI support.

## Focused synthetic verification

From P4, run `python -m unittest discover -s tests -p test_observation_applicability.py -v`. Regressions cover:

- The same recording/version selected twice, first evidence only: omitted second checkpoint gives 1/2 with `PLAN_CHECKPOINT_MISSING`; a present second checkpoint with failed capture gives 1/2 with `EVIDENCE_INSUFFICIENT`.
- An entirely checkpoint-free selected check stays visible with 0/2; no extra worker is created.
- Unknown and not-applicable rows remain visible independently of the applicable denominator.
- Invalid/duplicate/incomplete/out-of-scope/contradictory matrices fail before result storage.
- Cancellation preserves the missing-plan gap separately from unreached steps; v1 hash/result compatibility and changed-plan approval rejection remain intact.

No phone, real app, capture, model, inspection skill, setup change, UI or external service is involved. Fixtures use temporary local storage and fake review only. Power-loss durability, restarted-run reconstruction, real applicability reasoning, production schema migration and v2 rendering remain outside this bounded reporting change.

Windows/Python focused results: v2 applicability **6/6 passed (0.107s)**; existing observation **17/17 (0.747s)**; existing P1 bridge with fake peers **5/5 (2.643s)**; existing Python UI/child contract **2/2 (8.168s)**. The final v2-only validation/summary refinements reran the six applicability tests, including v1 compatibility. No broad structural suite, Rust build, UI or real-device success is claimed for this pass. `git diff --check` passed.
