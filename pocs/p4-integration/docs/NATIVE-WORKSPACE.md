# Native three-tab structural workspace

## Scope and multiple-route requirement

The user requires selecting several saved routes, ordering them, and replaying 1 -> 2 -> 3 on one device without overlap. Each route retains its own recording/packet identity and result. Selecting only one route is not the intended limit. Repeating a selected sequence creates new execution IDs, not overwritten results.

This native GPUI-kit POC implements the selection and sequential **mock structural execution** portion, using actual Rust-to-Python private pipes. It does not yet dispatch the selected routes through P1's real device replay controller. It must not be described as multi-route A34 replay success.

`gpui-smoke/src/bin/workspace.rs` has Record, Check and Results tabs. Record has named, timestamped recording checkboxes and selection order, with no inspection item controls. Check selects an existing opaque mock item and shows live events. Results explicitly loads finalized dated runs and details independently of live events. Selection order is checkbox order; clear and reselect to reorder. No selection preserves the existing default app-launch intent. This is not an actual app launch.

Optional `recording-meta.json` contains schema_version=1, the canonical P4 recording_id, display_name and timezone-aware recorded_at. It cannot replace the route/link/packet identity. Invalid metadata disables that row; absent metadata uses the reference and an explicit unavailable timestamp. Fixtures use synthetic timestamps, not inferred creation times.

## Safety and pending decisions

Only one admitted route runs at a time. The next is submitted after the previous terminal completed state. Unknown transport outcomes block further admission and are not retried. Failed/cancelled/unresolved execution stops remaining routes in this POC. **Product continuation policy is not agreed**: stop all, skip failed route, or explicit retry/resume must be decided with the user. A failed operation is never automatically repeated.

The product needs a durable queue owner, ordered immutable recording references, per-route replay/run IDs, scoped packet collection, device lease across the sequence, and recovery reconciliation after restart. The current queue is in-memory and intentionally does not auto-resume. Existing Python durable command recovery remains authoritative. No inspection skill, tool selection or vulnerability judgement is implemented.

The private child validates version/project/request generation and caps response frames at 256 KiB with a five-second response deadline. Pipe writes are small trusted built-in requests, without an independent write deadline. Child shutdown closes stdin, then terminates/reaps the owned process after a one-second grace period. Descendant cleanup, active real-tool cancellation and hostile child behavior are not validated by this POC. The product's authenticated loopback API is a separate transport gate.

## Reproduce

Use the existing Python environment with P1/P2 dependencies to create disposable data:

```text
python pocs/p4-integration/scripts/prepare_native_demo.py --root <fresh-private-folder>
```

Set FINSEC_MOCK_PYTHON to an existing Python executable capable of running P4 and FINSEC_MOCK_ROOT to that folder. Do not use real device evidence. With the installed Windows MSVC/SDK/Rust toolchain:

```text
cargo test --locked --offline --manifest-path pocs/p4-integration/gpui-smoke/Cargo.toml --bin workspace -- --include-ignored --test-threads=1
cargo build --locked --offline --manifest-path pocs/p4-integration/gpui-smoke/Cargo.toml --bin workspace
```

Launch target/debug/workspace.exe with the same environment. Refresh recordings; select demo-2 then demo-1; open Check, select mock-item, Start; open Results and refresh. The explicit Python acceptance command remains `python scripts/run_structure_tests.py` from p4-integration. Do not run historical judgement suites.

## Validation ledger

- Windows native build passed. Five Rust tests passed, including actual separate Python child requests, ordered demo-2 -> demo-1 -> demo-2 with distinct final run IDs and matching canonical recording IDs, live/final separation, duplicate submit and restart recovery. These are synthetic executions, not device input.
- Python structure-only suite: 155 passed, zero skips. Added metadata identity/invalid/absent handling; existing partial, corrupt and isolated artifact cases remain included.
- Native UI validation is recorded separately below; compiling or subprocess tests alone do not certify the screen workflow.
- Real multi-route replay, real model execution, production layouts/virtualization/accessibility, multiple projects and durable queue recovery remain unverified.

## Native rendering defect found during acceptance

With Windows accessibility attached, rendering multiple live-event labels from one `Label::new` call site reproduced a debug panic: duplicate a11y node ID. gpui-kit 0.10.0 documents that loop labels require explicit IDs. Live and detail labels now have distinct indexed IDs. This was not covered by transport-only tests; actual native screen acceptance is required. Progress polling also reschedules when another request occupies the serialized channel, and drains remaining event pages before advancing the queue.

After the fix, actual native checkbox input selected demo-2 -> demo-1, Check started both sequentially, and accessibility showed each route terminal completed followed by Queue completed. Results displayed ten finalized dated runs (including earlier test runs), and clicking the newest showed storage ok, completed 1/1, the correct canonical recording ID, complete route/packet states and no security verdict. A screenshot confirmed the final result layout. The window then closed normally. No real device/model was used. Cancel/failure policies are covered by queue-model tests, not an active native GUI cancellation acceptance.

## Actual device queue follow-up (separate UI)

[P1 combined Tk queue](../../p1-record-replay/docs/REPLAY-QUEUE.md) now executes existing CombinedRun replay sequentially and passed A34 one-step/two-step and reversed-order repeats with separate WSS capture scopes. This does not change the native workspace synthetic-only status: a bounded native-to-device queue API and lifecycle integration remain pending.
