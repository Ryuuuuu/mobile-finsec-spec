# Completed synthetic Results history

The Results tab explicitly refreshes a bounded list from the dedicated local `completed-reports` directory only. It does not enumerate other run directories or user folders. The display date/time is archive publication time in UTC, not replay start time. Run ID plus plan hash identifies a selection; equal timestamps never merge rows or choose a run implicitly. Order is newest timestamp first with run-ID tie breaking. Old archives without timestamps say DATE_UNAVAILABLE, never use guessed file times.

Only validated completed fixed-fixture reports are selectable. Malformed/incomplete entries are explicitly unavailable. Listing inspects at most 100 directory entries and 128 KiB per candidate; hitting the bound reports HISTORY_LIMIT with no selectable partial list. Reload revalidates the selected file to detect deletion/corruption after listing. A failed selection clears displayed details to avoid stale-result confusion. It never restores replay, approval or review tasks. Current-session Load final result remains separate.

New publication envelopes use v2 with saved_at; v1 envelopes and their missing historical timing detail remain supported. The picker does not automatically migrate legacy run/result.json files, inspect raw evidence, or infer timing from the current plan. This is a synthetic reporting POC; no device, model, real app, inspection skill or external network is involved.

## Data contract validation

The existing `history` operation returns status plus rows containing `run_id`, `plan_hash`, `saved_at`, `available`, and a bounded reason. It never creates an execution owner/task or changes approval. Unavailable rows omit plan/time rather than exposing unvalidated content. Unknown-time v1 archives sort below dated rows. Refresh is synchronous and explicitly user-triggered; this is not a watcher or a general filesystem catalog.

Synthetic Python validation: history 3 tests, archive 5 tests and existing stdio 3 tests passed. These cover same-timestamp distinct identities, deterministic ordering, distinct saved results, old missing date, malformed/unavailable files, stale selection rejection, bounded dedicated-folder enumeration, local child restart and unchanged idle/current-session behavior. Test artifacts remain private. Timestamp collision was tested synthetically; the interactive two-run fixture had distinct publication milliseconds.
