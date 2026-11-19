# GPUI fixed observation-plan preview POC

2026-11-19, after `b186d1f`. `gpui-smoke/src/bin/observation.rs` is a **dedicated synthetic three-tab GPUI-kit window in this existing spec repository**. It does not replace or connect observation controls to the real-device `workspace` binary. No separate product repository, device, actual model, inspection skill, agent tool permission or network listener is involved.

## Contract and minimal UI

The Check tab loads a fixed A -> B plan from a separate trusted Python child (`integration.observation_stdio`). It shows plan revision/hash, mock check ID, route/version, step, phase, expected QA state, state-only evidence and deadlines. Record contains no inspection selection. Approval sends the displayed hash to the Python owner; execution requires both a matching current plan and recorded approval. A newer fixed revision invalidates approval. The test-only Run button deliberately permits sending the last approved hash so the backend mismatch rejection is observable; this is not a recommendation for product UX.

Revision 1 is complete A/B evidence. Revision 2 deliberately omits B's evidence, while both synthetic routes replay normally. Subsequent fixed revisions alternate these fixtures; this is not a user-authored plan editor. Synthetic replay finishes independently of the fixed fake reviewer's nine-second delay and eight-second review deadline. Check displays live replay and review/finalization separately. Results explicitly loads only a finalized current run and keeps A/B rows, evidence counts, reasons and route coverage visible. All results remain observation-only/inconclusive; no control enforcement or security finding is established.

The transport reuses the existing bounded Rust Session framing with a distinct observation readiness/request/response contract and project ID. `start_observation` always selects the synthetic child even if a real QA configuration environment variable exists. It does not infer device approval from the UI plan or Computer Use permission. The child only receives closed built-in operations and hashes; it cannot receive shell commands, arbitrary scripts or device targets through this protocol.

This trusted child is not a demonstrated OS sandbox for hostile model code. The reviewer is still the fixed in-process data-only fake. Real reviewer isolation remains unavailable. UI uncertainty blocks further operations; no automatic restart/replay is added. History browsing, durable cross-process approval, user-authored plans and full GPUI workspace/device integration are outside this vertical slice.

## Actual Windows acceptance

The new app's Computer Use approval initially timed out. No screen input was performed then. After the user explicitly allowed `use observation`, the same POC window became readable and the following were verified through actual GPUI controls:

1. Before a plan/approval, execution was disabled. Loading revision 1 showed both route checkpoints and deadlines.
2. Approved revision 1. Loaded revision 2; UI displayed STALE approval/version mismatch. Sending the old approval returned PLAN_VERSION_MISMATCH with no run started.
3. Approved displayed revision 2 and executed the fixed synthetic plan through GPUI -> Rust Session -> Python.
4. Check displayed replay completed separately from review finalized and A's REVIEW_TIMEOUT versus B's EVIDENCE_INSUFFICIENT.
5. Results displayed replay completed, finalization completed, **coverage 1/2**, A evidence 1 / REVIEW_TIMEOUT, B evidence 0 / NOT_REVIEWED / EVIDENCE_INSUFFICIENT. The persisted local result matched those rows.

The transient review_pending screen was not captured before finalization during computer-use round trips. Its actual transport state (replay completed, final unavailable, then later review timeout) was independently observed by the Rust/Python pipe test and Python API test; do not label that as a visual pending-state observation. The result window was left open for review, with no active run or device session.

## Validation

- Native observation binary built successfully with the existing Rust/MSVC toolchain (final build 6.02s). No installation or security setting change.
- Python structural suite: **177 tests, 175 passed, 2 existing ephemeral-PKI dependency skips (41.252s)**. Includes actual Python child readiness/preview/EOF and approval/version/coverage tests. No full legacy inspection suite was run.
- Rust `cargo test --bins`: **7 passed, 6 explicitly ignored** across the binaries. The new actual Rust -> Python observation contract test was then invoked explicitly and **passed (8.22s)**; ignored historical environment-dependent tests are not newly claimed successful.
- The initial Rust test compilation exposed a `gpui_kit::*` test-macro import collision. Restricting the test module imports resolved it; the successful results above are after that fix.
- `git diff --check` and document reference checks are part of publication verification. Actual screen/device data are not committed; this run used only fixed synthetic data.

## Reproduce

From the repository root, with the previously installed tools (provide an existing Python path and a fresh disposable local output directory):

```powershell
$env:FINSEC_MOCK_PYTHON = '<existing P4 venv python.exe>'
$env:FINSEC_OBSERVATION_ROOT = '<fresh local synthetic output directory>'
cargo run --manifest-path pocs/p4-integration/gpui-smoke/Cargo.toml --bin observation
```

Choose Check -> Load fixed plan -> Approve -> Load newer fixed version -> Run with old approval (rejected) -> Approve current -> Run -> Results -> Load final result. No A34 or Appium is needed. To exercise the actual Rust child pipe without UI, use the same environment with `cargo test --manifest-path pocs/p4-integration/gpui-smoke/Cargo.toml --bin observation -- actual_observation_pipe_contract --ignored --nocapture`.

Related: [approved observation spec](../../../docs/spec/10-observation-checkpoints.md), [standalone synthetic structure](OBSERVATION-CHECKPOINT-POC.md), [separate real A34 state-reader acceptance](QA-STATE-DEVICE-VALIDATION.md).
