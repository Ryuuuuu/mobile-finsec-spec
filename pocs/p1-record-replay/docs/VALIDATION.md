# P1 검증 보고서

검증일: 2026-11-16 UTC / 2026-11-17 KST.

**결론: 클라우드 구현·자동 테스트·APK 빌드 완료. 실제 Windows/Android 기기 인수시험은 아직 미실행이며 P1 실기기 통과를 주장하지 않습니다.** 사용자 PC/실기기에는 접속·설치·입력을 하지 않았습니다. 이 보고서는 최초 클라우드 구현 시점의 검증 기록입니다. 이후 소스가 설계 저장소의 `pocs/p1-record-replay`에 편입되었습니다.

2026-11-16 UTC 게시 전 재검증: Python 단위/fake HTTP 테스트 **27/27 PASS**. `artifacts/*`로 표기한 최초 빌드 로그와 APK는 원본 배포 묶음의 증거이며 이 Git 소스에는 포함하지 않습니다. 아래 실기기 미검증 상태는 추후 별도 인수 결과로 갱신합니다.

## 구현 결과

- Android 네이티브 Java 앱: synthetic login, menu, mock transfer input, review/confirmation. public fixture `qa-user`, `qa-pass`, `DEMO-001`, `1000`만 입력 사용. 실제 금융·네트워크 권한 없음.
- `dev.finsec.poc`, versionCode 1/versionName 1.0, minSdk26, compileSdk35, targetSdk28. 안정적 resource ID, 명시적 reset, FLAG_SECURE toggle. secure와 진행 상태는 앱 재실행에도 유지하며 reset은 secure를 보존합니다. debug APK이며 제품 보안 기준 적용 주장이 아닙니다.
- Python/Tk: Appium screenshot polling 화면 클릭/드래그, public text, Back, Wait. 자체 PC UI 입력만 기록. 전송 전 intent fsync, 이후 dispatch/result 및 XML/PNG 참조 저장.
- 완료 route만 재생. 명시적 serial/package/build SHA256/reset 상태/secure 설정 검증. resource ID 고유 일치 우선, 좌표는 명시 opt-in 및 같은 geometry/rotation, 최대 3회.
- 기록/재생 단일 worker, 비차단 API busy 거부, 프로세스 간 OS lock, crash marker/quarantine. 유한 HTTP/ADB/관찰 timeout. cancel/단절/관찰 부족/저장 오류는 failed 또는 incomplete, 재생 tail은 not_run. route-provided 임의 코드/shell/스크립트 금지.
- Windows 준비/실행/복구 안내, 10단계 동선 표, FLAG_SECURE 관찰표 지침, versioned JSON 합성 예제, 고정 npm lockfile 및 Gradle checksum wrapper 포함.

## 실행 결과

| 검증 | 결과 | 증거/범위 |
|---|---|---|
| Python unit + fake HTTP integration | **27/27 PASS** | `artifacts/tests.log`, 약 4.6초. 실제 기기 아님 |
| Python compileall | **PASS** | `artifacts/compile.log` (정상 출력 없음) |
| CLI help / import | **PASS** | `artifacts/cli-help.txt`, import 시 기기 동작 없음 |
| 10단계 JSON 예제 validator | **PASS** | `examples/route.schema-example.json`; 실제 녹화가 아닌 합성 schema 예제 |
| Appium 3.1.0 / driver 6.0.0 로딩 | **PASS** | `artifacts/appium-version.txt`, `appium-drivers.txt`, `appium-server-smoke.log` |
| Appium /status readiness 및 서버 종료 | **PASS** | `artifacts/appium-status.json`; device session은 생성하지 않음 |
| Tk 가상 화면 UI smoke | **PASS** | `artifacts/ui-smoke.log`: 창 생성, 합성 PNG 표시, replay 중 버튼 비활성화 |
| Gradle assembleDebug | **PASS** | `artifacts/android-build.log`: BUILD SUCCESSFUL, 마지막 빌드 10초 |
| APK signature verify | **PASS** | `artifacts/apk-signature.txt`: v2 signature verifies, debug certificate |
| APK package/SDK/activity 확인 | **PASS** | `artifacts/apk-metadata.txt` |
| APK INTERNET permission 없음 | **PASS** | `artifacts/apk-permissions.txt` |
| 실제 Windows 실행 | **미실행** | 사용자의 집 PC 연결 이후 필요 |
| 실제 Android 설치/화면/IME/좌표/장치 단절 | **미실행** | 물리 기기 연결 없음 |
| 동일 초기 상태 10단계 × 3회 실기기 재생 | **미실행** | P1 인수 기준 아직 미충족 |
| FLAG_SECURE OFF/ON 실제 가용성 비교 | **미실행** | 검은 화면 원인/입력/계층 가용성 추정 금지 |
| Android instrumentation / emulator E2E | **미실행** | emulator 설치/실행 범위 아님 |

