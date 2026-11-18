# 상세 스펙 인덱스와 기능 추적표

> 이 문서는 설계 당시의 기준과 추적 ID를 보존한다. 현재 POC 구현·시험 상태는 [2026-11-18 추적성 점검](../08-poc-traceability.md)을 우선 참조한다. 아래의 당시 “미구현/미시험” 표시는 이후 POC 진척을 취소하지 않으며 제품 완료를 뜻하지도 않는다.

## 목적과 기준

승인된 UI 6장과 사용자의 기존 요구에서 도출한 43개 기능을 제품 구조·오류 처리·수용기준에 연결한다. 검토 범위는 Android 우선 QA 전용 데스크톱 앱이며, 이번 작업은 설계다. 구현/실기기 검증 완료와 구별한다.

- 기준 기능 ID: **F-01~F-43**. 각 문서의 APP/DEV/REC/PXY/CAT/RUN/AI 등 ID는 도메인별 별칭이다.
- UI 출처: UI01 기기 미연결, UI02 기록 준비, UI03 기록 중, UI04 점검 선택, UI05 점검 실행 중, UI06 최종 이력.
- [01 앱/프로젝트](01-app-workspace.md), [02 기기/대상](02-device-target.md), [03 기록/재생](03-record.md), [04 프록시](04-proxy.md), [05 카탈로그](05-catalog.md), [06 실행](06-run.md), [07 AI](07-ai.md), [08 증적/결과](08-evidence-results.md).
- [09 평가항목 18개 커버리지·PoC 게이트](09-checks-poc.md)가 작성되어 18개 항목의 선행조건·증거·범위·fixture 검증 게이트를 확인했다. 아래 09 참조는 작성된 문서에 대한 매핑이다.

## 구현 우선순위 축

제품 기능의 책임 도메인과 평가항목의 E/S/U/N/M을 구별한다. E→S→U→N은 점검 구현 우선순위이고, proxy 수집 기능은 RECORD의 조기 PoC(P2)에서 필요하다.

- P0: 데이터/프로젝트/도구/이벤트/결과 공통 계약 및 합성 fixture.
- P1: PC 입력 캡처→동선→Appium 재생, 기기/대상 상태.
- P2: Python relay 독립화→RECORD/STOP 패킷 수집→조회.
- P3: 첫 E 항목의 독립 Python 도구와 증거·판정. 이후 S/U/N 확장.
- P4: 기존 `docs/07-poc-plan.md`의 **조각 간 전체 통합**이다. 아래는 P4의 하위 검증 단계이며 독립적인 상위 P5/P6를 신설하지 않는다.
  - P4-a fake runtime: scheduler/device lease/watchdog/cancel/recovery를 합성 provider/tool로 검증.
  - P4-b backend adapter: 첫 실제 provider와 두 번째 provider 교체성을 검증.
  - P4-c GPUI 통합: 검증된 기록·프록시·점검 도구·AI를 승인 3탭 UI에 연결.
- iOS→web은 후속 플랫폼. 원본 공식 평가 식별자와 플랫폼 적용은 원본 대조 게이트를 유지한다.

## F-ID → 도메인 문서 추적

`주`는 책임 명세, `연계`는 계약 소비/보완 명세다. 검증 열은 시험해야 할 핵심이며 시험 완료 표시가 아니다.

