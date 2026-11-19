# Disposable QA state observation: A34 acceptance

2026-11-19 follow-up to `18898b6`. This is a real device test of the existing P1 replay queue and observation bridge, invoked by a private local CLI harness. It is **not a GPUI observation-plan UI test**, model integration, inspection skill, banking-app test or general screen interpretation result.

## Fixed state reader

`integration/qa_state_reader.py` accepts only the installed `dev.finsec.qa.network` QA package and an existing non-uncertain Appium session. It checks foreground package, finds exactly one `dev.finsec.qa.network:id/state`, and reads that element's text. Only `ready` and `sent:1` become `QA_READY` and `QA_SENT`. Unknown values are discarded and return an exclusion marker; absent/ambiguous elements, foreign foreground/package, invalid element IDs or expired budget fail closed. Error bodies are replaced with a fixed error code before they reach the bridge.

No screenshot, full hierarchy, input text, packet body, credential or actual device identifier is supplied to the fake reviewer. No actual model, external API or reviewer tool capability exists in this path. The reader uses only the existing loopback Appium server's read operations; it does not install software, modify settings or expose generic requests to the reviewer.

Appium request timeout now has an optional **shortening-only** keyword. Existing session-create/ordinary request budgets remain unchanged when omitted. The reader shares a one-second elapsed budget across its foreground/element/text requests and checks the remaining time before and after each response. This is a cooperative local HTTP read budget, not a hard OS-process kill guarantee. Snapshot sealing/handoff is a separately bounded host operation before the next input. No later screen is substituted when acquisition fails.

## Actual acceptance

1. Confirmed one authorized A34, unchanged approved settings, no reverse mappings and no active/quarantine reservation. Verified the existing QA certificate was still valid. Existing QA data was backed up privately and recorded APK/device targets matched before replay.
2. Selected **two different previously GUI-recorded one-action QA routes**, A then B. Both start at `ready`, press the normal SEND WSS control and expect `sent:1`. Full source hashes and stable action IDs were bound into the approved fixed plan. No replacement route was generated for this acceptance.
3. Ran actual Engine -> CombinedRun -> ReplayQueue, resetting only the disposable QA activity fixture before each route. Observed four sealed checkpoints in order: A before QA_READY, A after QA_SENT, B before QA_READY, B after QA_SENT. Both routes succeeded; their observation keys and replay/network IDs were separate.
4. State reads took 203, 172, 141 and 188 ms in this run. These four observations do not establish a performance guarantee. Each read completed within its one-second budget.
5. Used the fixed in-process fake reviewer with an eight-second artificial delay and an explicit six-second review deadline. The plan's bounded review-deadline range was widened to at most 30 seconds to permit this real replay experiment; this does not select a product default. P1 replay finished while review remained pending; later review events ended as REVIEW_TIMEOUT. All four evidence rows remained sealed and inconclusive/observation-only. No delayed reviewer controlled the device or scheduled a replay.
6. The local QA WSS fixture produced seven packet rows per route in separate private scopes. Only state DTOs reached review; packet rows were not review input or public output.
7. Final cleanup verified: original QA receipt restored byte-for-byte, reverse mappings empty, active/quarantine reservations zero, user-maintained hidden API/helper settings unchanged. The owned Appium server stopped. All 35 pre-existing files in the prior native cancellation acceptance directory retained their SHA-256.

The harness, configuration, actual IDs, source routes, server logs, private certificates, receipts, packet database and evidence results remain under local private test storage, outside public Git. Only source, synthetic fixtures and this aggregate report are published.

## Reproduction and limits

The existing authorized QA owner lifecycle remains responsible for preflight, reservation, local fixture networking, session and data restoration. Wrap its ReplayQueue with P1ObservationBridge, bind the existing two source routes with bound_route, attach read_network_qa_state, and retain the normal explicit per-route fixture preparation. Use a fixed plan with before_dispatch/after_postcondition for each stable action ID, capture handoff budget one second, and the explicit fake-review deadlines above. Keep configuration/serial/certificates and all result folders private; stop if target hashes, settings or ownership differ. This is a controlled QA harness procedure, not an unrestricted executable agent interface.

Run device-free regression from P4:

```text
python -m unittest discover -s tests -p test_qa_state_reader.py -v
python -m unittest discover -s tests -p test_p1_observation_bridge.py -v
python scripts/run_structure_tests.py
```

Wrong package, ambiguity, unknown text, read deadline and sanitized error-body behavior are synthetic cases. The actual A34 run validated normal A -> B acquisition and delayed fake review only; device disconnect, wrong foreground, cancellation/mismatch on A34 and permanent host hang were not deliberately induced. Existing synthetic bridge tests cover mismatch/cancellation separately. GPUI plan approval UI, arbitrary-app state extraction, real reviewer process isolation and real AI remain unimplemented/unverified. Existing user-maintained settings were preserved, not broadened.

Validation: prior bridge **4/4 passed (2.358s)** before device execution; new fixed reader **3/3 passed (0.002s)**. Afterward P4 structural suite **175 tests: 173 passed, 2 skipped (33.733s)**. The two existing TLS/WSS tests skipped for missing ephemeral-PKI dependencies in that environment, not counted as successful protocol validation. P1 full suite **153/153 passed (14.726s)**; after adding the timeout-override regression, focused session/lease suite **15/15 passed (0.039s)**. No revised full-suite count is claimed for that test-only addition.
