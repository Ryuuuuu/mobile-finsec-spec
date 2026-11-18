# 기록 및 재생 스펙

기능 도출 카탈로그 대응: **F-12~F-18**, proxy 경계 연동은 F-19/F-23. 도메인 ID는 분류용 별칭이다.

## 기능과 UI 경계

REC-001~005. 기록 탭은 입력과 packet 기록만 담당한다. 점검 checkbox/선택 개수/점검 시작은 없다. STOP 후 기록을 저장하고 점검 탭으로 이동하여 동선을 선택한다. 같은 기록을 여러 run에서 참조할 수 있다. proxy ON/OFF와 RECORD/STOP은 다른 lifecycle이다.

## 구조

### 여러 동선 저장·선택·순차 재생 (사용자 요구 반영)

여러 동선을 이름·기록 시각·recording_id로 저장하고 목록에서 복수 선택하여 순서를 지정한다. 선택한 동선은 단일 기기에서 1 → 2 → 3 순서로 실행하며 겹치지 않는다. 하나만 선택하도록 제한하지 않는다. 같은 선택 순서를 다시 실행하면 새 실행 ID를 발급하고 기존 동선·패킷·결과를 덮어쓰지 않는다. 각 동선의 원본 패킷 묶음과 재생 중 수집한 패킷은 출처와 실행 ID를 구분한다.

점검 시작 시 순서와 기록 참조를 고정하고, 앞 동선의 실행·수집 정리가 확인된 뒤 다음 동선을 허용한다. 중간 실패·취소 시 전체 중단/실패 동선 건너뛰기/명시적 재시도 정책은 사용자 확인 전 미확정이다. 결과 불명 상태에서 다음 동선을 자동 실행하거나 이전 동선을 재전송하지 않는다. 기록 미선택의 앱 실행 기본 동선은 기존 계약을 유지한다.

[네이티브 구조 POC](../../pocs/p4-integration/docs/NATIVE-WORKSPACE.md)는 복수 선택과 모의 순차 실행을 검증한다. [P1 결합 GUI 큐](../../pocs/p1-record-replay/docs/REPLAY-QUEUE.md)는 A34에서 두 실제 동선의 순서 변경·반복 재생 및 동선별 P2 수집을 검증했다. GPUI에서 실제 큐를 호출하는 API 연결과 영속 큐 복구는 남은 과제다.

`RecordingCoordinator`가 Device Input Gateway와 Proxy Recorder에 하나의 recording_id 및 시작/종료 boundary를 배포한다. 입력 캡처는 Appium 실행과 별개다. PC 입력을 gateway에 제출할 때 action intent를 먼저 기록하고 dispatch/result를 연결한다. 실제 수행되지 않은 click을 완료된 route step처럼 표시하지 않는다. action intent의 영속 저장이 실패하면 실제 dispatch를 금지한다. dispatch 이후 outcome 기록 실패는 실행 결과 불명으로 남기며 자동 재전송하지 않는다.

`Recording`: id, project_id, device_snapshot, target_snapshot, status, started_at/ended_at, monotonic_start/end, input_coverage, network_coverage, action_refs, packet_refs, artifact_refs, gaps[], schema_version.

`Action`: action_id, sequence, intent_time, dispatch_time, completed_time, type, locator_candidates, coordinates, screen_geometry, wait_condition, input_ref, before/after evidence_refs, execution_status, failure_reason. 관찰된 화면 이벤트와 실제 입력 action은 event_kind로 구별한다. raw 입력 event와 재생용 action을 구별해 한 텍스트 입력을 키 개수만큼 중복 재생하지 않는다.

JSON을 runtime의 버전 관리 형식으로 채택하고 YAML은 사람이 작성하는 설정/manifest에서만 사용한다. 모델에게 임의 실행 코드를 생성해 넘기는 대신 검증된 action DSL을 전달한다. 실제 도구가 DSL을 해석하며 AI가 필요 시 조회한다.

## 기록 상태 전이

`idle → preparing → recording → stopping → completed`.
준비 실패는 `failed`; 진행 중 단절/디스크 실패/수집기 장애는 `interrupted` 또는 `failed`와 coverage gap을 남긴다. 완료된 기록을 다시 수정하지 않고 '다시 기록'은 새 recording_id를 만든다.