테스트는 정상 기록→재생, intent/result 저장 실패, duplicate start/stop, STOP 이후 입력, locator 다중 일치, geometry mismatch, 좌표 횟수 제한, screenshot 실패와 hierarchy 분리, 단절, 실패 이후 not_run, build/device/initial mismatch, checkpoint timeout, dispatch 후 취소, OS lock/quarantine/crash marker, 동시 API 거부, 임의 action/field/literal/timeout 거부, 좌표 변환 3개 geometry, action ID 경로 이탈 거부, W3C HTTP serialization/명시 udid/cleanup을 포함합니다. 테스트 fixture의 성공이 실제 driver의 성공을 뜻하지 않습니다.

## 환경 문제와 해결 내역

1. 최초 Gradle 시도는 공식 Google Maven에 접근하지 못해 AGP resolution 실패. Java에 클라우드 HTTPS proxy 설정을 전달하여 해결했습니다. `android-build-first-attempt.log`에 실패를 보존했습니다.
2. 다음 빌드는 기존 Java runtime에 javac/jlink가 없어 JdkImageTransform 실패. `android-build-second-attempt.log`에 보존했습니다. Adoptium API 다운로드는 HTTP403, apt download는 로컬 package index 부재로 실패했습니다. 공식 Debian Packages.xz에 기록된 SHA256으로 OpenJDK JDK/JRE 패키지를 검증하여 전용 `.tools`에 풀고 빌드 성공했습니다. exact version/source/hash는 `artifacts/jdk-source.json`입니다.
3. Tk 첫 실행은 DISPLAY 부재로 실패. 공식 Debian Xvfb 패키지를 전용 폴더에 풀었습니다. Unix display socket은 환경 제한으로 실패했으나 같은 프로세스 범위의 가상 TCP display에서 smoke를 통과하고 즉시 종료했습니다. getifaddrs 환경 경고는 남지만 Tk 검증은 성공했습니다.
4. Appium 최초 서버는 로딩까지 성공했으나 별도 실행 환경의 localhost에서는 접근할 수 없었습니다. 서버와 HTTP 확인을 같은 실행 범위에서 수행하여 readiness를 확인하고 종료했습니다.
5. 초기 unit test 1개는 timeout을 failed로 기대했으나 구현이 관찰 부족을 incomplete로 구분하여 실패했습니다. 기대값을 계약과 일치시킨 뒤 추가 회귀 검증을 포함한 최종 27개가 모두 통과했습니다.

클라우드 실행 환경: Python3.12.14, Node24.22.1/npm11.9.0, Appium3.1.0/UiAutomator2 driver6.0.0, Debian OpenJDK21.0.12.1+1-1~deb13u1, Gradle8.9/AGP8.7.3, SDK platform35/build-tools35.0.0, Platform-Tools37.0.1. JDK/tool 설치 캐시와 node_modules는 source ZIP에 넣지 않습니다.

## 남은 제한 및 다음 시험

