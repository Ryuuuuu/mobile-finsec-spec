# Structural run log and final history contract

Execution state, result storage finalization and assessment display values are separate dimensions. This module does not implement a security check. Optional `mock_outcomes={selected_item: pass|fail|inconclusive}` supplies fixed **test-only** labels 양호/취약/판단 불가능 and fixed FIXTURE_ONLY reasons. It is never inferred from packets, skill content, successful execution or failed execution. Only completed mock items receive their configured display value; failed/cancelled/not_run items do not acquire a fake assessment.

## Live versus final files

Each unique synthetic run directory contains:

- run-meta.json: contract/version, run ID and UTC start time, written before lease admission.
- live.jsonl: appended timestamped lifecycle events while the run is active (item started/completed, run finished); flushed for concurrent observation. It carries no mock assessment, packet bytes, skill text or arbitrary worker messages. This is a lifecycle stream, not model token streaming or all internal progress updates.
- result.json: per-item execution states/reasons, reference snapshots, bounded packet-access statuses, start/end time, selected/completed counts and optional test-only assessment display values. A temporary file is fsynced before rename.
- finalized.json: written last with result SHA-256 and run ID, fsynced. A result file alone is not accepted as finalized history.

A live observer can read item_started before result.json exists. Reaching run_finished in the live stream does not imply final result storage succeeded. Consumers must wait for and verify finalized.json. Hashes detect ordinary corruption, not malicious authorship or synchronized rewriting of files. Directory rename/fsync guarantees, signed evidence, full filesystem transactions and power-loss acceptance are not claimed.

## Listing multiple runs

`integration.run_journal.list_runs(root, date='YYYY-MM-DD', limit=100)` returns newest UTC start time first, then run ID for deterministic ties. Multiple same-day executions have distinct IDs/directories and are never overwritten. Maximum returned rows is 100 and scan scope is 1,000 synthetic run directories; exceeding the scan cap is an explicit error, not silent omission. Result JSON is bounded to 2 MiB and small metadata to 8 KiB. The filesystem index is the directory set; a database index/GUI calendar is not implemented.

Each row exposes `storage_status`, `execution_status`, start/end time, completion counts and recovery_required where finalized. `finalized` can accompany completed, failed, cancelled, timed_out or not_run. Thus a stored cancelled run is a finalized **record**, not a successful inspection. Completed=1/selected=3 visibly preserves partial completion. The API does not infer final pass/fail from any run execution state.

Without a final marker the row is unfinalized and terminal execution status is withheld. This can mean still running, a stopped process, or finalization failure; listing alone cannot distinguish liveness. A malformed/hash-mismatched marker/result is corrupt and must not be shown as finalized. Old legacy directories lacking the new metadata are not automatically migrated or trusted by this reader. No automatic restart/recovery occurs.

UTC dates are the current storage/query contract; user-local timezone conversion belongs to a future UI layer. Content of finalized item results, including fixed mock reasons, remains in the private result file; list output is a summary. No real judgement or assessment skill implementation is added.

## Tested boundaries

New tests read live events while a mock worker is paused and verify that no final result exists yet; test all three fixed labels/reasons; list multiple dates/times; cancel after one completed item and preserve subsequent not_run; inject final-marker storage failure; corrupt result bytes; and verify executor errors do not inherit a requested mock pass or leak exception text. Existing structure, reference, packet, lease and fake-provider tests remain in scope. No old P3 judgement suite is run.

An initial Windows default-encoding error when adding Korean labels was corrected by explicitly saving the source as UTF-8. Validation uses actual local files and mocked timestamps/outcomes, not a real model, device, assessment, OS crash or physical power failure.

Run test_run_journal.py together with the selected structural suite. Product follow-ups include authenticated result retrieval, full schema validation/migration, pagination/indexing at scale, live stream recovery, local timezone UI and process-liveness reconciliation. These are not silently assumed complete.

Final Windows/Python 3.12.10 validation: 72 selected structural tests passed, zero skips, including 5 new history/log contract tests. Private log p4-run-journal-tests.log remains outside Git.