- RECORD 중복 클릭은 동일 command_id로 한 세션만 만든다. 다른 command_id로 중복 RECORD가 와도 active recording/device lease가 있으면 busy로 거부하여 두 세션이 생성되지 않는다.
- preparing에서 device/target/저장 가능 여부와 입력 recorder readiness를 확인한다.
- proxy ON이라면 네트워크 수집 준비까지 확인하고 두 수집기에 동일 시작 marker를 게시한다. 단순히 두 thread를 동시에 시작했다고 원자성이 확보된 것으로 보지 않는다.
- proxy OFF 기록은 허용한다. UI에 '네트워크 수집 없음'을 표시하고 network_coverage=none. 동선만 필요한 검사는 이후 가능하다.
- proxy ON이지만 수집기 준비가 실패하면 RECORD 시작을 실패 처리한다. 자동으로 동선-only로 낮추지 않는다. 사용자가 명시적으로 proxy OFF로 바꾼 후 다시 시작할 수 있다.
- 기록 중 새로운 입력은 recording_id/boundary epoch에 연결한다. STOP 수신 시 새로운 입력 수용을 닫고 이미 dispatch한 입력의 완료/실패를 확인한 뒤 finalize한다.
- STOP 뒤 발생한 새 입력을 이전 세션에 포함하지 않는다. 진행 중 요청/응답의 패킷 귀속은 proxy 계약의 경계 정책과 일치시킨다. recording은 입력 정리와 late packet drain/최종 flush가 모두 끝나기 전 completed가 될 수 없다. late response를 포함한다면 기간/connection/correlation 근거와 incomplete를 명시하고 무제한 기다리지 않는다.
- 기록 중 proxy OFF는 relay를 끌 수 있어야 한다. 수집 구간을 닫고 이후 network coverage gap을 남긴다. RECORD 자체를 조용히 완료시키지 않는다. 다시 ON 시 새 segment를 연다.
- 기기/프로젝트/대상 변경은 기록 종료 전 거부한다. 탭 전환으로 기록이 멈추지 않는다. 점검 START는 active recording 종료 전 거부된다.

## 저장·조회

시간은 UTC wall-clock과 monotonic elapsed를 함께 기록한다. UI 표시 timezone은 별도로 저장/표시한다. 장치 시각은 출처와 offset 관찰값을 함께 기록하며 서버 시간과 같다고 가정하지 않는다.

기록 UI는 action 목록·elapsed·packet count를 이벤트로 갱신한다. packet 목록은 page/cursor 기반이며 큰 payload는 선택 시 조회한다. UI 렌더링 지연이 relay 전달이나 action 저장을 막지 않는다. UI 입력 차트/리스트와 packet의 시간 인접성을 보여줄 수 있으나 인과관계라고 단정하지 않는다.

완료 기록은 title(선택), 날짜·시간, package/build, device, 단계수, network coverage를 표시한다. 저장 실패는 completed가 아니다. 부분 기록은 목록에 interrupted로 남기며 기본 재생 선택에서 제외하고 정확한 실패 범위를 보여준다. 부분 기록을 정상 route로 승격하는 편집 기능은 MVP 범위 밖이다.

## 동선 의미와 입력 바인딩

recording 원본 action은 불변이다. route profile에는 `semantic_tags[]`, `checkpoints[]`, `initial_state`, `input_bindings`를 별도 versioned 메타데이터로 둔다. recorder는 화면/입력/packet 관찰에서 후보를 만들 수 있으나 로그인 완료/비밀번호 변경/거래 완료를 자동 확정하지 않는다. 점검 탭의 동선 상세에서 사용자가 후보의 의미와 기대 상태를 확인·조정하고 그 출처와 시간을 저장한다. 기록 탭에 점검 항목 선택 UI를 추가하지 않는다. checkpoint는 관찰할 화면/값/응답 등 predicate 및 확인 출처를 갖고 run snapshot에 포함한다. 의미를 확정할 근거가 부족하거나 재생에서 checkpoint가 충족되지 않으면 해당 의미가 필요한 항목은 비활성 또는 판단 불가능으로 처리한다. 단순 사용자의 태그 지정이 실제 성공 관찰을 대신하지 않는다.

