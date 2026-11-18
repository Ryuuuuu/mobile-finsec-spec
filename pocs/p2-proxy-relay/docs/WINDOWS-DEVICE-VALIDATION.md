# Windows and Android transport validation — 2026-11-18

## Measured scope

Windows 11 / Python 3.12.10 used a dedicated venv with `websockets==16.0` from official PyPI. `python -m unittest discover -s tests -q` ran **58 tests: 56 passed, 2 class-setup skips** because the OpenSSL CLI was unavailable. These skips prevent a claim of full TLS/WSS coverage on Windows. No certificates were installed in Windows or Android trust stores.

The intentional child-process termination test initially raised Windows `ConnectionResetError` at socket cleanup before checking recovery. It now tolerates only that expected reset in this crash-test cleanup, then still asserts interrupted/partial recording, incomplete packet, missing response and OFF on recovery. No production relay behavior or recovery assertion was weakened.

## Real-device USB transport smoke

Path: Android shell synthetic client -> one owned temporary `adb reverse tcp:0 tcp:PC_RELAY_PORT` -> Windows IPv4 loopback relay -> synthetic loopback upstream. The existing CLI integration scenario was run with its client replaced by this device-side client. RECORD labels remained synthetic and attribution remained unverified.

Measured results:

- 20 distinct GET requests `/synthetic/0` through `/synthetic/19` returned the expected HTTP 200 and matching synthetic response bodies.
- STOP reported 20 persisted transactions and complete coverage for the supported HTTP scope; query returned 20 unique packet rows.
- Relay shutdown/restart preserved identical packet-detail query results and restarted in OFF state.
- Each run removed only its own allocated reverse mapping, including failed diagnostic attempts. Temporary test child processes and DBs were cleaned by the fixture.
- No system proxy, Wi-Fi, firewall, CA/trust, banking application, authentication or transaction setting was changed.

Initial client attempts failed; they are not counted as successful tests. The shell path exposed CRCRLF output transformation, and an immediately closed client stdin lost the response. The passing path generated HTTP bytes on the device, used raw `adb exec-out`, and kept the producer open briefly while the response arrived. Raw protocol bytes must not pass through a terminal newline transformation. The successful command shape is:

```text
adb exec-out sh -c "(printf 'GET /synthetic/0 HTTP/1.1\r\nHost: synthetic.local\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'; sleep 1) | toybox nc -w 5 127.0.0.1 DEVICE_REVERSE_PORT"
```

The exact quoting depends on the host shell; the measured harness passed the `sh -c` program as one subprocess argument, without adding another layer of shell quotation. Ports are allocated dynamically and must not overwrite another owner's reverse mapping. This command is a fixture client, not an app interception mechanism.

## Limits and next design boundary

This verifies an actual USB/device transport path, **not Android application traffic capture**. `app_routing_verified=false` remains correct. Native/WebView network stacks, mixed-app traffic, TLS/WSS on device, pinning, HTTP/2/3/QUIC and USB unplug/reconnect have not been accepted here. Real device evidence/identifiers are excluded from the public repository.

Next: use a dedicated disposable network QA application with an explicit loopback test endpoint and correlation IDs, retain fixed synthetic upstream routing, and compare client receipt IDs with persisted records. This can isolate app-origin traffic without changing a global proxy. General application proxying/CA trust changes require a concrete routing/trust design and separate user approval before any security setting is changed. Do not install a CA or weaken certificate validation merely to make a banking application pass.

## Subsequent app-origin validation

The next stage is now measured in [Disposable Android app validation](ANDROID-APP-VALIDATION.md): HTTP/HTTPS/WS/WSS app receipts and RECORD/STOP boundaries, plus untrusted-certificate rejection. The historical shell-only limitation above remains the scope of that earlier run.
