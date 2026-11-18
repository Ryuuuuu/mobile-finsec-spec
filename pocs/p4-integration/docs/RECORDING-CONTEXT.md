# Recording reference contract for structural mock agents

`recording-context.v1` connects a selected recording's P1 route and P2 packet collection by one common recording ID. This is a synthetic data-handoff contract, not a reader for current P1/P2 artifact formats. No existing recording, packet, device identifier, network payload or assessment skill is loaded.

## Input and boundary

`StructureSupervisor.run(selected_items, platform, recording_id=None, recordings=None)` resolves a detached snapshot before execution. The mock catalog maps a synthetic recording ID to `{recording_id, app_id, route, packets}`. The mock app is fixed to `dev.finsec.synthetic`. Each channel contains exactly `{recording_id, ref_id, status, count}`. IDs are bounded synthetic identifiers; path/URL/raw-body fields are rejected. Both channels must match the common ID and app scope. Unknown or malformed fields are rejected before a run/worker is created.

For complete/partial references, ref_id and a bounded nonnegative count are required. For missing/not_collected, both are null. Complete packet count 0 means a declared completed empty collection, **not** missing packets. Count is metadata, not evidence of completeness or a verified artifact hash. Partial count only describes declared available material. No automatic pairing based on timestamps or proximity occurs.

|Selection/data state|Handoff behavior|
|---|---|
|No recording selected|app_launch_default; one declarative app.launch action; collection not_selected|
|Explicit recording ID absent from catalog|recording_unavailable; recording_missing; no silent launch fallback|
|Route complete with steps|recorded_route; route/packet references passed separately|
|Route complete with zero steps|recorded_route_empty; not converted into a launch default|
|Route partial/missing/not_collected|route_unavailable; no implied complete replay|
|Packets partial/missing/not_collected|collection incomplete; channel status preserved even with complete route|
|Both channels complete|collection complete declaration; empty packet collection remains explicit|

The default app.launch is **an intent in mock context**, not an executed launch or generated assessment route. A real launch adapter will need selected app validation and existing device authorization. An explicit missing recording does not mean the user selected no recording. A mock agent may complete processing an unavailable-data context; that execution completion does not change the missing/incomplete data status.

## Agent delivery and result persistence

Each selected item receives its own deep copy of `recording_context` alongside the opaque common/platform skill snapshot and item ID. Only selected items run, in order, under the existing structural lease. Mutation by one mock executor cannot alter another item's references or persisted input snapshot. No route or packet data is interpreted as a finding, vulnerability, or proof of causality.

Every result row, including not-reached/failed rows, records the reference snapshot and data-availability status independently of execution_status. Existing structure-run.v1 gains this additive field; consumers must preserve channel status rather than equating completed execution with complete collection. Persisted result.json contains reference metadata only, not route bodies, packet contents, model output or skill text. The same private artifact handling applies; opaque identifiers can still link records.

## Tested and unverified

New mock tests cover unselected launch intent versus explicit missing ID, zero-packet complete collection, both-channel partial/missing/not_collected states, cross-record/app mismatch, unknown payload fields, count validation, empty route, snapshot isolation, selected-only sequential delivery and saved-result equivalence. Supervisor/hang/exclusivity/provider/loader structural regression remains selected; no judgement engine tests are run.

Actual P1 recording IDs and P2 collection/session IDs still need a verified mapping adapter. Future integration must validate artifact existence, immutable hashes, collection boundaries, source schema/version, ownership/permission, app/build and run/attempt scope, time/order interpretation, stale references and storage access. Shared ID alone is not OS application attribution, packet causality, replay success or collection completeness. No real P1 replay, P2 capture or actual agent/model execution was tested here.

Reproduce from pocs/p4-integration with unittest discovery for test_recording_context.py plus the structural selection documented in STRUCTURAL-SUPERVISOR.md. All fixtures are created as mock data in code/temp directories. Source/docs/tests can be public; real records must remain private.

Validation (Windows/Python 3.12.10): 54 selected structural tests passed, zero skips, including 7 new recording-contract tests. No check-content or security-verdict suite was run.
