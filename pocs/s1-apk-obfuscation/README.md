# S1 — APK inventory and synthetic CHK-15 obfuscation contract

Small independent first S expansion of P3. Standard-library Python 3.12 was tested;
no new dependency, device, model or network access is required.

**This is not an automatic APK obfuscation detector.** `inspect` reads an actual
APK ZIP but always returns inconclusive. `evaluate` combines explicitly synthetic
review records under a fixture-only policy. Its generated `.apk` is an APK-shaped
ZIP, NOT installable bytecode or a real obfuscated/unobfuscated build pair.

See [specification](docs/EXECUTION-SPEC.md) and [validation](docs/VALIDATION.md).

## Run from this directory

Use an existing dedicated Python venv, or create one with `python -m venv .venv`.
No pip installation is needed. Keep outputs outside the repository.

```powershell
python -m unittest discover -s tests -v
python -m fixtures --variant pass --output C:\QA\s1-pass
python -m obfuscation evaluate --apk C:\QA\s1-pass\synthetic.apk --review C:\QA\s1-pass\review.json --output C:\QA\s1-pass\result.json
python -m obfuscation inspect --apk C:\QA\authorized-qa.apk --output C:\QA\inventory.json
```

Repeat fail/inconclusive with new directories. Every output is exclusive; existing
files are never overwritten. Exit 0 means execution completed, not a good security
verdict. Invalid input/storage failure returns 2. Invalid input produces a failed,
inconclusive result when a new output file can be written. Inspect output includes
an artifact hash: retain it privately; it is not signature or provenance proof.

## Rules and boundaries

The selected important-logic scope needs two different evidence entries: identifier
transformation and logic readability, each bound by hash, scope and fixture tool
version. Only complete agreement under the exact named policy produces a fixture
pass/fail. Missing, mixed, contradictory or tool-error observations are inconclusive.
A proved fixture fail in one scope survives another scope being incomplete; a pass
cannot cover an unobserved scope. No short-name ratio, filename, DEX/native count,
or one observation can independently produce a security verdict.

The records declare observations: the POC does NOT derive their meaning by reading
code. Hashes detect mismatched bytes, not coordinated fabrication. A synthetic marker
is a mode guard, not an authenticity boundary. No real app conclusion is permitted,
even if somebody manually inserts that marker into an APK.

Production work remains: approved policy and important-logic selection; actual
DEX/decompiler/native/resource tools with versioned reports; controlled build pairs;
keep-rule/library/generated-code exclusions; manual review and broader coverage;
manifest/Skill/catalog registration; real artifact provenance and product integration.
Real obfuscation policies differ: the two-dimension fixture policy is not a universal
requirement that every app must rename every identifier or transform all control flow.
