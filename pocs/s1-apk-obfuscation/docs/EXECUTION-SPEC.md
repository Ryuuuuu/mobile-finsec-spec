# S1 / CHK-15 APK obfuscation contract POC

This is the first S expansion of the P3 check-tool work, not a new P5 milestone.
Source: docs/spec/09-checks-poc.md, CHK-15. Internal CHK IDs are not official IDs;
no official compliance conclusion or real-application security verdict is produced.

## Scope and decision

Implement a standard-library-only, offline CLI with two separate paths:

1. `inspect`: bounded APK ZIP inventory, SHA-256 and DEX/native/resource counts.
   It does not extract files, execute APK code, decompile DEX, verify signatures,
   or measure actual obfuscation. Inventory alone ALWAYS yields inconclusive.
2. `evaluate`: a deliberately synthetic contract evaluator. Input is a generated
   APK-shaped ZIP fixture (not installable Android bytecode) and JSON review
   evidence tied to its hash. Only an exact synthetic marker admits this mode.
   A real APK can be inventoried but cannot obtain a verdict from these fixtures.

A real APK decompiler/R8 comparison is deferred until selected important logic,
analysis tooling, tool versions and an approved project-specific policy exist.
Do not fabricate analysis by counting short identifiers or inferring protection
from DEX/native presence. No device, model, network, signing key or new package
installation is necessary.

## Synthetic verdict contract

Require schema version, synthetic=true, artifact hash, named fixture-only policy,
selected scope IDs and two separate evidence files per scope. The two dimensions
are identifier transformation and readability of designated important logic.
Each observation cites a distinct APK entry and its content hash, an explicit
fixture tool/version and its selected scope. Evidence files are synthetic review
records, not outputs of a real decompiler. This tests evidence plumbing and policy
combination, not automated semantic interpretation or independent attestation.

- Pass only when every selected scope has complete, noncontradictory evidence
  supporting both required dimensions under the named synthetic policy.
- Fail only for a selected scope with evidence supporting both policy violations.
  Preserve a proved fixture failure when another scope is incomplete.
- Missing policy/scope/evidence, artifact mismatch, unknown status, tool error,
  contradictory or mixed observations yield inconclusive for the affected scope.
  One indicator can never create pass or fail. Unselected evidence cannot count.
- Malformed/unsafe input is an execution failure with inconclusive verdict.
  No silent default policy or automatic external analysis/retry.
- Output explicitly says synthetic or inventory-only, lists tested scope and
  limitations, and never promotes this result to whole-app or official compliance.

## Input/storage safety

Reject symlink input, duplicate ZIP names, traversal/absolute entry names,
excessive entry count, compressed/expanded sizes, encrypted entries and extreme
compression ratios. Read bounded bytes; never extract to disk. Reject duplicate
JSON keys/nonfinite constants and oversized reviews. Create a new private output
file exclusively; never overwrite prior evidence. Output contains no file bodies
or arbitrary exception strings. Actual hashes/paths/results stay outside Git.

## Acceptance plan

Generate three deterministic synthetic ZIP/review pairs; run each three times
and check expected pass/fail/inconclusive. Negative cases: single dimension,
missing/mixed evidence, conflicting evidence, artifact/evidence tampering,
wrong policy/scope/tool, duplicate names/JSON keys, traversal, size limit,
real APK rejected by evaluate, existing output preserved. Inventory a locally
built disposable QA APK if available, reporting inventory-only/inconclusive.
No installed app, real financial app, device state or model is involved.
