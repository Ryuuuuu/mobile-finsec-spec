# 독립 설계 평가: 1차

## 검토 범위

승인된 UI PNG 01–06의 실제 이미지와 문서 01–07, 사용자 변경 이력을 대조했다. 구현/기기 시험은 수행하지 않았다. 아래는 현재 범위의 필수 상세 명세이며 새 탭, 운영 환경 승인 기능, 자동 대규모 스캐너, 잠금/마스킹 UI를 추가하자는 제안이 아니다.

## 결론

기록 / 점검 / 결과 로그 분리는 유지한다. Python 실행 관리자 + 결정론적 watchdog + 공통 gateway + backend adapter 방향이 적절하다. AI가 스케줄러·프로세스 정리·상태 저장의 유일한 주체가 되어서는 안 된다. 기능 수를 무한히 늘리는 대신 각 UI 조작의 정상·실패·취소·반복·재시작 경로가 계약과 인수기준으로 닫히는 것을 종료 조건으로 삼는다.

## 개선안과 수용 기준

|ID|반례/문제|채택 권고 설계|검증 기준|
|---|---|---|---|
|EV-01|루팅 기기라도 su/Frida 사용 불가; 순정인지 미확인|root observed/override와 tool capability 분리. override는 권한을 생성하지 않음|unknown/권한거부/조건변경마다 올바른 비활성 사유|
|EV-02|package ID만 같은 다른 빌드 분석|artifact hash/version/signer와 설치 앱 snapshot 비교; 암묵 uninstall/data clear 금지|불일치가 preflight에 표시되고 run snapshot에 보존|
|EV-03|proxy ON이나 실제 기기 트래픽 미경유|process healthy / routing / capture / decode capability 분리|0개 packet을 방어 성공으로 간주하지 않음|
|EV-04|TCP chunk를 HTTP 요청으로 오인|raw stream과 decoded message를 구분; decoder가 확인한 필드만 UI 표시|분할/합쳐진 TCP read에서도 원본 보존; 미지원 protocol 명시|
|EV-05|RECORD 반쪽 시작, STOP 경계 손실|session 생성→sink ready barrier→recording. STOP 시 입력 거부, flush/high-watermark, completeness 기록|sink 실패는 시작 성공 아님; stop 전후·inflight 정책 재현|
|EV-06|수집 저장소 full로 조용한 증거 손실|bounded buffer, drop/gap/truncated metadata; relay 전달과 저장 실패 분리|손실이 UI/증적에 보이고 영향 항목 양호 판정 차단|
|EV-07|그림의 '2개 서버'를 전체 2 process로 해석|제품 소유 API/relay 2 service; Appium/AI child는 관리 대상 도구|기동/종료/잔존 프로세스 목록과 책임이 문서화|
|EV-08|기록 또는 점검 중 project/device/app 변경 및 수동 입력 충돌|활성 작업 snapshot 고정; 변경/입력 command gateway busy 거부; overlay 없이 disabled/read-only|반복 클릭/직접 API 요청에도 같은 device 동작 하나|
|EV-09|timeout된 이전 agent가 뒤늦게 명령 수행|attempt_id와 fencing token; 독립 watchdog, process/tool termination 확인|stale tool 호출 거부; 정리 확인 전 다음 항목 불가|
|EV-10|거래 요청 timeout 뒤 무조건 재시도|side-effect operation은 outcome_unknown으로 중지 후 상태 검증; retry policy 명시|네트워크 응답 손실 시 이중 거래 요청 없음|
|EV-11|cancel 또는 crash 뒤 다음 run에 환경 오염|cleanup report와 필요시 recovery_required; 재기동은 중단 판별, 자동 거래 재개 금지|프로세스 잔존/변경 미복원 시 start 차단|
|EV-12|취소/미수행을 양호 또는 이력 누락 처리|execution_status와 verdict 분리; terminal run 최종화, 이유/증거 누락 검증|선택된 모든 항목 accounted for; 양호 집계에 미수행 없음|
|EV-13|결과 A 조회 후 B 선택, 늦은 A 응답 덮어쓰기|run_id + query generation 비교; 일관 snapshot 조회|기기 분리·빠른 이력 전환에도 동일 run 결과/증적|
|EV-14|UI 연결 재개 시 로그 중복/누락|event sequence cursor + snapshot fallback; paginated 목록/virtualized UI|재접속/역순·중복 event에서도 최종 상태 일치|
|EV-15|CLI backend가 자유 shell로 gateway 우회|실제 tool allowlist/권한 경계 검증; 강제 불가능 backend 미지원|직접 adb/shell 우회 시험 실패가 adapter 수용 조건|
|EV-16|패킷/앱 문자열이 agent에게 명령|비신뢰 관측 데이터 분리, scope는 immutable config; 증거 기반 candidate verdict 검증|악성 텍스트가 도구 범위/최종 판정을 변경하지 못함|
|EV-17|동선이 다른 기기·앱·초기상태에 속함|compatibility fingerprint, preconditions, checkpoint; 좌표 fallback 불확실성 명시|앱 버전/방향/locator mismatch 시 명확히 중단|
|EV-18|기록한 인증 token·동적 ID를 영구 재사용|route parameter binding + secret reference + capture freshness; 매 실행 정상 baseline 확인|만료 인증/재사용 불가 nonce는 판단 불가능 사유로 분리|

