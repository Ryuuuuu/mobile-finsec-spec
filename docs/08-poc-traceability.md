# POC → 제품 설계 추적성과 구현 전 시험 게이트

기준: 2026-11-18, 소스 `22057e5`. 이번 작업은 문서·코드·기존 검증 기록 대조이며 기기나 모델을 새로 실행한 시험이 아니다. [43개 승인 기능](spec/00-index.md), [18개 점검 범위](spec/09-checks-poc.md), [설계 수렴 기록](spec-review/03-feature-convergence.md)을 기준으로 한다. 설계 수렴은 구현 완료를 뜻하지 않는다. CHK ID와 공식 평가기준의 원본 ID·버전·적용 범위 대조는 아직 미완료다.

## 상태 읽기

- **부분**: 해당 기능의 일부 POC 코드가 존재한다. 제품 기능 전체 구현을 뜻하지 않는다.
- **모의**: fake provider/fixture/오류 주입. **로컬**: 실제 Python 프로세스·파일·loopback 네트워크 실행. 두 경우 모두 실기기·실모델 검증과 별개다.
- **기기 제한 통과**: 명시된 QA 앱·동선·프로토콜만 과거 실기기 통과. 최신 코드의 모든 변경을 다시 기기에서 검증했다는 뜻이 아니다.
- **미구현**, **미검증**, **중단/대기**를 분리한다. 모든 기능의 **실모델 검증은 없음**이다.
- 시험 개수는 각 POC의 최근 기록이며 합산 제품 통과율이 아니다. 한 fixture를 여러 번 실행해도 별도 제품 점검 항목 수가 늘지 않는다.

## P1~P4 증거와 코드 연결

|단계|존재하는 구현|검증된 범위|남은 제품 차이|
|---|---|---|---|
|P1|[입력/동선 엔진](../pocs/p1-record-replay/pc/core.py), [Appium 어댑터](../pocs/p1-record-replay/pc/adapter.py), [연속 영상/입력 GUI](../pocs/p1-record-replay/pc/mirror.py)|[다중 QA 앱](../pocs/p1-record-replay/docs/DEVICE-MATRIX.md): 기존 10단계+3회, native 4단계+3회, Canvas 2단계+3회. [연속 영상](../pocs/p1-record-replay/docs/DIRECT-MIRROR-INPUT.md): 실제 click/drag+3회, 최대화·Appium 입력 종료 후 영상 유지. 최근 자동 회귀 113 통과|Tk POC, GPUI 제품 아님. Compose/다중화면/잠금/물리 회전·USB 재연결 미검증. 새 통합 영상의 보호 화면 시험 별도 필요. 모든 앱 호환 아님|
|P2|[HTTP relay](../pocs/p2-proxy-relay/relay.py), [WebSocket](../pocs/p2-proxy-relay/websocket_relay.py), [reverse 소유권](../pocs/p2-proxy-relay/device_resources.py)|[기기 QA matrix](../pocs/p2-proxy-relay/docs/ANDROID-APP-VALIDATION.md): HTTP/HTTPS/WS/WSS/OkHttp HTTP·HTTPS, pre/post 제외 및 CA 거부. 최근 로컬 회귀 86 통과|협조 QA 앱의 loopback routing·token 상관관계. 임의 앱 가로채기/OS 앱 귀속/HTTP2·3·QUIC/CONNECT 미지원. 수정된 reverse 소유권의 실기기 재검증 대기|
|P1+P2|[공통 기록 barrier](../pocs/p1-record-replay/pc/combined.py), [GUI](../pocs/p1-record-replay/pc/combined_ui.py), [timeline](../pocs/p1-record-replay/pc/timeline.py)|[통합 기록](../pocs/p1-record-replay/docs/COMBINED-RECORDING.md): native+WebView HTTP 실제 GUI 기록, HTTPS 한 단계 기록·재생 성공. favicon도 보존|WSS GUI는 실제 연결 소실로 중단, replay 미통과. standalone WSS 성공과 구별. P4에 연결되지 않음. 원자적 트랜잭션/일반 앱 인과관계 증명 아님|
|P3|[합성 판정 엔진](../pocs/p3-android-os-tamper/os_tamper), [읽기 전용 probe](../pocs/p3-android-os-tamper/android_probe.py)|[CHK-07 fixture](../pocs/p3-android-os-tamper/docs/VALIDATION.md): 3판정 각 3회. [probe](../pocs/p3-android-os-tamper/docs/ANDROID-READONLY-VALIDATION.md): 실제 로컬 stub/5초 timeout·보고서 검증, 72 통과+1 skip|실기기 probe는 quarantine에서 not_run/관찰 0건. 실제 OS 변조·보호 서비스 oracle 없음. probe는 항상 inconclusive이며 판정 엔진과 자동 통합되지 않음|
|P4-a|[supervisor](../pocs/p4-integration/integration/supervisor.py), [lease](../pocs/p4-integration/integration/lease.py), [history](../pocs/p4-integration/integration/history.py)|[Windows CLI](../pocs/p4-integration/docs/WINDOWS-VALIDATION.md): 10개 실제 로컬 시나리오와 history/validate. [공급자 경계](../pocs/p4-integration/docs/PROVIDER-BOUNDARY-AUDIT.md): 최근 135 통과+1 skip|P2 loopback+P3 합성만 연결. P1 GUI·실제 Android probe·제품 프로젝트 저장소 미연결. 새 supervisor 인스턴스 차단은 OS 프로세스 재부팅 시험 아님|
|P4-b/c|Provider protocol와 fake-a/b, 설계 UI 시안|두 이름은 같은 FakeProvider. 실제 모델 0, GPUI 실행 0|실제 provider별 adapter/인증/과금/원격 취소/격리, GPUI 3탭 제품 미구현|

