# 기능 도출 1차: 승인 UI → 구현 스펙 입력 목록

검토 입력: `docs/01-requirements.md`~`07-poc-plan.md`, 승인 PNG 01~06 실제 화상. 기존 요구사항과 각 버튼의 전후 상태를 대조했다. 아래 항목은 설계 후보 목록이며 화면에 없는 임의 편의 기능을 늘리는 목록이 아니다. 최종 설계가 작성되면 역방향 누락 검토를 다시 해야 한다.

## 해석 규칙

- 출처 `UI01`~`UI06`은 승인 이미지 번호, `REQ/ARCH/DATA/POC`는 기존 요구·구조·데이터·PoC 문서다.
- 이미지의 합성 값, 폰트 오탈자, 중복 proxy 토글, 녹색 이력 아이콘을 의미·판정의 규범으로 취급하지 않는다.
- `UI03` 기록 탭에 점검 항목/시작을 추가하지 않는다. 점검 선택과 실행 진행은 `UI04/05`의 동일 탭이다.
- 기능 ID는 추적용이다. E/S/U/N/M 구현 분류 및 공식 평가기준 ID와 별개다.
- 아래 수용기준은 설계 완결성의 최소 기준이다. 성능 수치, 실제 도구 호환성은 PoC에서 확인해야 한다.

## APP / WORKSPACE

|ID|UI·요구 출처|기능과 구체 동작|선행조건|최소 수용기준|
|---|---|---|---|---|
|F-01|공통 상단 프로젝트; DATA|프로젝트 생성/열기/선택. 이름, 로컬 저장 위치, 설정·기록·실행 결과의 소유 범위를 분리한다.|저장 위치 쓰기 가능|A/B 프로젝트를 바꿔도 동선·결과·설정이 섞이지 않는다. 이름은 식별키가 아니다. 실행/기록 중 전환은 거부하고 이유를 표시한다.|
|F-02|공통 하단 API 상태; ARCH|앱 부팅 시 Python API와 proxy 서비스 시작, 준비 상태·실패 원인 표시. 재시도 진입점과 정상 종료 절차.|실행 의존성·설정 유효|프로세스 생성만으로 정상 표시하지 않는다. health 확인 후 준비 상태로 바뀌고, 포트 충돌/실행 파일 없음/응답 없음이 구분된다. 기존 다른 프로세스를 임의 종료하지 않는다.|
|F-03|공통 탭 및 UI01~06|기록/점검/결과 로그 탭 전환과 독립적인 화면 상태 유지.|UI와 API 연결 또는 저장 이력 접근 가능|탭 이동은 recording/run을 중지하거나 재시작하지 않는다. 실행 중 결과 로그에 들어가도 완료된 과거 실행만 본다. 돌아오면 최신 실시간 상태로 복원한다.|
|F-04|공통 상태바; DATA/ARCH|UI–API 연결 상태, 재연결·이벤트 재동기화. UI 종료/비정상 종료와 서비스 정리 정책.|현재 세션 식별 가능|재연결 시 snapshot+이벤트 cursor로 중복/누락 없이 복구한다. 화면이 마지막 상태를 현재 정상으로 오인하지 않도록 stale 표시. 정상 종료는 active 작업의 중단·정리 완료를 확인한다.|
|F-05|UI02/04 설정 아이콘; 모델 독립 요구|프로젝트 설정에서 backend, tool 경로, proxy endpoint, IDOR 프로필 등 필요한 설정을 검사·저장한다.|각 설정 schema 지원|잘못된 값은 필드별 오류로 거부. 적용 시점은 다음 run이며 실행 snapshot은 바뀌지 않는다. 임의 고급 메뉴 확장을 하지 않는다.|

## DEVICE / TARGET

