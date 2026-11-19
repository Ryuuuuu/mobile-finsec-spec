# P1 replay boundary to synthetic observation review

Later [fixed QA state reader A34 acceptance](QA-STATE-DEVICE-VALIDATION.md) validates normal A -> B device replay with state-only fake review. The tests described below remain synthetic; that follow-up does not establish GPUI observation UI or real reviewer isolation.

Follow-up to `2cdaff7` and [the observation specification](../../../docs/spec/10-observation-checkpoints.md). This validates the **actual P1 Engine -> CombinedRun -> ReplayQueue code**, with a synthetic device adapter and a mock RECORD/STOP peer. No GPUI input, A34 operation, real packet transport, actual model or inspection skill runs in these tests.

## Minimal connection

P1 Engine has an optional trusted-host `replay_observer(action_id, phase)` boundary. It is unset by default and inactive for recording. `before_dispatch` runs after intent persistence and before input; cancellation is rechecked afterward. `after_postcondition` runs only after the existing postcondition succeeds and before the next input. It passes no action text, credentials, screenshot, packet body or device identifier to the observer. This is an internal host connection, never an agent tool interface.

`integration/p1_observation_bridge.py` attaches the boundary only for its owned queue execution and restores the previous prepare handler/unsets the observer afterward. An occupied observer is rejected. A deep copy of each actual P1 route is bound by its full source hash, schema version, stable action IDs and queue occurrence to the approved plan. Mutating even the action timeout after approval is rejected before RECORD or input. Repeated selection can retain the same source hash while its occurrence remains distinct.

At the boundary, trusted QA instrumentation reads a small allowlisted synthetic state and freezes it on the replay thread. The existing observation host seals the state before allowing the next input, with a bounded asynchronous handoff. Fixed fake reviewers consume frozen state DTOs on the event loop while P1 executes on its owner thread. P1 never waits for review completion. Real device state readers are **not provided**, and no arbitrary app/privacy-safe extraction support is claimed.

The test adapter maps its own synthetic login/menu fixture states to QA_READY/QA_SENT. It never sends its hierarchy or fake image files to the reviewer. P1 fixture journals may independently contain synthetic `fake-png` evidence from the existing test adapter; these are not actual screenshots. Observation storage retains only the approved QA state and correlation metadata. Full P1 replay IDs and separate P2 mock correlation IDs remain linked by the queue's existing result; this does not establish actual network capture.

## Observations and failure behavior

- Two actual P1 route executions occur A -> B. At the four boundaries, `(state, acknowledged input count)` is `(QA_READY,0), (QA_SENT,1)` for each reset synthetic adapter. Four distinct sealed references belong to the correct route/action/phase, before the next route can overwrite state.
- With a fake reviewer delayed past its deadline, P1 completes both routes and RECORD/STOP pairs, releases the queue guard and synthetic device slot, and restores the observer while the observation result is still review_pending. Final rows then record REVIEW_TIMEOUT. Replay completion and review finalization are not conflated.
- A synthetic observation mismatch leaves normal P1 replay successful but one route incomplete for observational coverage (1/2). It never becomes a security verdict.
- Cancellation after the first acknowledged input preserves both sealed first-route snapshots, leaves route B not_run, issues only the first route's STOP, and releases owned in-process resources. The observer is removed and all prior source/evidence bytes remain unchanged. This is cooperative simulated cancellation, not a USB interruption or real Appium cleanup claim.
- A state-reader exception records a reached checkpoint with EVIDENCE_INSUFFICIENT/HOST_ACQUISITION_ERROR, distinct from subsequent STEP_NOT_REACHED rows. The exception then follows the existing P1 failure path: no input at that before-dispatch boundary and no next route. This is a conservative host malfunction boundary, not the policy for a normal observation mismatch or missing optional field.

## Limits and design decisions still open

AI response is nonblocking; timely evidence acquisition itself is not skipped. The trusted reader must return cooperatively within its QA contract. An arbitrary host function or OS call that never returns is not made safe by a Python callback or timeout. The bridge refuses to pretend that a timed-out worker has stopped; cancellation requests queue cancellation and drains the owner before releasing attachment. The permanent-hang recovery limitation remains unresolved.

Normal mismatch/explicit capture gaps permit replay to continue; unexpected host acquisition exceptions stop through the existing P1 error path. Recommendation: preserve that distinction until a real bounded state-reader implementation can prove which failures are harmless acquisition gaps. Silently swallowing an unknown host exception would conceal an unverified boundary. This POC does not settle product skip/resume policy.

The fixed fake reviewer remains in-process and data-only. Real reviewer isolation stays unavailable, as documented in [the standalone POC](OBSERVATION-CHECKPOINT-POC.md). No device/shell/network capability is added to it. GPUI does not yet create/approve observation plans or install this bridge; the native QA recorder/replay acceptance remains a separate result. No real model, real banking app, raw data transmission, security bypass or assessment automation was added.

## Reproduction

From P4:

```text
python -m unittest discover -s tests -p test_p1_observation_bridge.py -v
python scripts/run_structure_tests.py
```

From P1, the existing full device-free suite checks the default observer-disabled behavior:

```text
python -m unittest discover -s tests -v
```

Validation (Windows/Python 3.12, 2026-11-19): P1 **153/153 passed (14.780s)**. P4 structural runner **172 tests: 170 passed, 2 skipped (33.819s)**, including all four bridge cases and thirteen standalone observation cases. The two existing TLS/WSS tests skipped because the P4 environment lacks the ephemeral-PKI dependency; no protocol success is inferred from these skips. No real device/model/GPUI run was performed for this follow-up. Actual prior private A34 evidence was not used as a fixture or modified.
