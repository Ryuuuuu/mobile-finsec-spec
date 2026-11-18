# Active scope: structure only (2026-11-18)

The user will author assessment skills with skill-creator and specify their own tools. From this scope change onward, do not implement or test check-specific skill content, selected assessment tools, or vulnerability judgement logic. Earlier S1/S2/P3 results remain historical POC evidence, not current acceptance requirements or validated user skills.

Current work is limited to common-required + optional selected AOS/iOS skill discovery/loading/delivery, sequential item execution, device exclusivity, progress/hang/error supervision, and model-neutral adapter boundaries. Use opaque mock skills and fake task outcomes. Test execution state and isolation, not the correctness of a security verdict. Do not invoke skill-creator on the user's behalf or fill in their assessment instructions.

## What changed

`integration/skill_structure.py` adds a separate content-agnostic preparation loader: `<root>/<item>/common/SKILL.md` is required; selecting aos or ios also requires that platform file. With no platform selected, only common loads. Missing selected content fails closed rather than silently dropping it. The loader preserves UTF-8 text and SHA-256 in order, limits files to 64 KiB, rejects invalid item/platform paths, empty content and symlink escapes. `provider_context` creates a detached in-memory snapshot. It neither interprets the text nor executes tools or assesses findings. Snapshot bodies must remain private; hashes are integrity aids, not trust or instruction priority.

Mock tests verify common/AOS/iOS selection, missing files, bounded input, ordered delivery and snapshot isolation. The handoff function expects an internally produced bundle; it is not an untrusted external JSON verifier or an OS filesystem sandbox.

The loader is **not wired into the old P3-backed Supervisor path**. That path still couples CHK-07 synthetic content and bundle validation, and accepts AOS only. Future structural integration must inject a mock skill registry/executor and content-neutral result envelope before testing sequential orchestration there. A loader unit test is not evidence of iOS device execution, model receipt or end-to-end orchestration.

The local Ollama transport remains preparation-only, outside Supervisor. Its loopback mock request/response/cancel/timeout tests are in scope. Actual model execution, remote cancellation confirmation and persistent uncertain-job reconciliation remain unverified. No check-specific prompt or tool is added.

## Structure-only test selection

Run `test_skill_structure.py`, `test_ollama_http.py`, `test_providers.py`, and `test_lease.py` from the P4 tests directory via unittest discovery. These cover opaque mock files, local mock HTTP, fake provider lifecycle and exclusive ownership. Do not run the full old P4 suite as current acceptance: it also invokes P3 fixture verdict evaluation. Existing historical sequential/watchdog tests are not automatically considered content-independent; separate their mock runner and contract first.

No device, actual model, credential, real assessment skill or vulnerability judgement is tested by this selection. Previous real-model readiness and real-device comparison plans are subordinate to this active structural scope.

Validation: Windows/Python 3.12.10, 40 selected structural tests passed, zero skips. Four new opaque skill-loader tests passed. No full P3-backed suite was rerun after this scope change.
