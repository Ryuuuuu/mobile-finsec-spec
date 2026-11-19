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
# Strict no-settings-change device preflight (2026-11-19)

A subsequent request narrowed validation to GPUI -> P1 -> the disposable QA app, without security-setting changes or raw screen/traffic collection. Read-only preflight confirmed an authorized ADB device and an accessible, responding GPUI observation window. The window still showed the prior synthetic A/B result; this is not a new device execution.

The current paths cannot be joined unchanged under that restriction:

- `Session::start_observation` deliberately launches only `integration.observation_stdio`; it does not attach a device.
- `pc.qa_queue_stdio.execute` starts P2 collection, calls the existing Appium initialization path, and restores its security baseline during cleanup. It is not a state-only observation runner.
- Inspection of the locally installed UiAutomator2 driver's `performSessionPreExecSetup` and `deleteSession` found hidden API policy writes on Android API >= 28, including restoration to defaults. Merely selecting `skipDeviceInitialization` does not demonstrate that these writes are absent. Ignoring a policy error is not a no-write guarantee.

No device session, proxy, QA replay, raw capture, or setting change was started in this preflight. The GUI remains the synthetic-only POC. A test-only state-only runner needs a verified session lifecycle that does not write security settings, or an explicitly revised permission boundary; neither is silently inferred from earlier approvals. Such a runner must also exclude P2/raw evidence, preserve QA app data, and retain version/occurrence binding and cleanup reporting. Driver patching or alternative device control has not been implemented or validated here. This is an integration blocker, not a failed QA observation result.
# Repeated-selection UI follow-up (2026-11-19)

At `dfba39d`, preview/live/result text omitted the engine `occurrence`; live/result also omitted route version. A shared checkpoint formatter now includes recording ID, route version, **selection occurrence (zero-based)**, step and phase on all three surfaces. Engine identifiers and the observation result contract are unchanged. Missing fields display as unknown/null rather than inventing an identity.

The current synthetic smoke selects `route-A` twice with the same version/hash/step and occurrences 0/1. Loading the newer fixed plan produces evidence only on occurrence **1** (the second selection). Expected live/final rows: occurrence 0 has no evidence and `EVIDENCE_INSUFFICIENT`; occurrence 1 has one evidence object and progresses from `REVIEW_PENDING` to `REVIEW_TIMEOUT`. Overall evidence coverage is 1/2. Older A/B acceptance below remains historical and is not the current fixture.

Validation: Python UI contract **2/2 passed (8.271s)**, including identical ID/version/hash/step and distinct occurrences in preview/live/final. Rust observation binary tests **3 passed, 3 ignored**; the explicit real Rust-Python pipe test then **passed (8.20s)** and checked 1/2 results and distinct formatted rows. Offline Windows build passed (6.07s; existing unused-function warnings only).

Supported Windows CUA smoke actually displayed both repeated preview rows and live rows, including replay `completed` while review was still `review_pending`, then occurrence 1 timeout. Accessibility became intermittently unavailable; screenshot-based inputs loaded/approved/ran the fixture, but attempts to switch to the Results tab did not visibly change the panel. **Final Results-tab visual validation is unrun/incomplete**, despite the real pipe result and shared formatter tests passing. No permission/setup change or alternate UI automation was used to bypass that limitation. The completed synthetic window remains open. No Android device, packet capture, real model or inspection skill was used; local artifacts were not published.
