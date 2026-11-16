# 기기 및 대상 앱 스펙

기능 도출 카탈로그 대응: **F-06~F-11**, 실행 중 입력 통제는 F-36. 도메인 ID는 분류용 별칭이다.

## 기능과 범위

DEV-001~004, APPID-001~003. Android USB 실기기 한 대를 선택하여 사용한다. 여러 연결 기기 목록은 제공하되 실제 조작은 한 대만 수행한다. iOS 선택/IPA 입력의 공통 데이터 경계는 준비하되 Android MVP에서 iOS 검사를 지원한다고 표시하지 않는다. 에뮬레이터 자동 설치, root 획득, 탈옥, 보안 설정 자동 변경은 범위 밖이다.

## 구조와 계약

`DeviceAdapter`가 discover/probe/open_view/inject_input/launch_app/inspect_app/stop_owned_tools를 제공한다. 모든 호출은 명시적 device_id와 operation_id를 받으며 첫 USB 기기를 암묵적으로 선택하지 않는다. 조작 호출은 Tool Gateway의 device lease를 통과한다. GUI의 잠금 overlay는 만들지 않는다.

`DeviceSnapshot`: device_id, platform, model, os_version, connection_state, transport, root_observation, capabilities, probe_time, tool_versions. root_observation은 `rooted / stock / unknown` 및 evidence_refs/source를 가진다. 권한 확인 실패를 stock으로 취급하지 않는다. 사용자가 QA 기기의 실제 상태를 알고 수동 보정할 수 있으나 관찰 결과를 덮어쓰지 않고 override/value/reason/time을 별도 저장한다. override는 필요한 root command가 실행된다는 보장이 아니므로 실제 capability probe를 별도로 통과해야 한다.

`TargetSnapshot`: target_id, platform, package_id, version_name/code, installed_build_hash(가능한 경우), artifact_id/hash(파일 입력 시), signer_digest(확인 가능한 경우), identity_match_status(match/mismatch/unverified), launch_component, selection_source, inspected_at. hash를 구할 수 없으면 unavailable 사유를 명시한다. 동일 package명만으로 같은 빌드라고 주장하지 않는다. package/version/build hash/signer digest의 필수 비교 필드가 모두 확인되면 match, 확인된 필드가 다르면 mismatch, 필수 정보를 얻지 못하면 unverified다. unverified는 match가 아니며 static/dynamic 증거를 동일 빌드로 결합해야 하는 절차는 차단한다.

## 기기 목록 및 상태

- `disconnected`: 기기 없음. RECORD/점검 시작 비활성, USB debugging 연결 안내와 새로고침.
- `unauthorized`: 기기 자체 승인 필요 안내. 자동 승인이나 우회를 시도하지 않는다.
- `offline`: 연결은 보이나 명령 불가. 진단/재연결 안내.
- `ready`: probe와 미러링/제어 readiness 확인. 연결됨과 모든 평가항목 실행 가능은 서로 다름.
- `busy`: 기존 recorder/check가 lease 보유. 결과 조회는 가능, 충돌 조작은 API에서 거부.
- `lost`: 기존 ready 기기 단절. 활성 작업은 오류/중단 정리로 전환하고 다른 기기에 자동 연결하지 않는다.

자동 갱신과 새로고침은 같은 discovery 작업을 중복 생성하지 않는다. 연결 목록 변경 시 선택 ID가 사라지면 '기기 연결 해제'로 유지하여 대상이 조용히 다른 기기로 바뀌지 않게 한다. 재연결 후 serial/device identity 및 앱 상태를 다시 probe하고 새 실행은 preflight를 통과해야 한다. 진행 중 작업을 무조건 이어서 실행하지 않는다.

## 미러링 및 입력

기록·준비 화면에서는 PC 표시 화면을 마우스/키보드로 조작할 수 있다. 입력을 recorder 소유 gateway로 전달해 실제 실행 요청과 기록 action의 출처를 일치시킨다. 임의 외부 미러링 프로그램의 입력이 Appium에 자동 기록된다고 가정하지 않는다.