P3/P4 skip은 Windows 심볼릭링크 생성 권한 부재다. 권한을 바꿔 통과시키지 않았다. 과거 P1 문서의 설정 복원과 이후 사용자가 유지하도록 한 설정은 서로 다른 시험 기록이다. 현재 최종 기기 설정·reverse 상태는 연결 승인 후 읽기 전용 확인 전까지 미확인이다. 미확인을 정리 실패로 단정하지 않는다.

## F-01~F-43 기능별 추적

설계 링크는 해당 기능의 책임 문서다. `모의/로컬`은 위 POC 증거를 참조한다. `없음`은 해당 제품 기능의 검증 증거가 없다는 뜻이다.

|ID|설계/기능|구현|모의·로컬 증거|실기기 증거|제품 전 필수 빈틈/시험|
|---|---|---|---|---|---|
|F-01|[프로젝트](spec/01-app-workspace.md)|미구현|run 출력 폴더만|없음|A/B 프로젝트 격리·열기/선택 G1|
|F-02|[서비스 lifecycle](spec/01-app-workspace.md)|부분 P2|ON/OFF·실패·cleanup|QA relay 사용|제품 API/health/종료 소유권 G1|
|F-03|[세 탭](spec/01-app-workspace.md)|미구현|없음|없음|GPUI 전환이 실행 상태를 바꾸지 않음 G1|
|F-04|[재연결/stale](spec/01-app-workspace.md)|부분 P1/P4|stale/late event·로그|P1 이전 프레임 제거|UI cursor replay·서비스 재시작 G1/G3|
|F-05|[설정](spec/01-app-workspace.md)|부분 CLI/Plan|닫힌 schema|QA 실행 설정만|secret 참조·설정 화면·다음 run 적용 G1/G7|
|F-06|[기기 선택](spec/02-device-target.md)|부분 P1|선택 장치 guard|QA 장치 연결|다중 장치·프로필 선택 UI G2|
|F-07|[capability](spec/02-device-target.md)|부분 P1/P3|unknown/승인 gate/probe stub|과거 helper 설정 확인|실제 probe 수집·unknown 유지 G4|
|F-08|[미러/입력](spec/02-device-target.md)|부분 P1|변환·stale·회전 거부|native/Canvas·최대화|물리 회전·Compose·다중화면 G2|
|F-09|[package/APK](spec/02-device-target.md)|부분 P1|build/split/namespace guard|QA 패키지 동적 launcher|제품 import와 설치 대상 불일치 G2/G5|
|F-10|[설치/launch](spec/02-device-target.md)|부분 도구/CLI|실패·no-reset|QA 설치/launch; 은행 foreground만|설치 UI·여러 launcher·허가 확인 G2|
|F-11|[단절/변경](spec/02-device-target.md)|부분 P1/P2|transport/generation/lease|실제 소실 partial|수정 후 USB 복구·자동 재전송 금지 G3|
|F-12|[RECORD 경계](spec/03-record.md)|부분 P1/P2|중복·ack barrier|HTTP/HTTPS 통합|WSS 재시험·분산 start 실패 G3|
|F-13|[입력 수집](spec/03-record.md)|부분 P1|intent/dispatch/postcondition|native text/tap·Canvas drag|설계 전체 action·IME/키보드 G2|
|F-14|[action 상세](spec/03-record.md)|부분 P1|journal/route|GUI route provenance|제품 목록/상세·관찰 분리 G1|
|F-15|[STOP/seal](spec/03-record.md)|부분 P1/P2|flush 실패·ack loss|GUI STOP·중단 partial|프로세스 강제 종료·디스크 오류 G3/G8|
|F-16|[동선 보존](spec/03-record.md)|부분 P1|불변 원본/호환성|파일 선택 3회 재생|프로젝트 라이브러리·새 ID UI G1/G2|
|F-17|[launch/replay](spec/03-record.md)|부분 P1|초기조건/step 실패|QA reset 후 반복 성공|일반 앱 reset/oracle·WSS GUI G2/G3|
|F-18|[coverage gap](spec/03-record.md)|부분 P1/P2|partial/uncertain|실제 끊김 partial|catalog eligibility까지 연결 G1/G3|
|F-19|[proxy 상태](spec/04-proxy.md)|부분 P2|listener/drain/toggle|QA 경유|제품 서비스 UI·일반 routing G3|
|F-20|[routing/귀속](spec/04-proxy.md)|부분 QA 전용|unverified/token 구분|협조 앱 token|OS 귀속/타 앱 혼입 G3; token만으로 대체 금지|
|F-21|[packet 저장](spec/04-proxy.md)|부분 P2|framing/오류/SQLite|6 protocol fixture|대용량·지원 밖 protocol·손실 G3/G8|
|F-22|[검색/상세](spec/04-proxy.md)|부분 P2 query|저장 재조회|QA 저장 건수|제품 raw/preview UI·오류/0건 구분 G1|
|F-23|[STOP 트래픽](spec/04-proxy.md)|부분 P2|drain/경계|pre/post 제외|실제 지연 response·OFF 교차 G3|
|F-24|[변조/재전송](spec/04-proxy.md)|미구현(조회만)|없음|없음|N fixture·부작용·불명 재전송 차단 G6|
|F-25|[18항목 catalog](spec/05-catalog.md)|설계+CHK-07만|CHK-07 manifest|없음|나머지 17·공식 원본 대조 G4/G5/G6|
|F-26|[checkbox/조건](spec/05-catalog.md)|부분 P4 Plan|선택 ID validation|없음|제품 선택 UI·stale eligibility G1|
|F-27|[항목 상세](spec/05-catalog.md)|미구현 UI|없음|없음|disabled 이유·focus/선택 분리 G1|
|F-28|[Skill/version](spec/05-catalog.md)|부분 P3/P4|common+AOS hash/schema|없음|18항목 loader·실제 provider 소비 G4/G7|
|F-29|[QA/수동 증적](spec/05-catalog.md)|미구현 제품|synthetic fixture 입력만|없음|A/B·수동 검토 provenance·복원 G6/G8|
|F-30|[START/preflight](spec/06-run.md)|부분 P4|중복·immutable Plan|없음|제품 통합·재시작 idempotency G1/G7|
|F-31|[직렬/lease](spec/06-run.md)|부분 P4/P1|generation·attempt fencing|P1 단일 소유; 수정 후 대기|실제 provider/tool 프로세스 소유 G3/G7|
|F-32|[live/heartbeat](spec/06-run.md)|부분 P4|quiet/hang·stream error|없음|실모델 progress 의미·UI 재구독 G7|
|F-33|[취소/정리](spec/06-run.md)|부분 P1/P4|bounded RPC/stream·ack|과거 P1 정상 종료; 단절 미확인|원격 취소 입증·orphan reconciliation G3/G7|
|F-34|[timeout/retry](spec/06-run.md)|부분 P4|main/item/tool/RPC timeout|없음|자동 retry/resume 없음; 부작용 예산 G7|
|F-35|[재시작 복구](spec/06-run.md)|부분 P1/P4|quarantine·새 인스턴스 차단|실제 단절 quarantine|실제 프로세스 kill/재부팅/PID 재사용 G7/G8|
|F-36|[snapshot/통제](spec/06-run.md)|부분 P1/P4|불변 Plan·replay 입력 차단|QA replay|제품 모든 편집 경로 통제 G1|
|F-37|[provider adapter](spec/07-ai.md)|모의만|fake-a/b 동일 구현|해당 없음|실제 첫/두 번째 공급자 G7|
|F-38|[AI gateway/audit](spec/07-ai.md)|부분 P4|proposal 검증·로그|없음|OS 격리·범위 제한·prompt injection G7|
|F-39|[판정/최종화](spec/08-evidence-results.md)|부분 P3/P4|3판정·선택 전체 terminal|보안 판정 없음|실제 oracle·18항목 scope G4/G5/G6|
|F-40|[이력/검색](spec/08-evidence-results.md)|부분 P4 CLI|sealed history|없음|제품 날짜 검색·기기 독립 UI G1|
|F-41|[집계/표](spec/08-evidence-results.md)|부분 JSON|집계 일치|없음|여러 패널 동일 run·rapid selection G1|
|F-42|[증적 viewer](spec/08-evidence-results.md)|부분 validator|손상/경로 거부|사적 QA 증거만|읽기 전용 viewer·missing 표시 G8|
|F-43|[저장/용량](spec/08-evidence-results.md)|부분 P1~P4|hash/schema/쓰기 실패|QA 파일 생성|migration·실제 disk-full/power loss G8|