|ID|UI·요구 출처|기능과 구체 동작|선행조건|최소 수용기준|
|---|---|---|---|---|
|F-06|UI01 새로고침/기기 select|연결 기기 목록 탐색·갱신·선택. serial, 모델, OS, online/offline/unauthorized 상태 구분.|ADB 또는 플랫폼 adapter 접근|복수 기기에서 선택한 serial만 제어한다. 미연결/권한 미허용에서는 RECORD/START 불가. 자동으로 첫 기기를 대신 선택하지 않는다.|
|F-07|UI02/04 루팅 badge·info; REQ|기기 capability 검사: root true/false/unknown, OS, Appium/도구 가용성. 수동 보정 필요시 원검출·보정 근거를 보존.|선택 기기 연결|검출 실패를 순정으로 간주하지 않는다. 선택 항목 적합성이 재계산된다. 표시상 root 보정은 실제 권한 성공을 보장하지 않는다.|
|F-08|UI02~05 미러링·뒤로/홈/최근 앱|선택 기기의 화면 수신과 PC 마우스/키 입력 전달. 화면 크기·회전·letterbox 좌표 변환. 입력 경로를 recorder가 소유.|기기 제어 권한, stream 및 input adapter 정상|화면 크기를 바꿔도 의도한 기기 좌표에 입력. 끊긴 화면을 현재 화면으로 표시하지 않음. 검사 실행 중 사용자 입력은 기기 명령 충돌 방지를 위해 거부하되 자물쇠 overlay는 없음.|
|F-09|공통 앱 패키지 select; REQ APK/IPA|설치 앱 목록/패키지 입력과 APK/IPA 파일 입력. 파일 메타데이터·해시 추출, 설치 대상과 실제 앱 식별.|지원 플랫폼, 읽을 수 있는 artifact 또는 유효 패키지|패키지 없음/파일 손상/OS 불일치/설치 앱 버전 차이를 구분. 입력 artifact와 실제 실행 앱 일치 여부를 기록. 이미 있는 앱을 조용히 덮어쓰거나 데이터 초기화하지 않는다.|
|F-10|UI02 준비 화면; REQ 기본 동선|대상 앱 설치가 필요한 경우 설치·상태 확인, package launch 및 실제 foreground 확인. 재설치/초기화는 별도 명시적 동작.|F-09 검증 및 필요한 설치 동의|설치 실패 후 준비 완료로 표시하지 않는다. 파일 입력과 패키지 실행을 같은 것으로 취급하지 않는다. 앱 launch 실패 시 해당 단계/오류가 남는다.|
|F-11|UI01↔02; REQ preflight|기기 연결 해제/재연결/대상 변경 시 기록·점검 선행조건 재평가.|active recording/run 또는 선택 상태|연결 해제 시 신규 입력 중지, 현재 작업의 불완전 범위 보존. 재연결해도 중단된 거래/단계 자동 반복 없음. idle에서 대상 변경 시 맞지 않는 동선·선택을 해제하고 이유를 알린다.|

## RECORD / ROUTE

|ID|UI·요구 출처|기능과 구체 동작|선행조건|최소 수용기준|
|---|---|---|---|---|
|F-12|UI02 RECORD; UI03 REC 시간|RECORD 시작: device/app snapshot, recording_id 생성, 입력·packet 수집 경계를 함께 시작. 녹화가 아니라 구조화 동선 수집이 핵심.|선택 기기·앱 준비, 다른 기기 작업 없음, 저장소 가능|반복 클릭은 하나의 session만 만든다. 시작 전 입력/packet을 새 session에 넣지 않는다. proxy OFF면 동선만 수집됨을 명시하고 기록은 허용한다.|
|F-13|UI03 동선 목록; POC1|tap/swipe/text/back/home/recent/app launch/wait 입력을 순서화하고 dispatch 결과 기록. UI tree/locator와 좌표 fallback의 가능 여부 표기.|recorder가 제어하는 입력 경로|시도한 입력과 실제 전달 성공을 구분. 일반 Appium 사용만으로 다른 미러링 툴/기기 직접 터치를 기록했다고 주장하지 않는다. 지원 불가 gesture는 명시된다.|
|F-14|UI03 액션 행·시각|동선 목록 실시간 표시·선택과 단계 세부 근거 조회. action_id, 순서, 시간, 입력 유형, 결과, 화면 근거.|recording 참조|표시 순서가 안정적이고 같은 action이 중복되지 않는다. 화면 이동 등 관찰 이벤트와 재생할 입력을 구분한다. 큰 목록도 UI 정지가 수집 중단으로 이어지지 않는다.|
|F-15|UI03 STOP; REQ 기록→점검|STOP으로 입력 신규 수집 중단, 진행 중 packet의 종료 경계 적용, 데이터 flush 및 session 봉인. 이후 점검 탭으로 넘어갈 수 있게 함.|active recording|반복 STOP은 안전. STOP 이후 입력이 이전 recording에 붙지 않음. 저장/flush 실패가 완료로 감춰지지 않음. STOP은 proxy OFF와 다르다.|
|F-16|UI04 동선 select; DATA Recording|완료된 동선 보관·목록·선택, 이름/시각/앱·기기 snapshot 표시. 새 RECORD는 새 recording을 만든다.|선택 프로젝트에 기록 또는 기본 실행 옵션|새 기록이 기존 동선을 덮어쓰지 않는다. 저장 후 재시작해도 동선/packet 결합 유지. 현재 앱/빌드와 불일치하면 이유를 보이고 검사를 막거나 명시적 재검증한다.|
|F-17|UI04 기본 앱 실행; REQ|기록 없는 기본 route 생성: 앱 실행만. 기록 route 재생 시 초기 상태/단계 기대조건/timeout 확인.|app 준비, route schema 유효|기본 실행을 로그인/거래 완료로 간주하지 않는다. 재생 실패 시 실패 단계 이후를 성공 처리하지 않는다. 계정·OTP·세션 데이터는 유효성 재확인 없이 반복하지 않는다.|
|F-18|RECORD 예외; DATA/POC|기록의 completeness 상태와 수집 공백 관리: 기기 끊김, proxy OFF, 저장 실패, 지원 불가 입력.|recording 진행 또는 봉인|partial 기록을 정상 완전 기록처럼 표시하지 않는다. gap 범위와 이유를 보존하고 해당 route/packet을 요구하는 항목 eligibility에 반영한다.|

