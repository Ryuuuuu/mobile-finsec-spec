# GPUI screen-contract alignment using a mock UI client

This is an in-process Python UI projection/client test. No GPUI/Rust widget, Windows window, actual device, actual model or new inspection logic is implemented or executed. The approved product remains the reference: [workspace/UI](../../../docs/spec/01-app-workspace.md), [recording](../../../docs/spec/03-record.md), [execution](../../../docs/spec/06-run.md), [result logs](../../../docs/spec/08-evidence-results.md).

## Mapping and limits

|Approved screen behavior|Existing/source contract and added mock connection|What remains unverified|
|---|---|---|
|Record tab: route + packet collection status|P1 link/route + P2 SQLite reader projected by UIBridge.recording; complete/partial/missing remain separate|Actual RECORD/STOP UI controls, live capture, mirrored input|
|Check tab: selection/eligibility/start|StartAPI.inspect/submit with mock device capabilities and service-owned recording refs|Real discovery/authenticated HTTP API and GPUI selectors|
|Check tab: current progress/live log|Execution ID now maps to active run ID; UIBridge.progress tails bounded lifecycle JSONL with cursor and deterministic run:seq event IDs|Actual AI token stream, full queue/heartbeat visualization|
|During work disable selection and device input, allow history|Projection disables controls while task in_progress or lease not free; input also requires connected/authorized mock input capability|Physical input interception or cross-project global device manager|
|Cancel/STOP|StartAPI.cancel requests task cancellation once; repeated requests report already requested/terminal|External tool/remote model termination or application close workflow|
|Result log: terminal records only|UIBridge.history filters finalized records; failed/cancelled are retained; active/unsealed/corrupt records are not presented as final history|Timezone-local date conversion, large-scale pagination/virtualization|
|Result details exclude live logs|UIBridge.result verifies final seal/hash and strips live events; rejects path traversal/run-directory symlinks|Full product result/evidence schema and authenticated evidence viewer|
|Tab changes do not auto-navigate at completion|MockUIClient keeps selected tab; user explicitly selects results|Actual GPUI focus/input routing|
|Late responses do not overwrite a new selection|project_id + request_generation + selected run_id gates; duplicate event IDs apply once|Real network reconnect/transport authentication and complete project lifecycle|

## Contract details

Envelopes carry contract=mock-ui.v1, project_id and request_generation. Progress additionally carries run_id, current API execution state, events, next_cursor, resync_required and control availability. A future cursor beyond available events or an invalid/gapped event sequence requests resync; the mock client clears its live event view and re-reads from cursor 0 with authoritative API state. An incomplete final JSONL line is not consumed. This is bounded replay of current files, not a network stream or a complete snapshot/recovery protocol for deleted history.

The new execution-to-run association is local to the active StartAPI. After restart, durable admission status remains recovery_required rather than fabricating a live run association. Repeated cancel is idempotent at the local task boundary and does not repeatedly interrupt cleanup. Known task termination and sealed history remain separate.

Result queries use a run ID resolved inside the service-owned root, never a client file path. Result data is read only after matching final marker/hash; raw lifecycle events are withheld from this tab. The underlying history diagnostic API can still list unfinalized/corrupt states, but the result-tab projection excludes them as required by the approved design. Device disconnection does not disable viewing previously sealed records.

A project ID in this in-process facade is a routing tag, not an authentication boundary. MockUIClient rejects mismatched project/generation/run responses but does not provide a security sandbox. Original project-wide writer locks/global cross-project device ownership and authenticated loopback API are still product work. Each bridge is explicitly bound to one StartAPI/root.

## Tests

Four new async tests exercise record→check→results with actual-format synthetic files, live events before finalization, duplicate/cursor-gap/resync handling, no auto-tab switch, input/selection disabled during execution, finalized-only history, result details without live events, partial packet collection, repeated cancel, disconnected/no-device eligibility, history access after disconnect, stale project/generation/run responses and invalid result path rejection. They use mock executors and opaque mock skills only.

The UI bridge does not claim pass/fail assessment completeness: product finalizer judgement-count requirements remain out of scope under the user's structure-only instruction. Fixed mock labels from earlier tests are presentation fixtures, not assessment logic. Similarly, packet collection complete_for_supported_scope never becomes whole-app attribution or full collection coverage.

Reproduce via test_ui_bridge.py plus the selected structural suites. Source/test/docs only are public; synthetic temporary data and private execution logs stay outside Git.

Validation on Windows/Python 3.12.10: 89 selected structural tests passed, zero skips. After the final disconnected-input projection adjustment, all 4 mock UI tests passed again. 116 traceability links resolve. Private log p4-ui-bridge-tests.log remains outside Git.