## E/S/U/N 및 M 점검 항목

분류는 우선순위이며 실행 순서나 판정 완료 여부가 아니다. 제목·primary는 상세 설계의 매핑을 그대로 따른다. 모든 항목의 실모델 검증은 없고, 실제 금융 앱 보안 판정도 없다.

|ID|제목|Primary|검사 구현/모의 검증|실기기 판정 증거|다음 게이트|
|---|---|---|---|---|---|
|CHK-01|거래 인증수단 검증|U|미구현|없음|G6 인증 fixture·승인 oracle|
|CHK-02|거래정보 무결성 검증|N|미구현; P2 수집은 검사 아님|없음|G6 단계별 변조·적용값|
|CHK-03|거래정보 재사용 방지|N|미구현|없음|G6 중복 효력 oracle|
|CHK-04|거래시 소유주 검증|N|미구현|없음|G6 A/B 소유 fixture|
|CHK-05|비밀번호 변경 시 본인확인 절차 수행|U|미구현|없음|G6 변경 적용·복원|
|CHK-06|비밀번호 변경 시 이전 비밀번호 재사용 방지|U|미구현|없음|G6 이력 정책·복원|
|CHK-07|OS 변조 탐지 기능 적용|E|합성 3판정 각 3회; 별도 read-only probe|없음; probe not_run 0관찰|G4 검증된 변조 상태+서비스 oracle|
|CHK-08|악성코드 방지|E|미구현|없음|G4 무해한 탐지 fixture|
|CHK-09|보안프로그램 동작 여부|E|미구현; 모바일 확장 provisional|없음|G4 보호 기능 기대조건|
|CHK-10|보안프로그램 임의해제 방지|E|미구현; 모바일 확장 provisional|없음|G4 허용 해제·복원 승인|
|CHK-11|프로그램 실행 명령줄 내 중요정보 평문 노출 방지|S|S2 APK 합성 문자열 위치 탐지; 원래 실행 명령줄 관찰 미구현|합성 21시험 + 자체 2-DEX/인코딩 QA APK 로컬 분석; 실기기 미실행|G5 허용 실행 관찰·중요정보 기준|
|CHK-12|HTS 구동시 실행 파라미터 재사용 방지|N|모바일 MVP 제외, 카탈로그 보존|없음|HTS 별도 범위 승인 전 실행 안 함|
|CHK-13|이용자 입력정보 보호|U|미구현; P1 password 거부는 자체 안전장치|없음|G6 필드별 보호 요구/관찰|
|CHK-14|프로그램 무결성 검증|E|미구현; APK hash guard는 검사 아님|없음|G4/G5 OS 설치 거부와 앱 방어 구분|
|CHK-15|소스코드 난독화 적용|S|부분 S1: 실제 SDK DEX/smali 추출+합성 판정; 실제 보안 판정 미구현|실제 QA APK 파일 inventory만, 기기/보안 판정 없음|G5 중요 로직·분석 artifact|
|CHK-16|디버깅 탐지기능 적용|E|미구현|없음|G4 attach 성공과 방어 oracle|
|CHK-17|보안프로그램 구동시 최신 업데이트 수행|S|미구현; 모바일 확장 provisional|없음|G5 권위 있는 버전·update fixture|
|CHK-18|접근매체 발급 시 실명확인 수행|M|미구현 수동 검토 흐름|없음|G6/G8 적용 기준·발급 증거|

