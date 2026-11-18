# ADB reverse ownership and recovery

## Evidence and uncertainty (2026-11-18)

The WSS GUI interruption was a host ADB failure. Its preserved private log recorded a fatal `handle_packet disallowed connect to tcp:<owned-relay-port>` immediately after the QA click. Windows Application Error/WER recorded the same adb.exe process terminating in ucrtbase.dll with 0xc0000409; P1 then received a connection reset. The destination was the GUI relay's port. Samsung composite/ADB/MTP interfaces were still present and healthy when investigated. A host-only ADB restart restored transport, but phone RSA authorization remained pending. No device security setting, key, driver or boot state was changed. A full symbolized crash dump was unavailable.

The strong mechanism is overlapping fixture ownership in our test sequence: the WSS GUI kept a `reverse tcp:0` mapping while a standalone certificate test created further `tcp:0` mappings. Current upstream `UpdateReverseConfig` keys its host allowlist by the literal requested remote address, so later `tcp:0` registration can replace the earlier destination while the earlier allocated device listener remains. The next request then fails the host allowlist check. The private logs and executed sequence support this explanation. We did not deliberately repeat a fatal crash on the user's device, and the exact installed binary was not symbolized. Do not call this an independently reproduced upstream defect or blame a user unplug.

Primary references: [ADB packet handling](https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/adb.cpp), [reverse configuration tracking](https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/transport.cpp). Current upstream is evidence for the mechanism, not a substitute for testing the installed version.

## Changes

- Shared `device_resources.OwnedReverse` uses explicit randomly selected device ports with `--no-rebind`, bounded candidate attempts and exact mapping verification. It never sends `tcp:0` or `--remove-all`. Only definite address collisions are retried; timeout, authorization and unknown errors require recovery.
- Cleanup verifies the exact device-port/host-port pair and removes only its owned mapping. A replaced mapping is never removed. Uncertain creation/removal is not retried automatically. Missing mappings after restart block further fixture use.
- Combined GUI reserves the shared P1 device lease before video, reverse creation or fixture launch. The reservation remains held when the Appium input session is disconnected. Final release follows network/video/Appium cleanup; uncertainty preserves quarantine.
- The standalone app smoke harness uses the same lease for its entire matrix, before any ADB command. It therefore cannot reset the QA activity or allocate ports while a GUI fixture owns the device. It verifies the owned mapping before each invocation.
- Combined RECORD/replay verifies the mapping before enabling input. A failed new start does not rewrite the previous completed route.

The lease coordinates these tools under the same Windows user. It cannot stop an unrelated external adb client from changing mappings. Do not disable ADB's allowlist check or clear recovery markers to proceed.

## Device-free validation

P2 resource tests model two owned mappings, a candidate collision, independent cleanup, mapping replacement, missing mappings after transport restart, allocation timeout, unauthorized error, idempotent cleanup, GUI reservation retention, and standalone lease denial/failure. A literal-key model reproduces the `tcp:0` overwrite behavior; it is explicitly a model, not a real ADB or device reproduction. A P1 lifecycle test verifies reservation release follows adapter cleanup.

No device command was executed for these regressions. Corrected WSS GUI recording/replay and real P3 observations remain pending phone authorization and explicit cleanup verification. The previous HTTPS/OkHttp results are historical acceptance of the earlier build, not acceptance of this new port allocator.

## Recovery order

After the user authorizes the same PC, verify the device is online and no old Appium/GUI process remains. Inspect retained security baseline and actual settings; honor the user's instruction to keep the approved baseline. Inspect reverse mappings and remove only positively identified stale mappings from this run. Resolve only its known quarantine after cleanup is verified. Start a fresh fixture and fresh output; do not automatically replay an interrupted action. Device-side cleanup while disconnected remains unknown.

Final device-free Windows regression: P1 113/113 and P2 86/86 passed. No Android test execution occurred in this revision.
