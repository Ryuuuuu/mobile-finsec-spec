# Real DEX extraction follow-up design

Use the existing official Android SDK Command-line Tools 19.0 `apkanalyzer`
Java entry point and its launcher tools-directory property. No download or new
license acceptance is needed. Existing JDK 21, Build Tools 35.0.0 and SDK platform
35 provide javac, D8 and aapt; SDK R8 reports 8.9.27. Record local tool versions
and hashes with private evidence. Do not bundle tool binaries or keys.

References: [apkanalyzer commands](https://developer.android.com/tools/apkanalyzer),
[R8 optimization](https://developer.android.com/topic/performance/app-optimization/enable-app-optimization),
[controlled global flags](https://developer.android.com/topic/performance/app-optimization/global-options).
These support bytecode/name inspection and a controlled renaming experiment, not
an automatic financial-security verdict.

## Reproducible authored APK pair

Compile one small, offline Java Activity and ImportantLogic class against android.jar.
Build both DEX variants with the same R8 version; plain additionally sets
`-dontobfuscate`. D8 is version-probed only in the final controlled comparison. For this experiment disable shrinking
and optimization, keep the Activity entry point, permit other name obfuscation and
save R8 mapping. This isolates renaming; it is NOT a production hardening profile.
aapt packages the same binary manifest for both; append the corresponding DEX.
APKs are unsigned static-analysis fixtures and are never installed. Preserve source,
flags and mapping provenance. A valid APK container/DEX is not runtime acceptance.

## Independent extraction CLI

Accept APK, explicit Java executable and SDK command-line-tool directory, selected
class name(s), and a new private output directory. First run bounded ZIP inventory.
Copy the validated input bytes privately to bind tools to the recorded artifact hash.
Use fixed argument arrays, no shell or arbitrary user commands. Execute actual
`dex list`, `dex packages --defined-only`, and `dex code --class` commands. Save raw
stdout privately plus hashes; parse strict defined class/member records and report
class/member counts, short-name observations and selected class smali evidence.
No deobfuscation mapping is passed to the analyzer: use mapping only as QA ground
truth to select the renamed class and verify controlled build correspondence.

Tool timeout, nonzero exit, excessive output, unknown format, no DEX, selected class
missing or unsupported input cannot become pass. The result remains inconclusive
on success too: name changes and readable smali are evidence, not sufficient policy
or semantic judgments. No automatic connection to the synthetic pass/fail evaluator.
Bound process output and wait, terminate/reap the owned direct Java process on error;
this is local process management, not an OS sandbox for hostile APK parsers.

## Acceptance

Execute both real builds and both actual analyzer runs, compare mapping-confirmed
important-class/member renaming and retained logic instructions. Check actual missing
class/malformed input failures. Separate unit parser/timeout/output-limit fault tests
from real SDK execution. Keep APKs, mapping, raw smali and hashes private; publish
only authored source, build/analyzer scripts, tests and sanitized summary. No device,
model, account, transaction, CA or security setting is used.


The initial pilot used D8 for plain and R8 for renamed. Review identified compiler
version/code-generation differences as a confound, so the acceptance pair now uses
R8 8.9.27 for BOTH variants with the same javac input and common flags. Only the
plain variant adds -dontobfuscate. Pilot extraction is not substituted for this
controlled rerun. No shrinking or optimization is claimed or measured here.