`input_ref`는 literal 공개 QA 값 또는 로컬 변수/secret reference를 가리킨다. 점검 준비 단계에서 binding 이름/자료형/필수 여부를 검증하고 Tool Gateway가 dispatch 직전에 허용된 로컬 값을 resolve한다. 누락·만료·형식 오류가 있으면 입력을 보내기 전에 차단한다. 실행 로그에는 secret 값 대신 reference ID와 resolve 성공 여부만 남긴다. OTP·일회용 token은 녹화 값을 무조건 재사용하지 않으며 fixture가 제공하는 새 값/유효 상태가 없으면 해당 단계 실행 불가로 표시한다.

## 재생 계약

점검 탭의 동선은 기본 앱 실행 또는 완료된 compatible recording이다. 필요 조건: platform/target build(또는 명시적 compatibility)/지원 action/필요 checkpoint/input refs. device 모델이 달라도 locator replay 가능성을 검증하되 좌표 fallback은 geometry/방향 조건이 맞을 때만 허용한다. 추측으로 다른 좌표를 탭하지 않는다.

초기 지원 action: launch_app, tap, long_press, swipe, text_input, key(back/home/recent), wait_for_condition. 각 action은 finite timeout을 갖는다. 임의 shell/code 문자열은 action으로 허용하지 않는다. 미지원 입력은 기록 중 즉시 표시한다.

재생 단계:
1. 기기 lease와 실제 capability를 재검증한다.
2. route의 initial_state/checkpoint를 확인한다. 로그인/로그아웃·QA 데이터 상태가 다르면 자동 데이터 초기화 대신 실패 이유를 보고한다.
3. locator 후보를 순서대로 평가하고 고유 일치 여부를 확인한다. 0개/여러 개면 정의한 fallback 없이는 멈춘다.
4. action dispatch 및 기대 postcondition을 확인한다. sleep만으로 성공을 확정하지 않는다.
5. 단계별 evidence와 결과를 기록한다. 실패 후 남은 단계는 미실행으로 남긴다.
6. 취소 시 dispatch를 중단하고 현재 도구가 종료됐는지 확인한다. cleanup 전 lease를 해제하지 않는다.

한 run 안에서 여러 check가 같은 route를 사용할 때마다 앱/QA 초기 상태를 확인한다. 비밀번호 변경/거래처럼 상태 변경을 동반한 action은 결과 확인 없이 자동 재시도하지 않는다. recording 원본 packet을 실시간 거래 상태로 취급하지 않고 run에서 새로 얻은 evidence와 구별한다.

## 인수 기준

1. RECORD/STOP을 각각 연속 클릭해도 세션/종료는 한 번이다.
2. PC 조작 10단계 synthetic QA route를 동일 초기 상태에서 3회 재생해 모두 기대 postcondition에 도달한다. 단계별 action ID와 증거가 존재한다.
3. Appium/locator 실패 시 해당 단계와 이유가 보이고 나머지 단계가 성공 처리되지 않는다.
4. proxy OFF 기록은 route를 저장하며 network_coverage=none, 네트워크 필수 check는 비활성이다.
5. proxy ON 수집기 준비 실패는 전체 시작을 거부하고 record 성공으로 표시하지 않는다.
6. STOP 전후 식별 가능한 입력/packet fixture에서 경계 정책대로 귀속되고 late/incomplete 상태가 숨겨지지 않는다.
7. 기기 단절/저장 실패 시 partial recording과 gap이 보존되고 정상 완료 목록과 구별된다.
8. 기록 중 탭 변경은 기록을 유지하며 점검 시작은 거부된다. 종료 후 점검 탭에서 완료 동선을 선택할 수 있다.
9. locator 다중 일치, 해상도/방향 변화, 초기 상태 불일치 시 잘못된 탭을 실행하지 않는다.
10. 기록·결과 조회의 UI 지연이 relay hot path를 막지 않는지 P2 부하 fixture로 검증한다.

## 검증 미결

P1은 실제 Appium/미러링 경로에서 허용 action·좌표 변환·locator 품질·보안 키패드·custom canvas 지원 한계를 측정해야 한다. 처음 10단계/3회는 초기 PoC 통과 기준이며 다양한 금융앱에서 일반화됐다는 의미가 아니다. 물리 기기에서 직접 한 터치를 자동 캡처하는 기능은 최초 구현 보장 범위 밖이다. 첫 PoC는 앱 내 PC 미러링 입력만 보장하며 물리 터치 수집은 별도 검증 후 확장한다. 코드/백엔드 라이브러리는 이 문서에서 실제 실행했다고 주장하지 않는다.