따라서 E는 CHK-07의 판정 계약 POC만 있으며, S/U/N 자동 검사와 M 제품 흐름은 미구현이다. P1 입력 성공은 U 보안 점검 통과가 아니고, P2 TLS/packet 성공은 N 거래 무결성·IDOR 통과가 아니다. 앱 실행 종료나 검은 화면만으로 보안 탐지를 판정하지 않는다.

## 제품 전 우선순위와 재현 계획

각 시험은 새 비공개 출력 디렉터리에 버전·입력·기대값·실제값·정리 결과를 남긴다. 실기기 설정 변경/QA 데이터 초기화는 해당 시험의 구체 승인 범위에서만 수행한다. 아래는 계획이며 이번 작업에서 실행하지 않았다.

|Gate/우선순위|재현 준비와 절차|통과 기준/차단 조건|
|---|---|---|
|G1/P0 제품 골격|GPUI 3탭+API+프로젝트 A/B를 연결. 기록/실행 중 탭 이동, UI 재시작, 이력 rapid selection, 잘못된 설정 제출|탭 이동은 작업 제어 아님; 프로젝트/run 혼합 0; cursor gap 표시; secret 참조만 저장. 현재 GPUI 미구현이 선행 차단|
|G2/P0 입력 호환|격리 native/Canvas/WebView/Compose QA 앱별 직접 GUI route 기록, fixture reset 후 3회 재생. 물리 회전·letterbox·IME·dialog·잠금·보호 화면을 각각 분리|모든 postcondition 일치 또는 dispatch 전 명확한 거부; 보호 캡처 우회 없음. locator/좌표 성공을 임의 앱 인증으로 확대 금지|
|G3/P0 실제 연결·네트워크|승인된 장치에서 기존 소유 reverse·lease·유지 설정을 먼저 읽기 확인. 수정된 단일 소유권으로 HTTPS/WSS GUI record/replay, pre/post/지연 응답, 서비스 종료·재연결을 각각 실행|WSS 실제 GUI route provenance와 postcondition+token·packet 일치; 중단은 partial, 자동 재전송 0; 소유 mapping만 정리. 물리 USB 시험은 별도 통제. CA 만료 시 새 PKI/APK, TLS 검증 유지|
|G4/P0 실제 E oracle|CHK-07 순정 baseline와 별도 검증된 변조 QA 환경, 빌드 고정, 보호 서비스 허용/차단 oracle 준비. 각 판정 fixture 3회·관찰 불가·timeout·cleanup 실패 분리|환경·원인·서비스 결과가 모두 입증돼야 해당 scope 판정. read-only props만으로 stock/tampered 확정 금지. 변조 환경/승인 부재 시 중단|
|G5/P1 정적/artifact|비밀 없는 통제 APK 쌍과 중요 로직/정책 지정. hash·서명·빌드 일치 확인 후 명령줄/난독화/update fixture 검사|도구 실패는 판단 불가, 파일명만으로 판정 금지; 설치 거부와 앱 무결성 방어 구분. 원본 ID·적용 범위 대조 포함|
|G6/P1 U/N/M|실제 금융 계정 없이 전용 QA 서버·A/B 사용자·소유 resource·거래 카운터·인증/비밀번호 정책 구성. 승인된 입력만 변조/재사용하고 서버 oracle과 복원 비교|첫 요청 결과 불명이면 재전송 안 함; 원본 packet 불변; 실제 효력/소유권으로 판정. fixture/승인/복원 미준비 시 실행 차단|
|G7/P0 공급자·격리|먼저 별도 로컬 fixture 프로세스로 crash/hang/잘못된 JSON/중복 proposal/취소 무시/늦은 완료와 supervisor 재시작 시험. 이후 별도 인증·과금 승인으로 첫·두 번째 실제 공급자 동일 계약 시험|실제 OS 프로세스 소유/종료 확인, orphan 조회, durable idempotency와 retry 예산; 불명 작업 중복 0. fake-a/b 통과는 대체 증거 아님|
|G8/P0 저장·증적|임시 제한 저장소에서 쓰기 실패/실제 용량 부족, subprocess kill 후 재시작, 파일 누락·손상·외부 경로·schema migration, 수동 증거 제출/검토를 시험|불완전 결과 completed 금지; 원판정 불변·integrity 경고; 복구 후 재조회; 사용자 원본/시스템 디스크에 고갈 시험 금지|

