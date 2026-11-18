# Model-independent structural preflight/start API

The active interface is an in-process service contract (`integration.start_api`), not an HTTP endpoint or a model prompt. `preflight`/`StartAPI.inspect` returns JSON-compatible enabled/disabled states and fixed reasons. `submit`, `status` and `wait` manage mock execution IDs. No LLM provider, root probe, vulnerability logic or user assessment skill is involved.

## Request and authority

```json
{"contract":"structural-start.v1","command_id":"synthetic-command","device_id":"synthetic-device-p4","platform":"aos","items":["first","second"],"inventory_revision":1}
```

These keys plus optional bounded recording_ref are accepted; recording_ref selects a service-owned file registry entry, never a client path. Platform is aos/ios, 1–10 unique bounded item IDs, bounded command/device IDs and an integer inventory revision. Unknown fields (including provider/model fields), duplicate/empty selections, invalid platform and boolean revision are rejected. A client supplies selection, **not** trusted capability/authorization claims.

The service owns a copied mock inventory with revision, device map, platform, connection, authorized flag and boolean capability map. The service also owns a mock item catalog: supported platforms, common-skill availability, available platform-skill names and required capability names. Tests use `mock_input` and `recording_read`; these are structural declarations, not real device measurements. False/missing/unknown capability values are not true. Common/selected skill availability is rechecked by the existing actual opaque-file loader at execution preflight.

Current executor supports one modeled device ID, synthetic-device-p4. Other inventory devices can be displayed but start is disabled with DEVICE_EXECUTOR_UNSUPPORTED. AOS/iOS refers to mock file selection only, not real platform compatibility or multiple physical-device scheduling.

## Enablement reasons

Response contract structural-preflight.v1 contains overall enabled, global reasons and per-selected-item enabled/reasons. Reasons distinguish stale selection, missing device, platform mismatch, unavailable connection, missing authorization, busy/recovery ownership, unknown item, unsupported item platform, missing common/platform skill and missing named capability. A missing requirement on one item does not hide which other items are eligible, but overall start requires all selected items eligible.

This API never changes prerequisites, approves prompts or configures security. No rooting/tamper state or app vulnerability can be inferred from these capability flags. Inventory/catalog are trusted service inputs in this POC; production discovery authenticity, freshness and schema ingestion require a separate adapter.

## Submission, duplicate and race semantics

A valid enabled request gets accepted plus execution_id. This is task admission, not a promise of successful device ownership. The SQLite lease remains the final exclusivity authority. Two distinct requests can both be accepted before either task acquires the lease; exactly one proceeds, and the other records not_run. If the lease is already active/recovery during inspect, submission is disabled immediately.

Same command ID plus identical canonical JSON returns duplicate with the original execution ID, even after termination; no replay is performed. Same ID with a different payload is conflict. Disabled requests do not create an execution. The local task cache is bounded to 100 jobs. A separate durable commands.sqlite ledger now claims up to 1,000 command IDs before scheduling. After restart, known admissions return recovery_required (changed payloads conflict), never automatic re-execution. Restoring results/reconciling prior effects and automatic retry/reset remain unimplemented. See INTEGRATED-STRUCTURE.md for the tested boundary.

After lease acquisition, before every item and during the cooperative watchdog loop, the authoritative mock inventory/catalog are checked again. Stale revision or lost connection/authorization/capability prevents execution or stops the current item with PRECONDITION_CHANGED; subsequent items remain not_run. Before any item starts, the whole run remains not_run. During a running item it is failed, not an assessment finding. Cleanup/revocation and recovery rules remain unchanged. Inspect supplies the specific current reasons; stop records intentionally use a fixed non-sensitive reason.

`status(execution_id)` distinguishes not_found, in_progress, finished, execution/storage error and recovery_required for a prior persisted admission without a local task. Finished carries the actual terminal execution_status; it never means a security pass. `wait` shields underlying execution from a caller merely cancelling its wait; explicit structural task cancellation remains separate. There is no automatic reconnect, remote cancellation or actual model invocation.

## Validation

Eight new tests cover enablement and each global reason; per-item capability/common/platform availability; unknown/duplicate selection and strict request keys; same-ID deduplication and changed-payload conflict; selection revision changing between admission and execution; disconnect during a mock item stopping follow-ups; two concurrent commands with one owner; disabled request creating no job; and mock iOS selection. Existing structural suites test actual opaque-file loading, hang/error/cancel, history and packet-reference boundaries. User skill contents and security verdict evaluation are not tested.

Run test_start_api.py with the selected structural suites. Remaining product work: authenticated discovery adapters and API transport, device-specific stable identity/generation, persistent command/result reconciliation, real-time UI enablement, multi-device ownership and actual model-neutral job transport. This POC establishes selection/admission data semantics using mocks only.

Final Windows/Python 3.12.10 validation: 80 selected structural tests passed, zero skips, including all 8 new start/preflight tests. 114 traceability links resolve. Private log p4-start-api-tests.log remains outside Git.
