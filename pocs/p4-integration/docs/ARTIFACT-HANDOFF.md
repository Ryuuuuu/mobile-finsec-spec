# Offline P1/P2 file handoff into structural agents

`artifact_reader.read_artifacts(link, route, packets)` reads **existing source-format files** without launching P1, a device, the relay listener or a model. `StructureSupervisor.run(..., artifact_files={link, route, packets})` passes the decoded data to selected sequential mock executors. This is mutually exclusive with the earlier synthetic catalog parameters. Omitting both still uses the existing app-launch default intent, not an actual app launch. Explicit missing files never silently select that default.

## Supported source profiles

- P1 `combined-link.json`/`combined.json`: current unversioned recording linkage (`combined_id`, `input_recording_id`, `network_recording_id`, `status`). Replay-kind links and a new schema_version are rejected as unsupported. This is a pinned unversioned profile, not a version guarantee; future source changes require an adapter update.
- P1 route JSON schema_version 1 and 2: same keys/action DSL emitted by `pc.core`. The reader uses the actual `pc.protocol.route` data validator, never the replay implementation. Incomplete records are structurally checked without promoting them to completed. An incomplete zero-action record is recognized as partial; an internal validation-only placeholder checks the other fields and is never delivered or executed.
- P2 SQLite `PRAGMA user_version=1`: recordings and packets tables emitted by `relay.Store`. Queries use explicit linked network recording ID, then verify metadata ID/sequence, schema version, app label, persisted count, gaps and per-packet incomplete status. No timestamp-based guessing or cross-record merging.

Tests construct public synthetic content through the **actual P1 atomic JSON writer and P2 Store writer**, including packet raw-byte separation into SQLite BLOBs. They do not start Relay or capture traffic. Recording metadata is authored fixture data accepted by Store, not evidence of a real collection session.

## Data passed and data saved

The executor receives detached `artifact_data.actions` and `artifact_data.packets`. Actions preserve the P1 action DSL. Packets carry bounded decoded metadata including request/response metadata; raw request/response BLOBs are deliberately not loaded. This does not provide full packet-body analysis. IDs, paths and headers within in-memory metadata can be sensitive on real inputs: use private storage and authorized content only. Tests use synthetic samples.

Persisted item results contain only reader status, counts, source hashes and a hash-derived common recording identifier. Raw actions, packet metadata, source device ID, filesystem paths and skill bodies are not persisted by this integration. Source files themselves remain private. Hashing does not make sensitive records anonymous or authenticate their truth.

## Availability and completeness

Link status, route status and packet status are independent. Missing file/row, corrupt structure/JSON/SQLite, unsupported version, unsealed database, partial recording and complete supported-scope record remain distinct. A valid route can be passed while packet collection is incomplete; mock completion only means context processing finished. Incomplete route mode is route_unavailable: no automatic replay is attempted.

P2's `complete_for_supported_scope` is not whole-app traffic coverage. Completed P2 records with coverage `none`, gaps, absent/mismatched persisted count or incomplete packets remain partial in this adapter. Empty collection is not upgraded merely because the record is closed. Packet sequence discontinuity/cross-ID/app mismatch is rejected. Shared IDs and temporal proximity do not establish OS application attribution or causal relationships.

## Resource and storage limits

JSON/link/route reads cap at 1 MiB with duplicate-key/nonfinite rejection. SQLite input caps at 16 MiB, 100 packet metadata rows, 64 KiB per metadata record and a finite SQLite VM instruction budget. Source symlinks are rejected. The DB must be an offline closed snapshot: existing -wal/-journal means unsealed. The immutable read-only connection avoids creating sidecars, is explicitly closed, and checks file hashes before/after to reject ordinary concurrent changes. This is not an adversarial filesystem/OS sandbox or proof against a coordinated rewrite; callers must provide stable copies. No migration, recovery or source write occurs.

Initial tests exposed that a sqlite connection context manager commits/rolls back but does not close its handle. Explicit closing fixed the retained Windows lock. Immutable read-only mode also removed sidecar creation on a closed WAL-mode source. Corruption tests now remain independent of reader-created sidecars. The reader does not remove journals or repair inputs.

## Validation scope

Seven new fixture tests cover actual serializers + selected-agent delivery/persisted redaction, P1/P2 version mismatch, incomplete zero-step route and interrupted collection, missing/corrupt files, mismatched IDs/missing packet rows, unsealed DB, and v2 general-app route structure. Existing recording tests cover no-selection launch intent and sequential detached snapshots. No assessment skill content, judgement engine, actual device, model, recorded real user data or network traffic is used.

Reproduce from pocs/p4-integration using unittest discovery for test_artifact_reader.py and the structural test selection. Remaining work: production source schema evolution, validated export/copy lifecycle, complete packet/body selection policy, GUI selection/status display, real authorized artifact acceptance, and actual replay/capture integrations. This POC does not establish these capabilities.

Final Windows/Python 3.12.10 validation: 61 selected structural tests passed, zero skips, including all 7 new source-format handoff tests. Private log: p4-artifact-reader-tests.log outside Git.

## On-demand raw-byte follow-up

[Attempt-scoped packet access](PACKET-ACCESS.md) now provides selected mock executors a bounded request/response BLOB read callable. Metadata is still the default context; raw bytes are not eagerly loaded or persisted. The earlier no-BLOB statement describes the metadata-only stage.