### 지금 기기 없이 반복 가능한 기존 회귀

각 POC 디렉터리에서 해당 전용 venv의 `python -m unittest discover -s tests -v`를 사용한다. P2/P4는 localhost socket 권한이 필요하다. P3는 `python -m os_tamper run --input fixtures/pass.json --output NEW_PRIVATE_DIR` 후 `python -m os_tamper validate --output NEW_PRIVATE_DIR`; fail/inconclusive도 각각 새 경로로 반복한다. P4는 `python -m integration demo --scenario normal --output NEW_PRIVATE_DIR`, `python -m integration history --output NEW_PRIVATE_DIR`, `python -m integration validate --run DEMO_JSON_OUTPUT_PATH`를 실행한다. fault scenario 목록과 예상 exit는 P4 문서에 있다. P3 `python -m android_probe --validate --output EXISTING_PRIVATE_PROBE_DIR`는 저장 파일만 검사하며 수집 성공을 의미하지 않는다. 이번 추적성 점검에서는 이 회귀를 재실행하지 않았다.

## 문서 시점 충돌 처리

루트 README와 초기 설계에는 ‘P1/P2만 존재’, ‘Windows/TLS 미검증’, ‘43개 모두 미구현’ 등 당시 상태가 남아 있었다. 본 문서를 최신 구현/검증 추적 기준으로 연결한다. 과거 결과 문서의 수치와 한계는 역사 기록으로 보존하며, 뒤의 follow-up이 어떤 부분만 갱신했는지 위 표로 한정한다. 소스 존재, 시험 통과, 제품 기능 완성을 같은 상태로 합치지 않는다. 실제 화면·식별자·키·사적 로그는 공개 문서에 포함하지 않는다.