입력 좌표는 view의 letterbox/scale/rotation을 역변환하여 device 좌표로 보낸다. 기록에는 원본 device 크기/방향과 정규화 좌표, 가능한 locator를 저장한다. 화면 크기/방향이 바뀌면 기존 변환을 재사용하지 않는다. 지원하지 않는 multi-touch/보안 키패드 입력 등은 미지원임을 즉시 알리고 재현 성공처럼 기록하지 않는다.

점검 실행 중 기기 화면은 관찰용이다. 수동 click/뒤로/홈/최근 앱 입력은 비활성으로 표시하고 API도 거부한다. 이유 문구는 '점검 실행 중에는 수동 조작할 수 없습니다'이며 자물쇠 overlay를 사용하지 않는다. 실제 단말을 손으로 조작하는 것까지 차단했다고 주장하지 않는다. 관찰된 예상 밖 화면 전이는 route divergence로 기록한다.

## 대상 선택과 APK

설치 앱 목록/검색 또는 package명 수동 입력을 지원한다. 패키지가 없거나 실행 가능한 component를 찾지 못하면 이유와 함께 시작을 차단한다. 실행 component가 여러 개면 선택된 launch profile을 저장한다. 기본 동선은 `launch_app`이며 로그인/거래가 수행됐다고 가정하지 않는다.

APK import는 파일 복사/메타데이터 검증과 설치를 분리한다. import만으로 설치 앱을 바꾸지 않는다. 기존 설치와 파일의 package/version/hash가 불일치하면 정적 분석 파일과 동적 앱이 다르다는 상태를 표시하고 두 대상을 같은 증거로 결합하는 검사는 차단한다. 분석 전용 별도 artifact는 가능하지만 tested_scope에 명시한다.

설치/재설치가 필요하면 변경 대상과 데이터 손실 가능 여부를 표시한 별도 작업으로 수행한다. 설치 또한 호스트 전역 device lease가 필요한 mutating operation이며 recorder/check와 동시에 수행하지 않는다. 설치 완료 후 실제 설치된 package/version/hash/signer를 다시 probe한다. uninstall 후 reinstall이나 앱 데이터 초기화를 자동 fallback으로 하지 않는다. 실행 중 대상 변경은 거부하고 현재 run snapshot을 수정하지 않는다. split APK 등 지원하지 않는 파일 유형은 명확히 거부하며 단일 APK 지원과 혼동하지 않는다.

## 기본 실행 계약

`launch_app(device_id, target_snapshot, reset_policy=none)`를 기본으로 한다. package/launcher 확인→실행 요청→정한 시간 내 foreground/예상 화면 관찰→결과 기록. 실행 요청 전송 성공을 앱 정상 서비스 이용 성공으로 해석하지 않는다. timeout/앱 crash/다른 앱 foreground를 별도 결과로 남긴다. 앱 데이터 초기화는 기본 동작이 아니다.

## 인수 기준

1. 두 기기 연결 시 선택하지 않은 기기로 ADB/Appium 입력이 가지 않는다.
2. unauthorized/offline/unknown root 각 fixture에서 정확한 이유와 비활성 상태를 표시한다.
3. 기기 선택 변경 후 이전 앱 목록·root 상태·비활성 이유가 남지 않는다.
4. 세 화면 크기/회전 fixture에서 view 좌표가 올바른 device 좌표로 변환된다.
5. 실행 중 직접 API로 수동 입력을 보내도 lease 위반으로 거부된다.
6. 기기 단절 후 새 기기를 연결해도 진행 중 검사가 새 기기에 이어지지 않는다.
7. package 파일/설치 앱 불일치는 검사 전에 잡히며 import가 설치나 데이터 삭제를 발생시키지 않는다.
8. 무기록 실행은 선택 package를 launch하고 그 범위의 증거만 생성한다.
9. probe 실패/root override가 actual tool capability 확인을 우회하지 않는다.

## 검증 미결

Android 미러링 transport, Appium driver 및 버전, root probe와 앱 metadata 추출 도구는 P1/P3에서 실제 기기 확인 후 pin한다. root 탐지 자체의 완전성은 보장하지 않는다. UI tree를 제공하지 않는 custom canvas/보안 화면의 locator 추출은 P1 위험 항목이다. IPA/iOS 설치와 호스트 제약은 후속 플랫폼 설계에서 별도 검증한다.