## PROXY / PACKET

|ID|UI·요구 출처|기능과 구체 동작|선행조건|최소 수용기준|
|---|---|---|---|---|
|F-19|공통 proxy toggle/status|Python relay ON/OFF, endpoint 설정, starting/on/stopping/off/error 상태. OFF 시 active connection drain/close 정책.|설정 유효, 해당 포트 사용 가능|UI 즉시 토글 값이 아니라 실제 relay 상태 표시. 반복 토글 멱등. 기록 중 OFF는 수집 공백, 점검 중 사용 중인 relay OFF는 중지/정리 정책 없이 허용하지 않는다.|
|F-20|UI02 packet 패널; Hawkeye|선택 기기/앱 트래픽의 relay 경로 설정·검증 및 수집 범위 식별.|실제 경유 설정과 지원 프로토콜|프로세스 ON과 앱 트래픽 경유 가능을 구별한다. 다른 앱/기기 트래픽을 대상 앱으로 단정하지 않는다. 출처 불명은 attribution unknown으로 남기고 자동 판정 근거로 쓰지 않는다.|
|F-21|UI03 packet 수집/건수|recording_id 기준 송수신 원본·메타데이터 영속 수집. chunk와 논리 메시지, 요청/응답 correlation 구분.|F-12 session, relay 정상|알려진 프로토콜 fixture에서 누락/중복 검증. 해석 실패/암호화/부분 메시지를 정상 HTTP 요청으로 만들지 않는다. UI/AI 지연이 전달 루프를 막지 않는다.|
|F-22|UI01 검색; UI02~03 표·요청/응답/요약|packet 목록 검색·선택 및 request/response/raw/summary 조회. 지원 프로토콜에 맞는 컬럼.|recording 데이터 존재|선택 packet 상세가 일치. 검색 0건과 수집 0건, 수집 실패를 구분. 대용량 payload는 제한·페이지 조회. AI 요약이 원본을 대체하지 않는다.|
|F-23|RECORD STOP 및 proxy OFF; POC2|record 경계에 걸친 트래픽 귀속, flush, 연결 종료 및 불완전 데이터 표기.|active connections/recording|STOP 이전 request/이후 response 처리 규칙이 결정적이며, 별도 post-stop response라도 원래 request 참조를 잃지 않는다. 새 request가 이전 session으로 들어가지 않는다.|
|F-24|N 항목 요구; IDOR|검사 도구용 packet query, copy-on-write 변조/재전송, 응답 비교·상태 검증. 단순 UI Repeater 기능까지 추가하지 않음.|해당 check의 QA 설정·테스트 사용자·대상·복원 조건|원본 packet 불변. 실제 전송 attempt와 outcome 및 신호가 기록됨. 상태 불명 요청을 무조건 재전송하지 않음. 200만으로 거래/권한 성공으로 판정하지 않음.|

