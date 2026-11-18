# DEX durability and explicit coverage validation

This follow-up extends the real SDK extraction path; it does not turn evidence
counts into an obfuscation/security verdict. All successful and failed cases below
retain **inconclusive**. No device or page/native-code execution occurred.

## Implemented coverage contract

Root `classes*.dex` entries are matched against the actual SDK list, then inspected
one at a time with `dex packages --defined-only --files`. Each DEX has a hash and
class/member inventory. Duplicate class definitions across DEX are rejected. Selected
smali records name their defining DEX. Completed earlier records survive a later
failure, and `unextracted_selected_classes` lists missing requested evidence.

`coverage` separates DEX enumeration, per-DEX definitions and selected smali from:

- `native.status=not_analyzed`: count is based only on `lib/*.so` ZIP paths, not ELF
  validation, architecture, JNI coverage or native obfuscation.
- `webview.status=not_analyzed`: a WebView reference in a defined signature or selected
  smali is a signal only. No observed signature does NOT establish absence; reflection,
  runtime loading, unselected bodies and native embedding can escape this signal.
- `resources.status=not_analyzed`: `.js/.html/.htm` counts do not establish script
  protection, loading, execution or origin. Nonstandard `.dex` paths are separately
  listed as outside the root-DEX extraction path.
- `whole_application=not_assessed` always. Complete means only the named extraction
  stage, not whole-app scope or a security pass.

Failed input before inventory leaves counts unknown/null, not falsely zero.
Tool failures record a fixed reason and failing stage; stdout AND stderr remain
private with hashes. A default 256 MiB Java heap, 30-second per-call limit, 120-second
shared analysis budget and 16-root-DEX cap bound work. Limits for APK/ZIP remain
32 MiB APK, 8 MiB per expanded entry, 64 MiB total expanded, 1,024 entries and
compression-ratio checks. The 4 MiB process-output limit is polled and can briefly
overshoot; it is not an OS quota or hostile-parser sandbox.

## Actual SDK runs on constructed QA materials

`build_durability_qa.py` uses the prior authored plain APK and compiles a separate
ExtraSurface with the official SDK D8 entry point. Its real `classes2.dex` references
WebView.loadData on authored local HTML. The extra class is never invoked. APKs are
unsigned static-analysis containers; this does not verify Android startup/multidex
loading or WebView execution. The original root DEX is unchanged.

| Material | Actual tool result | Evidence / honest boundary |
|---|---|---|
| Real two-DEX QA APK | completed / inconclusive | Two DEX inventories; selected ImportantLogic from classes.dex and ExtraSurface from classes2.dex; WebView signal observed, behavior not analyzed |
| Same APK + ~24 MiB stored inert padding | completed / inconclusive | Same two DEX paths and selected smali; tests archive size handling, NOT large-code or high-method-count performance |
| Same APK + synthetic `.so` path marker | completed / inconclusive | One native path reported not_analyzed; marker is NOT ELF or a compiled library, so no actual native analysis accepted |
| Same APK + ~36 MiB padding | failed / inconclusive, INPUT_LIMIT | Rejected at inventory before SDK process dispatch; no large-APK support claim beyond configured limit |
| Actual SDK JVM with injected 1 ms timeout | failed / inconclusive, TOOL_TIMEOUT | Owned JVM killed/reaped; fault injected by local harness, not a naturally hung SDK or normal 30-second performance test |

Both real-DEX/size-positive cases retain two authored web assets with resource status
not_analyzed. The native marker variant deliberately mixes real DEX and a synthetic
scope marker; it is not presented as an actual native-code QA app. The forced-timeout
harness records its 1 ms override separately; product defaults remain unchanged.
Previous real invalid-DEX and missing-selected-class SDK rejection remain documented
in [DEX validation](DEX-VALIDATION.md).

## Automated regression and non-claims

`python -m unittest discover -s tests -v` runs original fixture tests, parser doubles,
actual local Python child timeout/output/error tests, and added synthetic multi-DEX
coverage faults. New cases cover per-DEX provenance, second-DEX tool failure,
second-class timeout retaining first smali, cross-DEX duplicate class, omitted DEX,
size rejection before tools, total-budget expiry, excessive DEX count and absent
WebView signal not being treated as absence. These injected cases are NOT actual
SDK multi-DEX corruption or spontaneous timeout acceptance.

Remaining: genuine native ELF/library fixtures and native analysis, actual WebView
runtime/JS protection, Kotlin/Compose/reflection/native bridges, large code/method
counts, 16-DEX boundary performance, hostile-parser process isolation and product
policy/oracle integration. Large archive handling does not cover these gaps.

## Reproduce without a device

Use the same trusted JDK/SDK and previous `build_qa` output. All paths below must be
new private output paths. No APK installation or new system setting is required.

```powershell
python -m build_durability_qa --jdk C:\Tools\jdk-21 --sdk C:\Android\Sdk --base C:\QA\s1-pair\plain.apk --output C:\QA\s1-durability
python -m dex_extract --apk C:\QA\s1-durability\multidex.apk --java C:\Tools\jdk-21\bin\java.exe --tools C:\Android\Sdk\cmdline-tools\19.0 --class dev.finsec.s1.ImportantLogic --class dev.finsec.s1.extra.ExtraSurface --output C:\QA\s1-multidex-result
```

Repeat with large.apk and native-marker.apk using new result directories; expect
completed/inconclusive. oversize.apk must fail/inconclusive with INPUT_LIMIT. Never
change the limit merely to force a pass. Unit tests reproduce tool deadline and
partial-result faults without requiring the SDK. Raw APKs, stderr/smali, hashes and
private matrix output are not published.

Final Windows/Python 3.12.10 regression: **37 tests passed, zero skips**. Actual SDK matrix: 3 completed/inconclusive constructed APK cases, one expected oversize rejection, and one separately injected actual-JVM timeout with owned-process reaping. This count is not real-app or native/WebView runtime acceptance.

The later [configurable budget revision](RESOURCE-BUDGETS.md) retains these limits as defaults and adds explicit bounded opt-in plus streaming input. The earlier >32 MiB rejection remains the default behavior, not an unconditional limit for every future invocation.
