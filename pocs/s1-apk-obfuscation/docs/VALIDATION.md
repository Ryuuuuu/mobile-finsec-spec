# S1 validation — separate inventory and synthetic evidence

Design was published first as e83bc06. This implementation follows the existing
CHK-15 design's important-logic, artifact identity and sufficient-evidence gate.
No official source-ID applicability revalidation or compliance opinion is claimed.

Windows / Python 3.12.10, no added packages. The unittest suite includes nine actual
local CLI executions: pass/fail/inconclusive fixtures each run three times into
new result files. Fixture bytes are deterministic. These are generated APK-shaped
ZIPs with synthetic review records and invalid placeholder DEX, not installed APKs,
R8 output, decompilation or real application verdicts.

Negative tests cover single dimension, mixed/unknown/conflicting evidence, missing
policy/scope, wrong artifact hash, missing/reused/changed evidence, wrong tool/status,
unselected scopes, partial-scope aggregation, malformed ZIP/JSON, duplicate entries,
traversal, absolute/Windows paths, compression/size limits, multidex naming, output
reuse and a nonfixture rejected by the synthetic evaluator. Error text is not copied
from input content. The Windows zipfile writer normalizes backslashes, so that test
injects the raw ZIP filename bytes after construction; the test exposed normalization during both writing and reading. The reader now
rejects an original ZIP name that differs from the normalized name, including
backslash/NUL normalization, without extracting anything.

Two **existing locally built disposable QA APK files** were separately processed by
actual `inspect` CLI executions (no installation/device use): both completed with
inconclusive. One inventory contained 5 entries/2 DEX-name entries, the other 17/3;
these counts do not demonstrate valid DEX parsing or obfuscation. Hashes and full
inventory files remain private. No real third-party application was evaluated.

Remaining: actual bytecode/decompiler analysis, known R8/minification build pair,
important-logic review, native/resources coverage, signing/provenance validation,
real policy calibration, manifest/Skill integration and product UI. A simulated
policy pass is not a CHK-15 real-app pass. Inventory remains inconclusive regardless
of DEX count or app size. No A34 access, security-setting change, model or service
call occurred.


Final result: **19 tests passed, zero skips** (`python -m unittest discover -s tests -v`).
Nine CLI fixture evaluations passed expected verdicts. Both actual QA APK inventory
runs were repeated successfully after the ZIP-name fix. An actual QA APK supplied
to evaluate with a synthetic review was rejected as failed/inconclusive; it was
not silently treated as fixture evidence. No runtime output or APK is published.