## 점검별 오판 방지

- OS 변조: 루팅 상태 증거와 서비스 차단 여부 모두 필요. 앱 종료만으로 양호 아님. 순정 baseline 비교가 없으면 그 한계를 남긴다.
- 악성코드 방지/보안프로그램: 특정 프로세스 유무만으로 보호 성공을 단정하지 않는다. 통제된 시험 조건과 관찰 가능한 방어 기준 필요. 실제 악성코드 실행을 기본 요구하지 않는다.
- 프로그램 무결성: 변조 APK가 설치 실패한 원인(서명, 패키징 오류 등)을 무결성 탐지 성공과 구분한다.
- 디버깅: debugger attach 자체 실패와 앱의 탐지·서비스 제한을 구분한다.
- 난독화: 짧은 심볼이나 난독화 도구 흔적만으로 양호 단정하지 않는다. 중요 로직의 범위와 가독성 기준을 정의한다.
- 인증/비밀번호: 기대 서버 상태·정책과 실제 사용자 A/B·계정 상태가 필요하다. UI 경고와 HTTP status만으로 판정하지 않는다.
- IDOR/재사용/무결성: 정상 baseline과 변경된 요청의 실제 소유주/거래 상태를 비교. timeout 또는 동일 status는 성공·실패 판정 근거가 아니다.
- 입력정보 보호/접근매체 발급: 공식 원문 적용성과 자동화 범위가 미확인되면 수동 증적 보완을 명시한다.

## 구현 전 검증 게이트

1. **GPUI 실제 빌드/렌더링:** 승인 PNG는 개념 이미지이다. 네이티브 컴포넌트로 선택·테이블·실시간 업데이트·미러링 영역·한국어 글꼴/DPI를 구현할 수 있는지 Windows smoke test. 현재 공식 설치 안내는 `gpui-kit` crate, MSVC 도구체계, Windows/Linux/macOS별 요건을 제시한다. 버전 pin과 lockfile은 PoC 시 검증한 조합으로 확정한다. [공식 설치 안내](https://gpui-kit.com/docs/installation/)
2. **기록/재생:** Appium은 client/server와 platform driver 구조다. 미러링에 전달된 입력을 자동 수집해주는 제품 계약으로 간주하지 않는다. recorder 소유 입력 경로에서 탭/스와이프/텍스트/back/home의 기록과 replay를 입증해야 한다. [Appium clients](https://appium.io/docs/en/latest/intro/clients/), [drivers](https://appium.io/docs/en/latest/ecosystem/drivers/)
3. **Relay 단독화:** Hawkeye GUI 없이 전달, 선택 기기 routing, 실제 protocol/암호화 visibility, STOP/OFF 동작 검증. 'TCP/TLS 지원'이 응용계층 복호화·HTTP parsing을 보장하지 않는다.
4. **Backend parity:** Claude Code/Codex/local GLM 각각 authentication, tool bridge, streaming, cancellation, output validation을 시험. 공통 capability 최소치 미달이면 선택 disabled 또는 명시적 제한.
5. **평가기준 provenance:** 현재 13 모바일/5 HTS 분류는 저장소의 기존 검토 기록이며 이번 평가에서 원본 workbook을 재검증하지 않았다. 공식 ID·범위·배점은 원본 대조 게이트를 남긴다. 모바일 확장 항목은 공식 항목으로 둔갑시키지 않는다.
6. **iOS future compatibility:** 현재 공식 XCUITest는 Windows/Linux에 제한적 지원을 문서화한다. real device iOS/tvOS 18+, 명시 udid, RemoteXPC, preinstalled 또는 externally managed WDA 등 제약이 있다. 그러므로 '항상 Mac만 가능' 또는 'Windows에서 전체 지원' 어느 쪽도 확정하지 않는다. iOS phase에서 실제 driver 버전·WDA 준비·기기 조합으로 검증한다. [공식 non-macOS 안내](https://github.com/appium/appium-xcuitest-driver/blob/master/docs/guides/non-macos-hosts.md)

## 종료 판단 기준

- 모든 승인 UI control/state가 feature ID와 책임 모듈, 데이터 계약, 인수시험 또는 명시적 제외로 연결됨.
- 반복·실패·취소·재연결·재시작 시나리오가 닫힘.
- 설계 확정과 미실행 PoC 가설을 구분함.
- feature discovery 재검토에서 새로운 필수 기능 0, 평가에서 미해결 설계 모순 0. 남은 구현 검증 게이트는 '검증 완료'라고 표시하지 않음.
