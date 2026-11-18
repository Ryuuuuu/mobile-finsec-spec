# Native GPUI preparation: Windows build and input smoke verified

## Current verified state (2026-11-18 installation follow-up)

After user-approved Microsoft Build Tools 2022 17.14.45 / MSVC and Windows SDK installation, discovery reports complete, launchable and no reboot required. Persisted Machine/User PATH executes Rust/Cargo 1.100.0 and CMake 4.5.0. An ordinary std Rust executable compiled, linked and ran. `rustc --test rust-ui-state/lib.rs` ran 1 test successfully; the separate response_guard module has no standalone tests.

The isolated [native smoke](../gpui-smoke/src/main.rs) pins gpui-kit 0.10.0 and includes the resolved Cargo.lock. `cargo build --manifest-path pocs/p4-integration/gpui-smoke/Cargo.toml` succeeded in 3m30s on this machine. Launch the resulting `target/debug/finsec-gpui-smoke.exe`: its Korean/English label and Verify button are exposed through Windows accessibility; an actual click changed the counter from 2 to 3. This verifies native window/input state, not the proposed three-tab application or Python API integration. A screenshot while another window covered it was not treated as rendering evidence. Source startup follows the official Apache-2.0 [example](https://gpui-kit.com/docs/getting-started/). Dependency distribution/license review remains a product task.

The [mock loopback API](LOOPBACK-API.md) and earlier [narrow native pipe probe](NATIVE-RUST-PIPE.md) remain distinct results. The initial smoke had no Python transport; the read-only private-pipe follow-up below now verifies one native UI request. It still has no device/model, inspection skill or verdict logic. The later [three-tab native workspace](NATIVE-WORKSPACE.md) implements synthetic record/check/results integration; real P1 device replay and production integration remain unimplemented. The following observations are historical, before installation.

## Original observed boundary

On 2026-11-18 the Windows build terminal could not discover `rustc`, `cargo`, `rustup`, `cl` or `cmake`. The usual user Cargo/rustup directories, Visual Studio Installer discovery executable and CMake executable were absent. This establishes that this terminal is not prepared; it does not prove no alternate installation exists anywhere on disk. At that time no Cargo manifest existed in this project.

The read-only [preflight](../scripts/gpui_preflight.py) returned `blocked_prerequisites` and exit code 2. Compilation, dependency resolution, native window rendering and Rust-to-Python integration were **not run**, rather than failed builds. No native implementation or Cargo.lock is presented as verified. The previous 89 structural tests concern Python mocks, not GPUI compatibility. No device/model, inspection skill or judgement logic was executed or added.

## Candidate and preparation

The [official installation guide](https://gpui-kit.com/docs/installation/) currently documents gpui-kit 0.10.0, matching GPUI re-exports, Windows MSVC C++ tools/SDK and CMake. It recommends Rust 1.92+ for its current dependency graph. This is a candidate for a build experiment, not the product's validated dependency pin. Do not independently override the matching GPUI snapshot. The guide identifies source/examples as Apache-2.0; dependency/license review is still needed after resolution.

Prepare using the [official Rust installer](https://rust-lang.org/tools/install/), [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/) Desktop development with C++ including MSVC/Windows SDK, and [CMake](https://cmake.org/download/). Review any new installer license/privilege request before proceeding. An initial PowerShell script invocation was blocked by the existing execution policy; the probe was replaced with standard-library Python instead of changing that policy. This task installed nothing and changed no PATH, security setting or device state.

From a new Visual Studio Developer PowerShell, at repository root:

```powershell
python pocs/p4-integration/scripts/gpui_preflight.py
rustc --version
cargo --version
rustup show active-toolchain
cmake --version
cl
```

Preflight exit 0 means names were discovered only; it does not certify versions, SDK, linker or compilation. Confirm an MSVC target, then build the official [getting-started example](https://gpui-kit.com/docs/getting-started/) in an isolated experimental directory using `gpui-kit = "=0.10.0"`. Run `cargo check`, then `cargo run`; retain the resolved lockfile and actual tool versions only after success. Do not use `--locked` before generating the first lockfile. Record dependency/network, compiler/linker and window/input failures separately. Do not accept new installation terms automatically.

## Original proposed smallest real screen slice (see current workspace above)

The approved [workspace](../../../docs/spec/01-app-workspace.md), [check screen](../../../docs/spec/06-run.md) and [results screen](../../../docs/spec/08-evidence-results.md) remain authoritative. Preserve a visible **MOCK / NO DEVICE** indicator and implement only three tabs with synthetic recording selection, one mock item, Start/Cancel, live events and finalized history/detail.

|Screen intent|Existing Python interface|Rust/transport work still required|
|---|---|---|
|Record summary|`UIBridge.recording(ref, generation)`|Deserialize summary; distinguish missing, partial and complete collection|
|Select/start|`StartAPI.inspect` / `submit`|Typed command/request IDs, disabled reasons; no duplicate start on uncertain reply|
|Live progress/cancel|`UIBridge.progress` / `StartAPI.cancel`|Background transport, bounded event queue, cursor resync and cancellation acknowledgement|
|Result history/detail|`UIBridge.history` / `result`|Explicit tab switch, sealed records only; history remains available without device|

The initial API was an in-process Python facade. The later minimal loopback adapter wraps it for synthetic fixtures and a single mock project; see the current validation link above. The original design requirements are: It must use a per-launch credential, bounded/versioned JSON messages and service-owned recording references. Do not expose arbitrary filesystem paths or payload bytes to a result preview. Start the Python asyncio worker separately; the Rust render thread must never wait for Python, SQLite or network I/O. Transport failures become unavailable/unknown state, not completion or automatic resubmission. The minimal adapter now tests bearer authentication and bounded requests; native launcher integration remains pending.

Carry `mock-ui.v1`, project ID, request generation, execution/run ID and event cursor across the transport. Reject stale project/generation/run responses before updating a GPUI entity; deduplicate event IDs. Preserve live/final separation and the current durable recovery-required admission semantics. A disconnect should disable new work but leave previously loaded final history readable. On application close request cancellation once; unknown cleanup remains recovery-required. No synthetic result label may be presented as a real assessment.

## Acceptance after prerequisites

1. Compile and open the official native example; validate button input, resize and Korean text/input. Only then select/pin the UI dependency with the actual lockfile.
2. Implement the loopback adapter and test its authentication, limits, schema/version rejection and request correlation without any native UI or device.
3. Use the actual GPUI window to select a synthetic P1/P2-format recording, start a mock item, observe live progress, cancel or complete, manually open results, and view two dated final runs. Save no real captures.
4. Exercise no-device, partial collection, delayed/stale reply, double Start, cancellation, service loss/restart, cursor resync and unfinalized result exclusion. Compare UI state with authoritative Python state; a static label/demo animation is not API integration success.
5. Record compile/run/window/transport tests independently. Native virtualized lists, full selectors, IME, accessibility, project-global ownership, production service lifecycle and real device/model integrations remain separate gates.

This plan closes the preparation/documentation step only. It does not establish that the approved product screens can already compile or communicate with Python on this PC.

## Native GPUI to Python read-only follow-up

The native button now starts the existing `integration.mock_stdio` Python child with private stdin/stdout pipes on a background executor, sends only `history`, closes stdin, waits for child exit and renders the validated run count. No task is admitted. Set `FINSEC_MOCK_PYTHON` to an existing Python executable and `FINSEC_MOCK_ROOT` to a disposable private synthetic root. The module cwd is derived from this POC Cargo manifest. No shell, network listener, token, device or model is involved. The mock server only creates its existing opaque fixture files.

Executed: two Rust parser tests passed (ready/response identity, stale generation, malformed/extra/oversized frames). The opt-in real-child Rust test passed against the existing Python venv, with normal child exit. The rebuilt native GPUI window was clicked through computer use and displayed `Python mock history verified: 0 runs; child exited`; screenshot and accessibility state agreed. This is actual GPUI -> Rust std pipes -> Python UIWire -> GPUI display, with an empty synthetic history. It is not native HTTP integration, nonempty result rendering or the full approved three-tab workflow.

```powershell
$env:FINSEC_MOCK_PYTHON = 'C:\QA\venv\Scripts\python.exe'
$env:FINSEC_MOCK_ROOT = 'C:\QA\private-synthetic-root'
cargo test --locked --manifest-path pocs/p4-integration/gpui-smoke/Cargo.toml
cargo test --locked --manifest-path pocs/p4-integration/gpui-smoke/Cargo.toml -- --ignored
cargo run --locked --manifest-path pocs/p4-integration/gpui-smoke/Cargo.toml
```

The reader caps output at 256 KiB plus an overflow byte; the child wait has a five-second deadline and kills/reaps the owned child on failure. Errors expose fixed categories, not raw child stderr/data. Busy suppresses overlapping button requests. The actual GUI proof covers normal completion only. Native timeout/forced-exit races, window close during request, descendant processes, hostile-child pipe inheritance, cancellation of admitted jobs and persistent multi-request sessions are **not validated** by this one-shot trusted mock probe. Production launcher lifecycle remains a separate task; do not promote this small probe as the finished adapter.
