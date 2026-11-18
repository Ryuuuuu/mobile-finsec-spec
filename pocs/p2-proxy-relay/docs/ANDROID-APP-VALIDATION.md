# Disposable Android network app: design and measured acceptance

## Decision

Use a separate debug APK, `dev.finsec.qa.network`, with a fixed IPv4 loopback destination and explicit synthetic correlation tokens. It is independent of P1's offline QA applications. One owned `adb reverse` maps the device-side loopback port to the PC relay, whose upstream is also fixed loopback. No global proxy, Wi-Fi, firewall, VPN, system/user CA installation or banking-app manipulation is needed.

The app uses bounded raw HTTP/1.1 and a minimal RFC 6455 fixture exchange (masked text and close frames, at most 125 bytes). It is deliberately not a general browser/WebView/OkHttp compatibility client. HTTP/WS are explicitly cleartext only on the hardcoded loopback socket. HTTPS/WSS use an app-local KeyStore containing only a freshly generated three-day test CA; SSLSocket endpoint identification is `HTTPS` for `localhost`. Neither accept-all trust managers nor permissive hostname verifiers are used. TLS is enabled on both app-to-relay and relay-to-upstream legs in the secure scenarios.

The APK contains only the public test CA. The CA signing key is discarded after certificate creation; the localhost server key remains in the caller's private PKI output folder. No keys, certificates, APKs, device IDs or receipts are committed. Certificate expiry requires generating a fresh PKI and rebuilding the disposable APK; it must not be solved by disabling checks.

References: [Android app-specific trust configuration](https://developer.android.com/privacy-and-security/security-config), [SSLSocket endpoint identification](https://developer.android.com/reference/javax/net/ssl/SSLParameters#setEndpointIdentificationAlgorithm(java.lang.String)).

## Recording synchronization contract

The harness awaits ON, performs a pre-record request, awaits the RECORD acknowledgement, invokes three distinct app requests, waits for each app-private receipt, awaits STOP, then invokes a post-stop request. Both outside-window requests must arrive upstream but must be absent from recorded request/response bytes. The post-stop packet query must equal the pre-post-request query. Each in-window token must occur in stored data and match the app receipt and upstream request sequence.

This is causal command/receipt ordering, not synchronization of Android and Windows wall clocks. Receipt timestamps are diagnostic only. It validates P2's recording boundary with a cooperative app; P1/P2 shared start markers and a unified UI recording session are still unimplemented. Relay attribution remains `unverified`; correlated fixture evidence is not OS-enforced proof that arbitrary traffic belongs to a selected app.

## Device results (2026-11-18)

The new APK built with Android Gradle Plugin 8.7.3 / Gradle 8.9 / SDK 35 / JDK 21 and installed successfully. No installation confirmation was needed on this run. Tests used the authorized USB-connected Android device, not an emulator or mocked app.

| Scenario | Actual result |
| --- | --- |
| HTTP | 3 in-window app receipts and 3 stored transactions; pre/post requests delivered and excluded |
| HTTPS | Same, with verified TLS on both legs |
| WS | 3 successful app echo/close exchanges; 3 handshakes and 21 total stored rows including frames/lifecycle; pre/post excluded |
| WSS | Same WS results over verified TLS on both legs |
| Untrusted listener certificate: HTTPS | App rejected with SSLHandshakeException; zero upstream requests and stored rows |
| Untrusted listener certificate: WSS | App rejected with SSLHandshakeException; zero upstream requests and stored rows |

The four positive cases total 20 app invocations (12 inside recording, 8 outside). Two additional negative certificate invocations were rejected. All temporary reverse mappings are removed by the harness, including on failures. Device evidence remains private. The installed disposable APK is retained; no existing app data was reset or removed.

## Reproduce with explicit authorized device

Use a dedicated Python venv. From `pocs/p2-proxy-relay`:

```powershell
python -m pip install -r requirements-device.txt
python tools/make_qa_pki.py --output C:\QA\private-p2-pki
# JAVA_HOME, ANDROID_HOME and Gradle prerequisites are the existing P1 setup.
..\p1-record-replay\android\gradlew.bat -p android -PqaAssets=C:\QA\private-p2-pki\assets assembleDebug
adb -s YOUR_SERIAL install android\app\build\outputs\apk\debug\app-debug.apk
python tools/device_app_smoke.py --device YOUR_SERIAL --pki C:\QA\private-p2-pki --output C:\QA\private-results
python tools/make_qa_pki.py --output C:\QA\different-test-pki
python tools/device_app_smoke.py --device YOUR_SERIAL --pki C:\QA\private-p2-pki --output C:\QA\private-negative --untrusted-listener C:\QA\different-test-pki
```

Use a new output PKI directory: the generator refuses to overwrite an existing one. Review any device installation/security prompt; do not automatically approve it. Do not use `install -r` over an unrelated existing package or clear another app's data. The harness force-stops only this disposable QA package between invocations and reads only its private synthetic receipt via `run-as`. A missing CA fails the secure connection; it never falls back to unverified TLS.

## Automated tests and remaining scope

`requirements-device.txt` adds cryptography 50.0.2 solely for private test PKI generation. The existing test fixture can use this generator when OpenSSL CLI is absent, so Windows TLS/WSS tests no longer need to be silently left behind. The PKI regression checks localhost identity, server-auth purpose, short validity and refusal to overwrite keys. Final Windows/Python 3.12 run: **75 tests passed, zero skips**, including the previously skipped TLS/WSS suites. These are automated localhost tests and remain distinct from the real-device cases above.

Not accepted: ordinary third-party application interception, mixed-app attribution, transparent/CONNECT proxying, WebView/OkHttp differences, HTTP/2/3/QUIC, certificate pinning bypass, physical USB removal/reconnect, simultaneous P1/P2 GUI start/stop, or production trust/CA lifecycle. A future global routing or trust-store change requires separate concrete approval. Existing approved hidden API/helper settings were not changed by this P2 workflow.

## Integrated GUI follow-up

The dedicated app now also exposes native and WebView HTTP buttons for [P1/P2 combined GUI recording](../../p1-record-replay/docs/COMBINED-RECORDING.md). The new WebView cleartext exception is scoped to this app's loopback domain. The existing noninteractive HTTP/HTTPS/WS/WSS device cases were rerun successfully after the APK update. Combined-GUI TLS and OkHttp are still unverified.

## OkHttp and integrated replay follow-up

The pinned OkHttp 4.12.0 (Apache-2.0) loopback fixture passed HTTP and HTTPS on the real Android device: 3 captured transactions each, pre/post delivery excluded. HTTPS rejected an unrelated CA with SSLHandshakeException and zero stored/upstream requests. The full six-protocol matrix passed; no global CA or proxy was changed. This is cooperative QA token correlation, not OS-enforced attribution or support for arbitrary apps. See [combined GUI results](../../p1-record-replay/docs/COMBINED-RECORDING.md) for actual HTTPS GUI record/replay success and the WSS GUI disconnection that remains unaccepted.
