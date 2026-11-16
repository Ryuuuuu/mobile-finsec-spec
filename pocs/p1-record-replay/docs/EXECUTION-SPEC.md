# P1 실행 명세 — 2026-11-16 UTC

가설: recorder가 소유한 PC 입력 경로에서 먼저 intent를 영속화하고 Appium UiAutomator2로 전송하면, 합성 Android 앱의 짧은 동선을 검증 가능한 JSON으로 기록·재생할 수 있다.

범위: 로그인 → 메뉴 → 모의 이체 입력 → 확인. package `dev.finsec.poc`, 실제 금융 서비스·계정·네트워크 권한 없음. PC screenshot polling/Tk UI, tap/swipe/text/back/wait. 물리 손터치 녹화, proxy, AI, 금융 판정, GPUI, iOS, 외부 앱 지원 제외.

준비: 명시적 Android serial, USB debugging 승인, 테스트 APK 수동 설치, Appium localhost 서버, UiAutomator2. Python 3.12/Tk, Node 22, JDK 17 또는 21, SDK 35. 실기기와 사용자 Windows PC는 지금 접근하지 않는다. reset/secure 설정은 기록 밖에서 사용자가 명시적으로 수행. 재생이 자동 reset하지 않는다.

계약: schema_version=1; session/run/action/event ID, UTC 및 monotonic elapsed; network_coverage=none. immutable 완료 route + append-only intent/result journal + 별도 replay 결과. 허용 DSL만 수용하고 임의 shell/code 금지. target build versionCode=1/versionName=1.0 및 설치 APK SHA256 비교; exact package allowlist. locator는 resource-id만, 고유 일치 필수. 좌표 fallback은 사용자 opt-in, 동일 geometry/rotation, 화면 확인 가능 시 최대 3회. timeout 1~15초, transport timeout 유한. dispatch 전 intent fsync 실패 시 입력 금지; 결과 저장 실패 시 재전송 금지.

입출력: `python -m pc.ui --device SERIAL --package dev.finsec.poc`; outputs/<UUID>/{events.jsonl,route.json,result.json,evidence/}. 텍스트는 공개 QA literal만(예: qa-user, qa-pass, DEMO-001, 1000). 실제 비밀 입력 금지. wait condition은 resource-id 존재 및 선택적 exact text. 자동 의미 추정 없음. 매 action 이후 사용자가 지정한 postcondition을 관찰하며 timeout은 실패.

실패/정리: active device lease로 기록·재생 중복 거부; STOP은 새 입력을 닫고 현재 작업 종료 뒤 finalize. cancel/disconnect/observation 부족은 incomplete/failed 및 gap, 남은 단계 not_run. timeout 후 도구의 종료가 불명하면 lease 유지하고 재시작/재실행 차단. UI tree/screenshot/input 성공 여부를 각각 기록; 검은 화면은 원인 미확정으로 표시. crash journal은 completed route로 승격하지 않는다.

검증: unit + fake Appium HTTP integration으로 DSL/초기상태/locator 모호성/geometry/중복/영속 실패/실패 뒤 미실행/timeout 검증. Android debug APK build 별도. 실기기는 집에서 동일 reset 상태 10단계 route를 3회 재생, 각 단계 ID 및 postcondition 필요. secure OFF/ON에서 image/hierarchy/input 각각 가용성 비교. 지금 실기기 결과는 미실행으로 보고.

근거: Ryuuuuu/mobile-finsec-spec docs/spec/03-record.md (862121a), docs/07-poc-plan.md (5275039), docs/spec/02-device-target.md (698747e). 설계 저장소는 변경하지 않는다. 다음 결정은 실기기 좌표/locator 품질·secure 관찰 결과 이후.
