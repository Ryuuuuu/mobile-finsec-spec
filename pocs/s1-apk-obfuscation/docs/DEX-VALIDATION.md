# Actual DEX extraction validation

## Tool selection and trust boundary

Used already-installed official Android SDK Command-line Tools **19.0** apkanalyzer,
SDK Build Tools **35.0.0** aapt, platform **35** android.jar, SDK R8 **8.9.27**, and
Temurin JDK **21.0.13+9**. D8 **8.6.2-dev** was version-probed; the final comparison
uses the SAME R8 version for both APKs. No tool was downloaded or newly licensed.

The Java command reproduces the installed official Windows launcher's classpath,
main class and `com.android.sdklib.toolsdir` property. The first direct Java probe
without that property failed; the adapter supplies it rather than suppressing the
check. apkanalyzer has no usable `--version` output here; provenance uses the SDK
source.properties revision and local launcher-JAR hash, not a fabricated version.
That hash does not attest every dependency JAR or establish a cryptographic vendor
signature. Only explicitly trusted local SDK/JDK paths should be supplied.

Official command reference: [apkanalyzer](https://developer.android.com/tools/apkanalyzer).
[R8 configuration](https://developer.android.com/topic/performance/app-optimization/enable-app-optimization)
and [global options](https://developer.android.com/topic/performance/app-optimization/global-options)
explain name minification and the experimental switches. No SDK/R8 binaries are
redistributed. Existing SDK terms continue to apply.

## Authored real-DEX APK pair

`qa/` contains a minimal offline Activity and ImportantLogic class with three public
QA result strings and two conditions. Both unsigned APKs contain a real compiled
binary manifest and DEX. aapt dump badging and actual apkanalyzer parsing succeeded;
they were not installed or executed on Android. This is stronger than the previous
APK-shaped fixture, but does not establish runtime behavior or valid signing.

The initial D8/plain versus R8/renamed pilot was replaced by the same-R8 comparison
to remove compiler-version differences. Both final variants use the same javac
input, no shrinking, no optimization, same Activity keep rule. Plain adds
`-dontobfuscate`; renamed permits other identifier changes. These are controlled
experiment flags, not production security guidance. The mapping file is QA ground
truth, never supplied to the independent extraction tool as a deobfuscation aid.

| Observation | Plain | Renamed |
|---|---|---|
| Actual SDK extraction | completed | completed |
| Defined classes / methods / fields | 2 / 4 / 1 | 2 / 4 / 1 |
| Short class simple names (length <= 2) | 0 | 1 |
| Important class | dev.finsec.s1.ImportantLogic | a.a, confirmed by R8 mapping |
| Selected ordinary method | classifyDemoUnits | a, confirmed by mapping and smali |
| Selected class method bodies (includes constructor) | 2 | 2 |
| Selected conditional instructions / string loads | 2 / 3 | 2 / 3 |
| QA_INVALID / QA_LIMIT / QA_ACCEPTED visible | yes | yes |
| Security verdict | inconclusive | inconclusive |

The authored comparison script checks artifact/evidence hashes, class and method
rename observations, the three expected strings and two conditions. It does not
prove semantic equivalence, score decompilation difficulty or certify protection.
The visibility of these known-source fixture branches/strings is a concrete reason
not to equate shortened names with protected important logic. It is also not a
vulnerability finding absent an applicable policy and adequate scope review.

## Error and regression separation

- Actual SDK calls: renamed APK requested with the old class name fails with
  SELECTED_CLASS_MISSING; no substitute class silently analyzed.
- Actual SDK rejects the earlier synthetic placeholder DEX; failure remains
  inconclusive, never a fabricated empty successful analysis.
- **28 unittest tests passed**, zero skips: 19 original contract tests plus 9 parser,
  evidence-scope and tool-management tests. Parser/analysis doubles are NOT actual
  SDK acceptance. Timeout/output-limit/nonzero-exit tests use real local Python
  children, and assert that a timed-out owned child is reaped; they are not remote
  cancellation or a hostile-parser sandbox test.
- Previous 9 synthetic CLI evaluations remain synthetic. The two actual R8 APK
  extractions and mapping comparison above are separate real tool executions.

## Limits and next work

Support is pinned to the observed SDK 19.0 text format. Unknown formats fail closed.
Selected classes are explicit; no automatic important-logic selection is attempted.
DEX/native counts and short names are only observations. Native code, resources,
reflection/keep-rule reasons, generated code/library exclusions, encrypted/dynamic
DEX, semantic readability, policy calibration, APK signing, actual Android runtime,
multiple real applications and product/Skill integration remain unverified or
unimplemented. The local process limit can kill/reap its direct JVM but is not an
OS isolation boundary. Concurrent hostile modification of the private output or
trusted SDK directory is outside this POC's guarantee.

APKs, mappings, raw DEX/smali, hashes and complete tool stdout/stderr remain in private
output directories. Only authored source/scripts/tests and this summary are public.
No device, real account, network service, model or security setting was touched.

The [durability follow-up](DEX-DURABILITY.md) adds per-DEX provenance, explicit
unassessed native/WebView/resource scope, bounded work and partial failure results.
Its actual multi-DEX/size SDK runs are separate from injected fault tests.