### S1 후속 구현 (초기 추적 기준 이후)

[CHK-15 독립 POC](../pocs/s1-apk-obfuscation/README.md)는 P3의 S 확장 실험이며 새 P5가 아니다. 실제 QA APK 두 파일의 구조 관찰은 모두 inconclusive이고, 설치 가능한 DEX가 없는 합성 APK형 ZIP의 증거 계약만 pass/fail/inconclusive 각 3회 시험했다. 19개 테스트 통과. 실제 디컴파일·난독화 판정·manifest/Skill/catalog 통합은 미구현이므로 위의 제품 S 검사 미완료 결론은 유지된다. [검증 기록](../pocs/s1-apk-obfuscation/docs/VALIDATION.md) 참조.


### 실제 DEX 추출 후속

[S1 실제 SDK 검증](../pocs/s1-apk-obfuscation/docs/DEX-VALIDATION.md): 동일 R8 8.9.27로 만든 직접 작성 QA APK 2개에서 class/member와 선택 클래스 smali를 실제 추출했다. 이름 변경은 mapping과 일치했고 조건 2개·QA 문자열 3개는 양쪽에서 관찰됐다. 보안 판정은 양쪽 모두 inconclusive다. 28개 회귀 통과와 실제 SDK 추출을 구분하며, 이전 ‘실제 분석 미구현’ 중 DEX 근거 추출 부분만 갱신한다. 의미 분석·실제 앱 보호 판정·서명/Android 실행·제품 통합은 여전히 미검증/미구현이다.

S1 [내구성 후속](../pocs/s1-apk-obfuscation/docs/DEX-DURABILITY.md): 실제 두 DEX/24 MiB 패딩 QA APK 추출, 크기 제한 거부와 강제 JVM timeout을 검증했다. 37개 회귀 통과. native/WebView/resource는 명시적으로 미분석이며, 패딩 APK는 대형 코드/메서드 성능 시험이 아니다.