- 실제 기기에서 설치, screenshot geometry/status bar/IME, locator visibility, USB disconnect, 취소 후 도구 정리를 확인해야 합니다. Windows `msvcrt` lock 분기는 Linux에서 실행하지 않았습니다.
- screenshot 반환 성공은 픽셀이 실제 보인다는 의미가 아닙니다. 검은 화면 원인은 자동 판정하지 않습니다. 좌표 사용에는 사용자의 명시적 가시성 확인이 필요하며 secure 화면 우회는 없습니다.
- hierarchy의 exact text/existence만 postcondition으로 지원합니다. 실제 금융 서비스 성공이나 방어 판정을 하지 않습니다. 존재만 보는 조건은 동작의 의미를 충분히 입증하지 못할 수 있습니다.
- screen snapshot은 polling이며 연속 비디오가 아닙니다. raw physical touch, multitouch, secure keyboard, custom canvas recording은 지원하지 않습니다. screenshot이 없는 화면에서 클릭 녹화까지 지원한다고 주장하지 않습니다.
- 대상 APK를 ADB로 읽어 hash를 얻을 수 없으면 차단합니다. signer digest/전체 DeviceSnapshot/root 판정/secret reference/다기기 이식은 미구현입니다.
- 전체 step wall time은 transport/evidence 호출의 합으로 postcondition timeout보다 깁니다. 각 호출은 유한하지만 즉시 취소는 아닙니다. 불확실성은 quarantine으로 남기고 자동 재전송/자동 해제를 하지 않습니다.
- 동작 중 STOP은 현재 action을 보수적으로 incomplete 처리할 수 있습니다. STOP을 눌렀다고 이미 보낸 입력을 되돌리지 않습니다. UI/worker crash 후 일부 journal만 남을 수 있으며 자동 정상 route 승격이 없습니다.
- 외부 adb/Appium 프로세스 및 손터치를 막지 않습니다. lease는 이 프로그램을 따르는 작업들에 적용됩니다. 테스트 동안 다른 도구로 같은 기기를 조작하지 않아야 합니다.
- dependency lock/checksum이 있어도 모든 OS 도구/SDK revision과 debug signing key까지 동일한 bit-for-bit 재현을 보장하지 않습니다. 새 build hash는 새 기록이 필요합니다.

다음 단계는 Windows에서 명시적으로 APK 설치 후, secure OFF의 10단계 route를 기록하여 RESET→재생 3회를 수행하고 각 run JSON/XML/PNG를 비교하는 것입니다. 이후 secure ON의 관찰 가능 범위를 별도로 검증한 뒤 P1 통과 여부를 판단합니다. proxy/AI/금융 판정 통합은 아직 범위 밖입니다.

## 2026-11-17 미리보기 회귀 검증

Python 3.12/Windows에서 기존 단위·fake HTTP 테스트와 미리보기 회귀 테스트 총 46개를 통과했습니다. 추가 검증은 foreground 이탈, 조회 중 앱 전환, transport 불확실성, 누락/손상 PNG에서 이전 이미지와 입력 매핑 폐기, 정상 프레임으로 회복 및 secure 상태 표시를 다룹니다. 합성 mock 테스트는 실기기 캡처 동작을 대체하지 않습니다.

별도 실기기 진단에서 동일 합성 앱의 FLAG_SECURE ON/OFF와 일반 홈 화면을 ADB/Appium 원본으로 비교했습니다. ON에서는 양쪽 앱 영역이 가려졌고, OFF와 홈 화면에서는 양쪽 원본이 정상 표시됐습니다. P1의 이전 구현은 대상 앱 이탈/연결 오류 후 이전 프레임을 남겨 홈 화면도 검게 보이는 것처럼 오인할 수 있었습니다. 변경본은 해당 프레임을 폐기합니다. 기기 설정과 합성 앱 상태는 진단 후 복원·확인했습니다. 실제 증거와 식별자는 로컬에만 보관하며 저장소에 포함하지 않습니다.

수정된 Tk GUI에서도 실기기 연결 후 secure OFF 합성 로그인 화면 표시, 홈 전환 시 프레임 폐기, 앱 복귀 시 새 프레임·수신 시각 갱신, secure ON 복원을 확인했습니다. GUI 종료 후 hidden API 정책 3개는 기본값, Settings helper 모의 위치 app-op은 default이며, 합성 앱 설정 파일 2개는 시험 전 원본과 바이트 단위로 일치했습니다. helper APK는 승인대로 설치 상태를 유지했습니다.

이 결과는 미리보기 결함과 캡처 경로의 제한된 검증입니다. 10단계 기록·3회 재생 전체 인수시험 통과를 의미하지 않습니다.