|ID|기능|도메인|주 문서|연계|단계|핵심 검증|
|---|---|---|---|---|---|---|
|F-01|프로젝트 생성/열기/선택|WORKSPACE|01|08|P0|A/B 프로젝트 정보 혼합 방지|
|F-02|API/relay 부팅·health·종료|APP|01|04/06|P0/P2|port 실패를 정상으로 표시하지 않음|
|F-03|세 탭 전환·상태 유지|APP|01|03/06/08|P4|탭 전환이 작업 시작/종료가 아님|
|F-04|UI 재연결·stale·종료 복구|APP|01|06|P4|cursor replay/snapshot, cleanup|
|F-05|backend/tool/proxy/IDOR 설정|APP|01|04/05/07|P0/P4|유효성 오류·다음 run 적용·비밀 참조|
|F-06|기기 발견·새로고침·선택|DEVICE|02|05|P1|선택 serial만 조작|
|F-07|root/tool capability·보정|DEVICE|02|05|P1/P3|unknown≠stock, 보정≠권한 보장|
|F-08|미러링·PC 입력·좌표 변환|DEVICE|02|03/06|P1|회전/letterbox 변환·입력 충돌 거부|
|F-09|package/APK 입력·일치 검사|TARGET|02|05/08|P1/P3|package/version/hash 불일치 표시|
|F-10|명시적 설치·launch|TARGET|02|03|P1/P3|설치 실패·foreground 확인·무단 초기화 없음|
|F-11|단절·대상 변경 재평가|DEVICE|02|03/05/06|P1/P4|재연결 자동 거래 반복 없음|
|F-12|RECORD 및 공통 경계 시작|RECORD|03|04|P1/P2|중복 요청 한 세션·proxy OFF 표시|
|F-13|입력 action 수집/dispatch|RECORD|03|02|P1|의도/전달/완료·미지원 입력 구분|
|F-14|action 목록/상세|RECORD|03|08|P1|순서/중복·관찰과 입력 구분|
|F-15|STOP/flush/seal|RECORD|03|04|P1/P2|저장 실패≠완료·STOP≠OFF|
|F-16|동선 보존/선택/다시 기록|RECORD|03|05/08|P1|재시작 보존·새 ID·호환성|
|F-17|기본 launch/route 재생|RECORD|03|02/05|P1/P3|초기 상태/단계 postcondition|
|F-18|partial/coverage gap|RECORD|03|04/05|P1/P2|gap이 eligibility에 반영|
|F-19|proxy ON/OFF/status|PROXY|04|01/06|P2|listener 상태·drain·중복 토글|
|F-20|routing/attribution|PROXY|04|02/05|P2|ON≠경유·unknown은 근거 제외|
|F-21|packet 영속 수집|PROXY|04|03/08|P2|chunk≠message·누락/overflow|
|F-22|packet 검색/상세|PROXY|04|03|P2|0건/실패 구분·raw/preview|
|F-23|STOP 경계 트래픽|PROXY|04|03|P2|post-stop response 연결·bounded drain|
|F-24|query/mutation/replay|PROXY|04|07/09|N|원본 불변·상태 불명 재전송 금지|
|F-25|항목 catalog/공식·확장 범위|CATALOG|05|09|P0/P3|18개 제목 추적·HTS 재명명 없음|
|F-26|checkbox/조건/개수|CATALOG|05|02/03/04|P4|조건 미충족 차단·stale 해제|
|F-27|항목 상세·부족 조건|CATALOG|05|09|P4|focus와 선택 별개·disabled 상세|
|F-28|manifest/Skill/version|CATALOG|05|07|P0/P3|최대 3 Skill·schema·snapshot|
|F-29|QA/IDOR 입력·수동 증적|CATALOG|05|04/08/09|U/N/M|A/B 소유·복원 조건·수동 출처|
|F-30|START/preflight/idempotency|RUN|06|05|P4|한 run·불변 plan·조건 재검사|
|F-31|main/item 직렬·lease|RUN|06|07|P4|이전 tool 정리 전 다음 시작 금지|
|F-32|live 이벤트/heartbeat|RUN|06|07|P4|업무 진행≠생존·로그 유실 표시|
|F-33|취소/정리|RUN|06|02/04/07|P3/P4|중지 요청≠정리 완료|
|F-34|watchdog/timeout/retry|RUN|06|07|P3/P4|AI 밖 감시·미확인 부작용 반복 금지|
|F-35|재시작 interrupted recovery|RUN|06|01/08|P4|PID 소유 확인·새 검사 차단|
|F-36|실행 snapshot/입력 통제|RUN|06|01/02/03|P4|기기·route·checkbox 수정 거부|
|F-37|provider capability/adapter|AI|07|06|P4|같은 schema·gateway/cancel 검증|
|F-38|AI 데이터 조회/송신/audit|AI|07|04/08|P4|허용 범위·신뢰 경계·실제 실행 로그|
|F-39|3종 판정/최종화|RESULTS|08|05/06/07|P3/P4|선택 전체 terminal coverage|
|F-40|날짜·시각 이력/검색|RESULTS|08|01|P4|동시각 run 구분·기기 독립|
|F-41|summary/filter/항목표|RESULTS|08|06|P4|모든 패널 동일 run·집계 일관|
|F-42|근거/증적 preview/후속|RESULTS|08|09|P4|missing/corrupt·실행 없는 viewer|
|F-43|저장/hash/schema/용량|EVIDENCE|08|01/03/04|P0|원본 불변·disk full·마이그레이션|