S1 [자원 예산 후속](../pocs/s1-apk-obfuscation/docs/RESOURCE-BUDGETS.md): 기본 32 MiB는 유지하되 명시적인 64 MiB 예산으로 약 36 MiB 패딩 QA APK의 실제 SDK 추출을 확인했다. 스트리밍 ZIP/해시 처리, 압축·메타데이터·디스크·시간·심볼 상한과 부분 실패를 검증했고 51개 회귀가 통과했다. 금융 APK 표본 호환율, 대형 코드 성능, 전체 프로세스 RSS 보장은 측정하지 않았다.

### S2 모바일 정적 확장 (2026-11-18)

[S2 범위와 원래 CHK-11 차이](../pocs/s2-apk-plaintext/README.md), [검증 결과](../pocs/s2-apk-plaintext/VALIDATION.md). 공개 합성 marker의 APK 바이트 위치만 탐지합니다. 원래 명령줄 점검은 미실행/판단 불가능이며 금융 앱 평문 노출 평가 완료가 아닙니다.

S2 1.1은 UTF-16LE/BE 고정 샘플 표현 및 결과 이름 해시화를 추가했습니다. 실제 2-DEX QA APK의 6개 위치를 검증했지만 문자열 의미 분석·compiled resource 구조 추출·원래 명령줄 관찰은 미실행입니다.

### P3 실기기 비교 재개 준비 (2026-11-18)

[비교·오류·재개 명세](../pocs/p3-android-os-tamper/docs/DEVICE-COMPARISON-RESUME.md)와 순수 준비 gate를 추가했습니다. 전체 85시험 중 84통과/기존 권한 관련 1skip. 정상·변조 상태 근거 및 같은 보호 서비스 oracle을 fixture로 검증했으며 실기기 비교는 미실행입니다. 준비 gate는 자동 실행/보안 판정을 하지 않습니다.

### P4 local HTTP preparation (2026-11-18)

[Ollama loopback adapter](../pocs/p4-integration/docs/OLLAMA-LOCAL-PREPARATION.md): 6 local mock HTTP tests passed; full P4 142 tests / 141 passed / 1 existing privilege skip. Real model and Supervisor admission are not verified/enabled. Cancellation after submission remains unknown with no automatic retry; durable recovery integration remains pending.

### Active scope change: structure only (2026-11-18)

The user authors assessment skills/tools with skill-creator. Stop check-content/tool/verdict implementation and testing. [Current structural scope](../pocs/p4-integration/docs/STRUCTURE-ONLY-SCOPE.md) covers opaque common/platform skill delivery, sequential orchestration, exclusivity, liveness/error monitoring and provider adapters. Historical check-specific results remain historical; user skills are not validated by them.

### Structural Supervisor separation

[Active mock-only runner](../pocs/p4-integration/docs/STRUCTURAL-SUPERVISOR.md) now loads and delivers opaque common/AOS/iOS snapshots, runs items sequentially under a synthetic-device lease, and records missing/failed/timed_out/cancelled/completed separately. It does not import P3 judgement; legacy aliases are preserved only for historical paths. Real device/model execution remains unverified.

### Recording-reference structural handoff

[Common-ID recording contract](../pocs/p4-integration/docs/RECORDING-CONTEXT.md) passes synthetic P1 route/P2 packet references to selected sequential mock agents and persists independent collection/execution states. 54 structural tests passed. Real artifact mapping/replay/capture/model execution is not implemented or validated by this change.

### P1/P2 source-format structural handoff

[Offline artifact reader](../pocs/p4-integration/docs/ARTIFACT-HANDOFF.md) reads synthetic files produced by the P1 JSON writer and P2 SQLite Store. 61 structural tests passed; missing/corrupt/partial/version/unsealed states and detached sequential handoff are checked. Raw packet BLOBs, real-device replay/capture and actual model execution remain outside this test.

### Scoped packet-byte structural access

[On-demand packet access](../pocs/p4-integration/docs/PACKET-ACCESS.md) allows selected mock executors to read synthetic request/response bytes by common record ID and packet ID. Grants are fenced/revoked, bounded and independent of collection completeness. Raw data is not persisted; OS/model gateway isolation and real packet acceptance remain unverified.
