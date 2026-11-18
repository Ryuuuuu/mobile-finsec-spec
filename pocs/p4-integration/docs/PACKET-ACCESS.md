# Attempt-scoped on-demand packet bytes

The previous metadata-only interface was insufficient for an agent that needs request/response bytes. The structural mock path now provides `context['read_packet'](recording_id, packet_id, direction)` only when a linked, sealed P2 SQLite snapshot has complete/partial readable metadata and a pinned file hash. `recording_id` is the common ID in recording_context, not an arbitrary path or foreign P2 record ID; direction is request or response.

No assessment skill, packet interpretation or verdict logic is implemented. The callable returns data to the selected cooperative mock executor. It is not exposed to an actual model, RPC server or general filesystem tool.

## Grant and isolation

Each selected item receives a separate grant bound to its current fenced lease attempt, the selected common record, corresponding P2 network record, immutable database snapshot and delivery budget. SQL filters both packet ID and network recording ID using bound parameters. Cross-record access returns denied/missing without disclosing another record. The current lease is authorized at each read. The callable is revoked on item completion and in failure/cancel cleanup, before the next item starts. A retained previous-item callable returns expired. Only the selected items' executors receive it.

This is an in-process cooperative capability, **not an OS sandbox**: arbitrary Python code with filesystem privileges could bypass it. Before real agent integration, put the interface behind the existing tool gateway/process boundary, preserve durable ownership and prevent direct file access. No such production isolation or remote-model handoff is claimed.

## Bytes, completeness and limits

Request/response BLOBs are loaded on demand, never automatically included in the main context. Response includes encoding=base64 and data only for successful complete/partial reads. Base64 preserves arbitrary binary and empty bytes; no implicit UTF-8 decoding occurs. These are the P2 stored raw message/frame bytes, not an invented HTTP body parser.

P2 metadata `stored_size`, `stored_sha256`, `size`, `sha256`, `truncated`, and packet `incomplete` are checked. When not capture-truncated, full SHA must match. A truncated original cannot be reconstructed or independently hash-verified; only its stored portion is verified. Missing hashes/fields fail closed rather than pretending completeness.

- `complete`: stored bytes verified, no source capture truncation, packet not marked incomplete, all stored bytes delivered.
- `partial`: verified stored bytes delivered, but capture_truncated, delivery_truncated, or packet_incomplete is true. The response separately reports all three plus original/stored/delivered sizes.
- `missing`: absent packet in the selected recording or NULL direction BLOB. A valid zero-length BLOB is complete empty data, not missing.
- `corrupt`: malformed metadata, length/hash mismatch, invalid SQLite/read error; no raw data returned.
- `artifact_changed` / `unsealed`: changed pinned file or WAL/journal present; no data returned.
- `limit`, `denied`, `expired`, `unsupported_version`: no bytes returned, no retry or scope expansion performed automatically.

`complete` describes this packet read, not the whole collection. recording_context's partial/missing collection status stays independent. No claim of traffic completeness or app attribution follows from readable bytes.

Default delivery cap 64 KiB per call (constructor can lower it); 256 KiB total delivered bytes and 20 authorized read attempts per item. Individual stored BLOB verification caps at 1 MiB and rejects larger BLOBs. Database cap remains 16 MiB, metadata 64 KiB, bounded SQL VM steps. Audit stores at most 50 fixed status codes. No pagination/offset resume is implemented: delivery-truncated results explicitly cannot represent the remainder as analyzed.

## Persistence and privacy

Returned Base64 is private in-memory data, not safe-to-publish encoding. Supervisor persists only fixed access status codes with the item result, never raw bytes/Base64, packet contents or error text. The source DB remains private. Mock result payload is still exactly execution completion, preventing accidental embedding of packet text into this result path. Production transcript/tool-result retention needs a separately designed private policy.

## Validation

All input is synthetic test data in temporary SQLite files generated with P2 Store and then varied for boundary cases. Tests cover binary and empty bytes, request/response selection, NULL/missing data, capture and delivery truncation, incomplete packet, stored-byte corruption, pinned-file change, oversize rejection, cross-record isolation, call budget, revoked previous-item access, sequential selected mock agents, and absence of raw/Base64 content in saved results. The initial empty SQLite BLOB/substr behavior was corrected to distinguish empty data from NULL.

No existing private packet, real device, network capture, actual model or inspection skill is used. Run test_packet_access.py plus the selected structural suites. Remaining work is actual gateway isolation, model-specific binary tool result handling, private retention, chunked access policy and real authorized packet acceptance; this change is the data access structure only.

Final Windows/Python 3.12.10 validation: 67 selected structural tests passed, zero skips, including 6 new packet-access tests with individual/aggregate byte and audit caps. Private log p4-packet-access-tests.log remains outside Git.