## 추적 레코드와 변경 단위

각 F-ID는 source(UI/사용자 요구), domain, milestone, preconditions, inputs/outputs, states/errors, acceptance criteria, design decision, validation gate를 가진다. 도메인 문서에서 구체 계약을 정의하며 이 표는 연결을 제공한다.

설계 상태(초안/검토/채택), 구현 상태(미구현/PoC/구현), 검증 상태(미시험/통과/실패/차단)를 혼합하지 않는다. 이번 43개 항목은 구현 상태 **미구현**, 기술 호환성 검증 **미시험**이다. 설계 문서에 인수기준이 있다는 사실은 통과한 시험이 있다는 의미가 아니다.

커밋은 기능군 단위로 도출→분류→설계→평가 결과를 묶는다. 도메인 문서의 계약 변경은 이 표와 연계 문서의 영향을 함께 확인한다. 구현 코드/실제 앱/키/패킷 증적을 설계 저장소에 추가하지 않는다.

## 1차 교차검토 결과와 남은 게이트

- 43개 기능 모두 주 도메인 문서에 매핑되었다. 아직 실제 구현 시험은 없으며 스펙 완결성의 최종 판정은 후속 역검토가 필요하다.
- F-29 보완 확인: 05/08에 점검 탭 항목 상세의 수동 자료 제출·검토, 제출자/검토자·시각·manual 출처·원본 참조, 대기/기한/취소, 근거 부족 시 판단 불가능, finalization 전 제출 및 terminal 불변 정책이 반영되었다. 자동 도구 관찰과 수동 진술을 구별한다.
- F-23 보완 확인: 04에서 STOP 응답 drain은 `record_stop_response_drain_ms=2,000ms`, relay OFF 연결 drain은 `relay_off_drain_ms=5,000ms`로 분리했다. 초기 PoC 설정값이며 측정 후 조정 가능하다. 03은 drain/flush 완료 전에 recording completed를 금지한다.
- F-05 설정의 tool 경로/provider/IDOR 필드는 도메인 소유 schema를 참조하고 저장 직전 검증/다음 run 적용/실행 snapshot 불변을 확인한다.
- 09 작성 확인: 18개 제목은 CHK-01~18에 빠짐없이 대응하며 플랫폼 적용·확장/제외 이유·입력/증거·fixture 불명 시 동작과 공통 절차/판정·cleanup 계약을 명시한다. 개별 앱 fixture/정책/oracle과 공식 원본 ID·적용 범위는 구현 전 검증 게이트로 남는다. 공식 범위·ID 대조가 완료되었다고 주장하지 않는다.
- 01~08 상호 상태 이름 중 recording `completed/interrupted/failed`, run terminal/finalization 실패와 evidence 계약을 일치시킨다. UI 라벨은 같아도 서로 다른 객체 상태임을 구분한다.
- 시안의 장식 메뉴·증적 checkbox·중복 proxy·합성 날짜는 별도 기능으로 확대하지 않는다. 제거/예시 판단을 문서에 보존한다.

## 반복 종료 기준

도출→분류→설계→평가의 전체 역검토 회차에서 새 필수 기능 0, 미처리 계약 충돌 0, 모든 gate가 구현 전 검증 과제로 명시되면 현재 범위의 설계 수렴으로 본다. main agent가 미연결/준비/기록/종료/선택/실행/취소/오류/재시작/최종 이력, 무기록 실행/proxy OFF/기기 변경을 재검토해 최종 판단한다. 무한 편의 기능 확장을 목표로 하지 않는다.
