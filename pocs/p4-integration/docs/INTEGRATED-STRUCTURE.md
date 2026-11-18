# Device-free structural integrated acceptance

## End-to-end exercised path

A mock inventory and item catalog authorize the selected synthetic device/AOS items. The start request optionally names `recording_ref`, an opaque key in a **service-owned registry** of link/route/SQLite paths. Clients do not supply arbitrary filesystem paths. Actual P1 atomic JSON and P2 Store writers create non-sensitive synthetic source-format files. The structural runner loads common/platform opaque mock skills and passes detached route/packet metadata plus scoped on-demand byte access to selected mock executors sequentially under the shared lease.

While the first worker is deliberately paused, live.jsonl is observable and history reports unfinalized with no terminal execution status. The worker then reads a synthetic request BLOB by common record ID + packet ID, returns execution completion and releases its grant. A second item and a second distinct command run similarly. Sealed results and UTC same-day history list both runs, without saving packet bytes or Base64. This is actual local Python/file/SQLite execution with mock agents, not real device replay/capture, an LLM or a security judgement.

## Integration defects corrected

1. The start API previously accepted only device/item selection and never forwarded the existing artifact selection to Supervisor. Optional bounded `recording_ref` and the server registry now connect that path. Unknown keys disable both overall and per-item enablement. No selection still uses the existing default app-launch intent only; an explicit absent record is not silently replaced.
2. Command deduplication previously vanished on process restart. `commands.sqlite` now atomically claims command ID + canonical-request digest + execution ID **before task creation**. A new API instance sees an earlier same request as recovery_required instead of executing it again. Different payload on the same ID conflicts. Concurrent claims are transactionally serialized. The ledger has a 1,000-admission cap and no automatic eviction/reset.
3. Querying a known admission after restart previously looked like not_found because only in-memory tasks were visible. Status now reports recovery_required for known persisted execution IDs, keeping uncertain history explicit.

The ledger is deliberately conservative. Same-instance duplicates still return the same handle, but after restart even a completed prior admission requires reconciliation; it does not automatically restore task/result handles or promise exactly-once effects. A crash after ledger claim but before task creation can leave a known admission with no run directory. This is retained uncertainty, not permission to retry. New command IDs are new user requests; the lease remains the independent device exclusivity authority. No ledger deletion, recovery override or ownership stealing is implemented.

## Failure/restart coverage

- Mid-run mock failure: first item remains completed, second failed; stored completion count stays partial; all retained packet grants expire; arbitrary exception text is not saved.
- Final-marker storage failure: result may exist but history remains unfinalized; API status reports storage/execution error; a freshly constructed API does not resubmit the prior command.
- Real local child-process termination: a test child acquires the synthetic lease, writes run metadata + item_started, then calls os._exit(7). Parent verifies that exact exit, opens a new API, observes unfinalized history and retained active lease, and refuses a new start. This is an actual subprocess-boundary test, **not a Windows reboot, power loss, device disconnect or malicious process-isolation test**.
- Multiple successful commands: distinct execution/run IDs, ordered selected items and two same-day finalized history records; an earlier command remains blocked from re-execution after API reconstruction.
- Unknown registry reference: no worker is admitted. Unselected reference: declarative launch default persists, no app is launched.

All tests use temporary mock skills and synthetic requests/responses. No inspection skill content, tool choice or security verdict implementation is created/tested. Existing historical P3 judgement tests are excluded.

## Remaining limits

Reconciliation UI and authenticated persistent command/result association, concurrent OS-process admission stress, actual model transport, real-device execution, filesystem adversaries, production multi-device scheduling, registry authorization/lifecycle and OS-level sandboxing remain separate work. Inventory capabilities are declarations. Live events are lifecycle records rather than model-token streams. Passing this integration validates the local structural chain only.

Reproduce from pocs/p4-integration using test_integrated_structure.py plus the selected structural modules. Detailed logs stay outside Git; only source/tests/docs are published.

Final Windows/Python 3.12.10 validation: 85 selected structural tests passed, zero skips, including 5 new integrated scenarios. The child-process termination test ran locally and returned the expected exit code 7. Private log p4-integrated-structure-tests.log is outside Git.