## CHECK CATALOG / SELECT

|ID|UI·요구 출처|기능과 구체 동작|선행조건|최소 수용기준|
|---|---|---|---|---|
|F-25|UI04 E/S/U/N 그룹; REQ 18개 항목|평가항목 카탈로그와 분류·적용 범위 관리. 공식 기준 ID·모바일 확장 ID·구현 분류 분리. M/수동 보완을 누락하지 않음.|원문 대조 및 manifest 유효|제공된 각 제목이 적용/확장/보류 중 하나에 대응. UI 예시의 6개만 실제 범위로 오해하지 않음. HTS 전용 항목을 모바일 공식 항목으로 재명명하지 않음.|
|F-26|UI04 checkbox·선택 개수·조건|체크 선택/해제, 분류 접기/펼치기, 현재 선택 수 표시. 항목 적합성 계산 및 비활성 이유.|기기·앱·route/packet·tools snapshot|root만이 아니라 artifact/route/packet/backend/tool 요구조건 모두 반영. 조건 미충족 항목 체크 불가. 선택 후 조건 변경 시 stale 선택 제거/오류 안내. 선택 0개 START 불가.|
|F-27|UI04 우측 선택 항목 상세|항목 목적, 절차 개요, 필요한 조건, 현재 충족 여부와 부족한 준비를 표시.|catalog item 선택|행 선택과 checkbox 선택은 별개. 비활성 항목도 상세를 볼 수 있어 왜 불가한지 알 수 있음. UI의 조건과 API preflight 결과가 동일한 판정 로직을 사용.|
|F-28|DATA manifest/Skill; REQ max3|항목별 common mandatory + AOS/iOS optional loading/versioning/schema 검증. 플랫폼 지원 선언.|유효 manifest, 현재 플랫폼|common 없는 항목은 실행 불가. AOS skill 없음이 곧 unsupported는 아니며 manifest에 의해 판별. 잘못된 skill/schema는 시작 전 원인 표시. run 시작 뒤 파일 변경이 진행 중 기준을 바꾸지 않음.|
|F-29|IDOR 설정 요구; U/N/M|항목별 QA 입력 프로필, 소유자 A/B fixture·동선·resource·검증/복원 조건 및 수동 증적 입력 경로.|항목별 입력 schema|IDOR 자료 부족을 일반 인증 실패와 구분. 자동 검증 불가 항목은 증거 요구·수동 확인 결과를 별도 출처로 남기며 AI가 관찰한 사실로 둔갑하지 않음. 비밀값은 repo 예제에 없음.|

## RUN / AGENT

