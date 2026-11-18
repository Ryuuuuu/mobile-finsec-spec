# Configurable APK resource budgets and 32 MiB impact

## Impact assessment, not a finance-app survey

The old 32 MiB cap rejected the complete on-disk APK before DEX inspection. Assets,
images, native payloads and other resources could exceed it even when selected DEX
was small. This is a compatibility restriction of the POC, not an Android or
financial-security rule. We did not download or measure a representative set of
financial APKs, so no typical size, rejection percentage or coverage claim is made.

The current dedicated [Google Play size-limit page](https://support.google.com/googleplay/android-developer/answer/9859372?hl=en)
allows distribution components above 32 MiB (for example a base module's compressed
download limit is listed as 500 MB). Those distribution limits are NOT the same as
a single local APK's size, APK sets, AAB upload size or this analyzer's supported
workload. They justify not treating 32 MiB as a general app-size assumption, not a
claim that a given finance app is compatible. Split/feature APK aggregation remains
unimplemented; analyzing one base APK cannot establish full application coverage.

## Decision

Keep conservative defaults; add explicit finite `--budget FILE.json`. Do not remove
limits or silently increase them after failure. `profiles/qa-64mib.json` is a tested
example for the authored padded QA artifact, not a finance-app or product profile.
The legacy synthetic `obfuscation inspect/evaluate` path keeps its original fixed
limits. Configurable streaming budgets apply to `dex_extract` only.

APK copying and archive CRC/hash verification now use 128 KiB chunks, retain only
entry metadata/hashes, and run against a private snapshot. No APK/expanded entry
body is kept in a Python dictionary. Source size/mtime changes during copying are
rejected; later source modification cannot change the saved input used by tools.
This does not defend against a hostile actor mutating trusted SDK/private output
paths or defeating file-stat change detection.

Before Python ZipFile loads metadata, a bounded EOCD check limits central-directory
size and entry count. ZIP64 and multi-disk ZIPs are explicitly unsupported. Unsafe
paths, duplicate names, encryption, symlinks, excessive compression ratios, entry
sizes, expanded totals and CRC errors reject the archive. Legitimate highly
compressible/large entries may also be rejected: a limit failure is inconclusive,
not a malicious-file or security verdict.

## Default values and allowed finite ranges

All values must be JSON integers, not booleans/floats. Unknown or duplicate keys,
nonfinite values, zero/unlimited values and inconsistent combinations are rejected.
Effective settings are copied into every saved result.

| Setting | Default | Allowed range | Unit / purpose |
|---|---:|---:|---|
| apk_mib | 32 | 1–512 | on-disk APK |
| entry_mib | 8 | 1–128 | one expanded ZIP entry |
| expanded_mib | 64 | 1–1024 | sum of actual and declared expanded bytes |
| disk_mib | 128 | 6–2048 | retained output directory, including snapshot and logs |
| min_free_mib | 64 | 16–1024 | free-space reserve checked on the output volume |
| tool_output_mib | 4 | 1–16 | stdout+stderr per child process |
| heap_mib | 256 | 64–1024 | JVM -Xmx; NOT total JVM RSS |
| total_seconds | 120 | 1–600 | shared copy/inventory/tool deadline |
| tool_seconds | 30 | 1–120 | each tool, clipped by remaining shared budget |
| max_entries | 1024 | 1–8192 | ZIP entries |
| max_dex_files | 16 | 1–64 | root DEX files |
| compression_ratio | 200 | 1–200 | maximum declared expansion ratio |
| central_directory_mib | 4 | 1–16 | bound ZIP metadata before loading |
| symbol_records | 10000 | 1–20000 | total retained defined classes/methods/fields |

Entry budget cannot exceed expanded budget; tool deadline cannot exceed total;
disk budget must cover APK budget + one tool-output budget + 4 MiB result reserve.
Symbol names/signatures are additionally bounded to 512 characters. These limits
bound buffers/records but are NOT a hard Python RSS quota. JVM native memory and
runtime overhead are outside -Xmx. Output/free-space checks poll and can overshoot
briefly; deadlines are checked at chunk/process boundaries, not OS CPU quotas.
No certification at the maximum permitted settings is claimed.

Disk checks run before copying, during copying and during the owned child process.
Crossing a disk limit kills/reaps that child and preserves partial evidence. A
4 MiB result reserve is held back during analysis; final JSON is streamed to a
budget-checked temporary file and only renamed when fully written. Disk-full may
prevent even the error report; then no final result.json is published, exit is 2,
and any partial snapshot/log/result.json.tmp is not a completed report. These are
software accounting checks, not protection against other processes filling disk.

## Validation

Windows/Python 3.12.10: **51 tests passed, zero skips**. Added synthetic tests exercise
explicit size opt-in; hard caps/types; compression bombs rejected before their
payload is decompressed; entry/central-directory/count/ZIP64 bounds; low disk before
copy; disk loss during copy; aggregate output budget; actual local Python child
termination/reaping on a disk guard; copy deadline; symbol-memory bounds; and final
JSON publication failure. Disk-full conditions are injected, not produced by filling
the user's disk. No device or real finance app is involved.

A 12 MiB stored synthetic archive was snapshotted and CRC/hash-checked with a traced
Python allocation peak below 6 MiB in its unit test. This measures that one Python
path only: not JVM memory, total RSS, a performance benchmark or product capacity.

Separately, the existing ~36 MiB padded unsigned real-DEX QA APK is rejected with the
default 32 MiB setting. With explicit apk_mib=64 and all other defaults unchanged,
the official SDK extracted both DEX inventories and both selected smali classes:
completed/inconclusive. This validates one larger-container path with small authored
code. It does not demonstrate large-code/high-method-count/real-finance compatibility.
Full outputs and APK hashes remain private.

## Reproduce

From the S1 directory, using the previous durability fixture and trusted SDK/JDK:

```powershell
python -m unittest discover -s tests -v
python -m dex_extract --apk C:\QA\s1-durability\oversize.apk --java C:\Tools\jdk-21\bin\java.exe --tools C:\Android\Sdk\cmdline-tools\19.0 --class dev.finsec.s1.ImportantLogic --class dev.finsec.s1.extra.ExtraSurface --budget profiles\qa-64mib.json --output C:\QA\s1-budget64-new
```

Omit --budget and use another new output directory to confirm default rejection.
Raising only apk_mib does not relax compression, expanded size, disk, heap, output,
symbol or time limits. Any remaining failure preserves explicit incomplete scope;
all security verdicts remain inconclusive. No automatic reduced-scope pass occurs.
