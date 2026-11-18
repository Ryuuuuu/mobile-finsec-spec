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

## Actual DEX extraction follow-up

The separate `dex_extract` path now invokes the installed official SDK analyzer on
real APK DEX, saving defined class/member records and selected-class smali privately.
It ALWAYS remains inconclusive and does not call the synthetic evaluator. See
[design](docs/DEX-EXTRACTION-SPEC.md) and [actual results](docs/DEX-VALIDATION.md).
The initial synthetic-only limitations above describe the original path; real
semantic readability assessment and security classification are still not implemented.

From this directory, with trusted existing SDK/JDK paths (no download by these scripts):

```powershell
python -m build_qa --jdk C:\Tools\jdk-21 --sdk C:\Android\Sdk --output C:\QA\s1-pair
python -m dex_extract --apk C:\QA\s1-pair\plain.apk --java C:\Tools\jdk-21\bin\java.exe --tools C:\Android\Sdk\cmdline-tools\19.0 --class dev.finsec.s1.ImportantLogic --output C:\QA\s1-plain
# Read the authored build's mapping.txt for the renamed ImportantLogic class.
# The pinned tested build maps it to a.a; do not assume this for arbitrary builds.
python -m dex_extract --apk C:\QA\s1-pair\renamed.apk --java C:\Tools\jdk-21\bin\java.exe --tools C:\Android\Sdk\cmdline-tools\19.0 --class a.a --output C:\QA\s1-renamed
python -m compare_qa --pair C:\QA\s1-pair --plain C:\QA\s1-plain --renamed C:\QA\s1-renamed --output C:\QA\s1-comparison.json
```

The builder requires SDK platform 35, Build Tools 35.0.0, Command-line Tools 19.0
and JDK 21. It creates unsigned static-analysis APKs, not an installation workflow.
Every output directory must be new. Raw tool output may contain application logic
or strings; treat the entire directory as private. Tool time/output errors preserve
partial evidence with failed/inconclusive status. Exit 0 means extraction completed,
not that obfuscation protection passed.

### Durability and scope

[Per-DEX, size and failure validation](docs/DEX-DURABILITY.md) now records root DEX
inventories, selected-class provenance, partial extraction and explicit unassessed
native/WebView/resource scope. A WebView reference or `.so` ZIP filename is not an
analysis result. Two-DEX and ~24 MiB padded QA APKs passed actual SDK extraction;
>32 MiB input is rejected. All security verdicts remain inconclusive.