|ID|UI·요구 출처|기능과 구체 동작|선행조건|최소 수용기준|
|---|---|---|---|---|
|F-30|UI04 점검 시작|preflight 재검사, run 생성과 전체 설정 snapshot, 명령 idempotency, 단일 기기 소유권 확보.|선택≥1, 모든 필수 조건 유효, 다른 작업 없음|더블클릭/요청 timeout 후 재시도에도 run은 하나. 선택 대상/항목이 그 사이 변경되면 과거 preflight를 재사용하지 않음. 부분 run 생성 실패는 조회 가능한 오류로 정리.|
|F-31|UI05 항목 상태·agent·대기열|main AI 및 item agent 순차 실행. 도구 gateway도 하나의 device lease를 검증. 항목 간 사전 상태 확인·정리.|F-30 run snapshot|명령 중첩 0. 이전 하위 도구가 남아 있으면 다음 항목 시작 안 함. 항목 실행 순서는 의존/초기화 제약을 반영하며 E/S/U/N 구현 우선순위를 무조건 runtime 순서로 오해하지 않음.|
|F-32|UI05 live log·heartbeat·main 상태|구조화 실시간 이벤트와 elapsed time, active tool/step, main/item liveness. UI 로그는 실행한 것·입출력 근거 중심.|run active, event stream|heartbeat와 업무 progress 구분. 로그의 잠깐 공백만으로 hang 판정하지 않음. 로그 유실/재연결을 표시. 숨겨진 사고과정 수집은 기능 아님.|
|F-33|UI05 점검 중지; ARCH|cancel 요청→하위 agent/tool 중단→환경 정리→terminal 확인. 중복 요청 처리.|run nonterminal|버튼 누른 즉시 완료로 표시하지 않음. cancel 대기 상태와 실패 원인 보임. cleanup 실패면 다음 기기 작업 차단. 이미 완료된 결과는 보존.|
|F-34|ARCH watchdog; UI05 응답 상태|main crash, item hang, tool timeout, backend disconnect, device unplug 분리 감시. 재시도·실패·중단 정책.|외부 watchdog와 persisted state|main AI 정지에도 제어 가능. 부작용 있는 명령 결과 불명 상태에서 자동 반복하지 않음. 시간값/복구책이 항목·도구 계약에 명시.|
|F-35|DATA/ARCH recovery|앱/API 재시작 후 미완료 run 탐지, 실제 프로세스·device ownership 확인 및 interrupted 정리. 결과 복구.|저장소·식별자 접근|낡은 PID/lock만 믿고 새 작업 시작하지 않음. 비정상 종료 후 거래 자동 재실행 없음. 미완료 항목은 양호 아님. 복구 실패 원인이 이력에 남음.|
|F-36|UI05 실행 중 checkbox/상단 입력|실행 snapshot 불변과 UI 상호작용 정책. active 체크/기기/앱/프로젝트/route 수정 차단, 읽기용 행 선택/탭 이동 허용.|active run 또는 recording|화면 checkbox가 실행 범위를 중간에 바꾸지 않음. 미러링 navigation 키도 경쟁 명령을 전송하지 않음. 사용자가 제거한 잠금 overlay는 다시 만들지 않음.|
|F-37|모델 독립 요구; ARCH|backend adapter 연결 검사·capabilities·start/events/cancel/result. CLI agent와 model API+tool loop 차이 흡수.|선택 backend 인증/필수 capability|backend 교체가 result/route/skill schema를 바꾸지 않음. 지원하지 않는 cancel/resume/tool 호출을 가능하다고 표시하지 않음. provider 오류를 보안 판정으로 변환하지 않음.|
|F-38|DATA model payload/audit|AI에 전달하는 route·packet index와 필요 payload 조회, 송신 데이터 정책, tool 요청/실행/결과 audit.|허용 데이터 범위와 backend 확정|전체 packet dump 무조건 전달하지 않음. 실제 전달 범위 확인 가능. 로컬 비밀 참조를 외부 전송하지 않는 기본 경계와 예외를 명세. 대상 앱/packet 내용을 실행 지시로 신뢰하지 않음.|

## RESULT / EVIDENCE

|ID|UI·요구 출처|기능과 구체 동작|선행조건|최소 수용기준|
|---|---|---|---|---|
|F-39|UI05 나온 판정; UI06 최종 결과|item result schema·증적 검증, 최종 run 봉인. 실행 상태와 판정 독립. 선택한 모든 항목의 terminal coverage.|item terminal 또는 run 중단/완료|판정은 세 값만. 양호/취약은 기준·증거 필요, 판단 불가능 reason 필수. 미실행 항목은 execution=not_run 및 reason으로 남고 양호 집계 안 됨. 취소/실패 run도 terminal history에 존재.|
|F-40|UI06 왼쪽 날짜별 이력·검색|날짜/시각별 scan history 조회·검색·선택, run_id 고유 식별 및 pagination.|프로젝트 저장 이력|기기 연결 없어도 조회. 같은 초에 생성된 run도 구분. 검색 0건/이력 없음/저장소 오류 구분. 진행 run을 최종 결과로 노출하지 않음.|
|F-41|UI06 summary·항목표·filter|선택 run snapshot 요약, 판정별 count, 항목 검색·판정 filter 및 시간 표시.|terminal run 선택|summary/row/details/evidence 모두 같은 run_id. 빠른 이력 전환에서 이전 비동기 응답이 새 화면을 덮지 않음. 미완료/판단불가 집계 정의 일관.|
|F-42|UI06 사유/근거/증적/후속 조치|선택 항목의 최종 근거, 시험 범위·한계, 후속 준비사항, 증적 목록 및 미리보기.|결과와 evidence refs|사유와 원본 근거를 구분. missing/corrupt/지원 불가 형식은 상태 표시, 다른 증적으로 대체하지 않음. 미리보기는 실행 파일/스크립트를 실행하지 않음.|
|F-43|DATA evidence hash/snapshot|증적 저장·hash·참조 무결성, 원본 불변, 스키마 버전·마이그레이션·저장공간 오류 처리.|쓰기 가능 저장소|재시작 후 같은 run 재조회, 원본 변조 검출, artifact 누락 진단 가능. 공간 부족 시 완료 성공으로 감추지 않음. schema 업데이트 전 기존 이력 유지 검증.|

## 필요한 상태 조합 목록

UI에 새 화면 20장을 추가하라는 뜻이 아니다. 기존 탭 안에서 아래 상태의 문구/버튼 가용성과 데이터 귀속을 정의해야 한다.

1. 부팅/준비 중; API 오류; proxy만 실패; 데이터 조회만 가능한 offline 상태.
2. 기기 없음/unauthorized/offline/online; root unknown; 지원하지 않는 OS 또는 tool.
3. 기기는 있으나 앱 없음, APK 읽기 실패, 설치 실패, 설치 앱과 입력 artifact 불일치.
4. 기록 준비: proxy ON 경유 확인/ON이지만 경유 미확인/OFF 동선 전용.
5. 기록 중: 정상/화면 stream만 실패/packet 수집만 실패/기기 연결 해제/저장 불가.
6. STOP 처리 중/봉인 완료/부분 기록/동작 0개; 새 RECORD와 과거 recording 보존.
7. 점검 준비: 선택 0/선택 유효/전부 비활성/기기·앱·route 변경으로 선택 stale/기본 앱 실행.
8. START preparing/running/cleaning/cancelling/timed-out/error/recovery-required/terminal.
9. main 정상+item timeout, main 종료+tool 잔존, proxy 오류+E 검사 계속 가능 여부 등 컴포넌트별 장애.
10. 결과 이력 없음/검색 0/선택 결과 로딩/결과 조회 오류/최종 partial run/증적 없음·손상.
11. active run 동안 과거 이력 읽기와 점검 탭 복귀; 날짜/timezone/동시각 run 구분.

## 기능을 추가하지 않기로 판단할 후보

- UI06 증적 checkbox에는 실제 일괄 동작이 없다. 미리보기만 구현하고 checkbox는 제거 후보로 기록한다. 이를 export/delete 기능의 승인으로 해석하지 않는다.
- 장식성 상단 프로젝트/점검/도구/보기/도움말 메뉴의 모든 하위 메뉴를 상상해 구현하지 않는다. 필수 진입점만 매핑하거나 제거한다.
- packet Repeater/Intruder 화면, 보고서 PDF/Excel export, 다중기기 병렬 실행, scheduler, 계정 클라우드 동기화, 실시간 협업, 결과 비교, 자동 git 업로드는 현 UI/요구의 MVP 필수 기능이 아니다.
- root 탐지 우회, TLS pinning 우회, 모든 암호화 프로토콜 해석을 기본 지원으로 약속하지 않는다. 필요한 도구 capability·PoC 검증 과제로만 구분한다.
- 최종 결과 탭에 실행 중 로그, 잠금/마스킹 버튼, 기록 탭에 선택한 점검 항목은 재도입하지 않는다.

## 반복 종료 기준

1. 각 승인 UI의 사용자 조작 요소가 F-ID/삭제·장식 판정 중 하나에 매핑되어 있다.
2. 각 사용자 요구가 F-ID/명시적 후속 플랫폼·비범위 항목 중 하나에 매핑되어 있다.
3. 모든 F-ID에 선행조건·정상·실패·취소/재연결·영속 데이터·수용기준이 설계 문서에 있다.
4. 모든 START/RECORD/PROXY 명령에 반복 호출과 실제 상태 일치 정책이 있다.
5. 모든 원본 평가항목에 지원/확장/수동/후속 이유가 있고 미선택/미실행/판단불가가 혼동되지 않는다.
6. 발견된 gap이 설계/평가를 거쳐 채택·기각·검증 게이트로 명시되어 있다. 실제 구현 호환성이나 원문 식별자 검증을 끝난 것으로 가장하지 않는다.
7. 최종 변경 문서 역검토에서 위 조건에 필요한 새 기능이 더 이상 나오지 않을 때 도출 단계를 수렴으로 판정한다. 무제한 기능 확장은 하지 않는다.
