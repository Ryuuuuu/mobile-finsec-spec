# 10. 관찰형 동선 체크포인트와 읽기 전용 증적 검토

상태: 2026-11-19 사용자 승인 요구를 반영한 **설계 명세**. 전체 수용 계획은 아직 완료하지 않았으며 제한된 합성 구조 시험은 문서 끝의 후속 POC와 구분한다. 기존 QA 녹화·순차 재생 POC의 성공이 이 명세 전체의 구현 성공을 뜻하지 않는다. 기존 검사 Skill 내용·도구 선택·취약점 판정 로직은 작성하거나 시험하지 않는다.

관련: [기록/재생](03-record.md), [실행·취소](06-run.md), [AI 경계](07-ai.md), [증적/결과](08-evidence-results.md), [현재 POC 증거](../08-poc-traceability.md).

## 범위와 책임

이 모드는 승인된 자체 QA 동선을 정상 순서로 재생하면서 계획된 화면 상태와 이벤트의 증적을 수집하고, 고정된 자료를 읽기 전용으로 검토한다. 공격 실행, 취약점 재현, 우회, 실제 인증·거래 조작 또는 그러한 도구 연결 설계는 포함하지 않는다. 기존 AI 문서의 더 넓은 도구 실행 항목은 이 모드의 권한으로 상속되지 않는다.

|주체|책임과 제한|
|---|---|
|메인 AI|재생 **이전**에 선택 점검과 모든 선택 동선의 적용 관계 및 관찰 계획을 제안. 근거 없는 단계/조건을 만들어 실행하지 않음. 계획 작성 실패·timeout은 실행 전 상태로 표시하며 자동 재생하지 않음.|
|점검 탭/사용자|동선 순서, 점검별 적용/제외 이유, 단계·전후 이벤트, 기대 화면, 필요한 증적과 제외 필드, 버전·한도·취소 정책을 미리 확인하고 계획 해시를 승인. 기록 탭에 점검 항목을 넣지 않음.|
|재생 엔진/호스트|승인된 불변 계획과 실제 단계/조건을 검증하고, 단일 기기 lease 아래 선택 동선을 1→2→3 순서로 실행. 관찰·수집·저장 경계와 재생 상태를 소유. AI 응답으로 다음 기기 동작을 결정하거나 기다리지 않음.|
|하위 에이전트|해당 점검·동선·시도에 배정된 **봉인된 증적 묶음**만 읽기 전용 검토. 기기/셸/네트워크 조작 권한 없음. 새 캡처·재생·재시도·상태 변경을 요구하거나 실행하지 않음.|

읽기 전용은 프롬프트 약속만으로 성립하지 않는다. 호스트가 다른 실행 자료와 기기·셸·네트워크 접근을 차단했음을 별도 구조 시험으로 확인하기 전에는 해당 검토 실행을 unavailable로 둔다. 이 문서는 구체 도구 연결을 추가하지 않는다. 외부 모델 전송은 별도 승인된 데이터 정책이 없으면 허용하지 않는다.

## 불변 계획과 적용 범위

점검별 관찰 시점은 사용자가 작성하는 검사 스킬 본문과 분리된 버전 메타데이터로 선언한다. 조건 화면/상태 또는 이벤트, 전후 phase, 필요한 비민감 증적 종류를 포함하며 실행 명령이나 도구 지시를 담지 않는다. 계획 미리보기는 동선 버전·선택 occurrence·단계와 매칭 근거를 표시한다. 후보 없음은 unmatched, 여러 후보는 ambiguous이며 임의로 첫 후보를 고르지 않는다. metadata 변경도 승인 해시에 반영한다. [합성 메타데이터·매칭 계약](../../pocs/p4-integration/docs/OBSERVATION-TIMING-METADATA.md)은 고정 QA 이벤트에 한정되며 실제 스킬·모델·앱 연결이 아니다.

```text
ObservationPlan
  schema_version, project_id, plan_id, plan_revision, plan_hash
  selected_check_ids[], ordered_routes[]
    recording_id, route_version, route_content_hash, selection_occurrence
  applicability[]
    check_id, recording_id, selection_occurrence
    applicable | not_applicable | unknown, reason
  checkpoints[]
    checkpoint_id, check_id, recording_id, route_version, route_content_hash
    selection_occurrence
    step_id, event_phase (before_dispatch | after_postcondition | route_end)
    expected_screen_state, condition_schema_version
    required_evidence_types[], permitted_fields[], excluded_fields[]
    capture_deadline_ms, max_bytes, required_for_review
  review_deadline_ms, queue_limit, storage_limit, cancellation_policy_version
  approved_plan_hash, approved_at, approval_source
```

`checkpoints[].selection_occurrence`는 `ordered_routes[]`의 정확한 선택 인스턴스를 참조한다. 같은 recording/version을 반복 선택해도 합치지 않는다. 현재 Python POC의 `occurrence` 필드가 이 값에 해당하며 P1 브리지는 0부터 시작하는 큐 위치로 바인딩한다. 첫 선택에만 증적이 있으면 커버리지는 1/2이고 두 번째 누락 사유를 보존한다. 같은 이벤트 재전달은 새 선택 인스턴스가 아니다. [반복 선택 회귀 근거](../../pocs/p4-integration/docs/P1-OBSERVATION-BRIDGE.md)를 참조한다.

미리보기·실시간 진행·최종 결과의 각 행은 recording ID, 버전, 선택 실행 번호, 단계와 전후 이벤트를 함께 표시하여 반복 선택을 구분한다. 내부 `selection_occurrence` 0/1은 변경하지 않으며 사용자 화면에는 `execution 1/2`로 표시한다. 번호가 없거나 유효하지 않으면 추정하지 않고 unknown으로 표시한다. 같은 ID/버전/단계를 두 번 선택하는 현재 UI fixture는 첫 실행(내부 occurrence 0)에만 증적이 있고 두 번째(내부 occurrence 1)는 누락이다. 두 행을 분리하고 전체 커버리지는 1/2로 유지해야 한다. 이전 occurrence 1 증적 사례는 두 번째 실행의 증적이었으므로 첫 실행 증적 요구의 수용 근거로 쓰지 않는다.

단계 ID는 동선 버전 안에서 안정적이어야 한다. 화면 상태는 관측 가능한 QA 상태 조건으로 표현하고 임의 실행 문자열을 넣지 않는다. 모든 선택 점검 × 선택 동선(반복 선택 occurrence 포함)에 적용 관계를 남긴다. 관련 동선 하나만 대표로 고르지 않는다. 적용 여부가 unknown이면 공백으로 표시하고, 근거 없이 not_applicable로 줄이지 않는다. 같은 체크포인트가 여러 동선에 해당하면 **모든 해당 동선에서 별도 증적과 결과 행**을 만든다.

계획 승인 뒤 동선·체크포인트·점검·조건·수집 필드·한도가 바뀌면 새 revision/hash와 실행 전 재확인이 필요하다. 실행 중 교체하지 않는다. 동선이 없거나 단계가 존재하지 않거나 버전이 다르면 계획 검증 오류이며 대체 동선을 몰래 실행하지 않는다. 이전 결과 검토는 그 당시 버전으로 유지한다.

## 이벤트, 수집과 재생 비차단

`review_deadline_ms`의 시작점은 각 봉인 증적을 검토 큐에 등록하는 호스트의 단조 시각이다. 태스크 스케줄 대기와 검토 락 대기를 모두 포함하며, 검토 시작 때 예산을 새로 주지 않는다. 등록 시각과 절대 deadline을 `review_queued`에 기록하고, 실제 검토 시작 직전에 deadline을 다시 확인한다. 이미 만료됐으면 검토기를 호출하지 않고 `REVIEW_QUEUE_EXPIRED`로 끝내며 `review_started`를 남기지 않는다. 시작 이벤트를 기록한 뒤 남은 예산이 만료되면 `REVIEW_TIMEOUT`이다. 둘 다 증적은 보존하고 판단 불가능 이유를 구분하며, 재생 실패나 증적 누락으로 바꾸지 않는다.

등록/시작/종료 이벤트 저장 실패는 정상 검토 완료로 숨기지 않고 최종화 실패로 처리한다. deadline은 실행 허용·만료 판정의 상한이며, 취소 정리나 동기 파일 I/O가 그 시간 안에 반드시 종료된다는 보장은 아니다. 현재 협조적 가짜 검토기 POC는 재생 소유권을 먼저 해제하고 검토 정리를 기다린다. 실제 비협조 프로세스의 강제 종료·복구는 별도 미구현 범위이다. 단조 시각은 같은 실행 안에서만 비교하며 재시작 후 그대로 재사용하지 않는다.

POC 결과의 `review_timing=enqueue-deadline.v1`은 이 구분을 표시한다. 이 필드가 없는 과거 `REVIEW_TIMEOUT`은 큐 대기와 실행 중 만료가 섞인 구형 결과이므로 소급 재분류하지 않는다. 소비자는 새 `REVIEW_QUEUE_EXPIRED` 사유를 보존·표시해야 하며, 모르는 사유를 성공으로 취급하지 않는다.

비차단의 대상은 **AI 응답 대기**다. 증적 취득은 다음 화면 변경 전에 짧은 제한 시간 안에 불변 스냅샷으로 고정해야 한다. 취득 실패는 별도 사유이며 나중 화면으로 보충하지 않는다. 재생 완료, 검토 대기, 최종화는 별개 상태다. 필수 동선 둘 중 하나만 증적이 있으면 1/2 커버리지를 표시하며 점검 전체 양호나 통제 강제를 뜻하지 않는다.

엔진 이벤트는 `run_id, replay_attempt_id, queue_position, selection_occurrence, recording_id, route_version, step_id, phase, event_id, monotonic_sequence, utc_time`을 가진다. 관찰 이벤트와 입력 실행 결과를 구별한다. before_dispatch 증적은 입력 이전 시점, after_postcondition은 조건 확인 뒤 시점이라는 출처를 남긴다. 적시에 관측하지 못한 후속 화면을 이전 화면 증적으로 이름 붙이지 않는다.

수집은 엔진이 경계에서 얻은 허용된 상태 스냅샷을 bounded 큐에 인계하고 봉인한다. AI 완료를 기다리는 동기 호출을 재생 경로에 두지 않는다. 수집 자체도 승인된 짧은 한도 내에서만 시도하며 queue full/timeout/storage error는 공백 이벤트로 남긴다. 해당 관찰 실패 때문에 무제한 대기하거나 동선을 자동 재시도하지 않는다. 입력·postcondition·기기 실패의 기존 중단 규칙은 별개로 그대로 유지한다. 증적 기록 기능 자체가 실패해 안전한 실행 이력을 유지할 수 없는 경우에는 [실행 계약](06-run.md)의 실패 최종화로 정지하며, 비차단을 이유로 무기록 실행을 지속하지 않는다.

하위 검토는 봉인된 자료만 받아 항목별 순차로 수행한다. 재생과 검토의 완료 시각은 분리한다. 재생 종료 뒤 검토가 남으면 점검 탭에서 review_pending으로 표시하고, 검토 deadline이 끝나면 timeout으로 마감한다. AI hang/응답 지연은 기기 lease를 계속 잡거나 다음 승인 동선 실행을 늦추는 원인이 아니다. 검토 deadline은 무한 연장하지 않는다.

안정적 중복 제거 키는 다음 구조 필드의 canonical encoding에 대한 hash다. 시간이나 표시 이름으로 만들지 않는다.

```text
project_id + run_id + replay_attempt_id + plan_hash + check_id
+ recording_id + route_version + selection_occurrence
+ step_id + event_phase + checkpoint_id + evidence_kind
```

재전달된 동일 이벤트는 같은 키로 한 번만 등록한다. 같은 키의 내용 hash가 다르면 충돌/손상으로 보존하고 덮어쓰지 않는다. 새 명시적 재생 시도는 새 attempt ID이므로 이전 증적을 대체하지 않는다. 공통 blob을 중복 제거하더라도 각 동선/점검의 독립 참조·상태·보존 수명은 유지한다.

로그에는 plan_validated/approved, checkpoint_reached, condition_matched/mismatched, evidence_sealed/gap, review_started/completed/timed_out, cancelled, finalized 이벤트와 이유 코드·참조·버전을 남긴다. AI의 숨겨진 사고과정이나 민감 원문은 로그에 넣지 않는다. 늦게 도착한 이벤트는 현재 run으로 섞지 않고 해당 attempt와 종료 시점에 따라 별도 표시한다.

## 증적과 개인정보

모든 해당 동선 보존은 **승인된 최소 관찰 증적을 동선별로 보존**한다는 뜻이지 전체 화면·패킷·입력 원문을 무조건 저장한다는 뜻이 아니다. 비밀번호·인증값·토큰·개인 식별값·민감 입력 및 원본 화면/원본 패킷은 이 검토 묶음에서 제외한다. 허용 필드의 상태 요약·비민감 QA 영역 등 파생 자료만 등록하고 수집 방식·제외 범위·원본 미보존을 명시한다. 민감 정보가 섞이지 않았음을 확인할 수 없는 자료는 저장/전달하지 않고 `EVIDENCE_PRIVACY_EXCLUDED`로 남긴다. 보호 화면 캡처 제한을 우회하지 않는다.

증적 manifest에는 계획/동선/단계/시도 참조, 출처 이벤트, media type, bytes, content hash, 완전성, 제외 이유와 봉인 시각을 기록한다. 봉인 후 파일은 불변이다. 원본 P1 동선과 P2 기록은 변경하지 않고 각각의 ID/버전/coverage를 참조한다. 기존 기록 패킷과 이번 재생 패킷을 같은 자료로 대체하지 않는다. 증적의 수집 시각이 맞는다는 사실만으로 앱 요청의 인과관계나 OS 앱 귀속을 확정하지 않는다.

실제 기기 식별자·화면·패킷·개인 데이터는 공개 Git에 넣지 않는다. 검토 결과의 자유 문장도 같은 제외 정책을 적용한다. 누락/해시 불일치/손상/지원하지 않는 형식이면 검토 범위를 줄였다는 사실과 이유를 보존한다.

## 상태와 최종 요약

수집 상태, 검토 실행 상태, 평가 결과를 각각 저장한다. 실행 성공이 양호를 의미하지 않는다. 아래 코드들은 취약점 판정 규칙이 아니라 공백의 구조적 분류다.

|상태/코드|의미와 표시|
|---|---|
|STEP_NOT_REACHED|앞 단계 실패/취소로 해당 단계가 실행되지 않음. 기대 화면 불일치와 구별.|
|STATE_MISMATCH|단계는 도달했으나 승인된 화면 조건과 관찰이 다름. 그 자체로 취약 확정 금지.|
|EVIDENCE_INSUFFICIENT|조건을 보았더라도 필수 증적이 없거나 불완전. 판단 불가능 사유 필수.|
|EVIDENCE_PRIVACY_EXCLUDED / CAPTURE_RESTRICTED|개인정보 제외 또는 캡처 제한 때문에 자료가 없음. 보안 우회 없음.|
|REVIEW_TIMEOUT / REVIEW_ERROR|자료 수집과 별도로 AI 검토가 끝나지 못함. 기기·재생 실패로 바꾸지 않음.|
|REVIEW_CANCELLED / NOT_REVIEWED|취소 또는 미검토. 다른 동선의 결과로 채우지 않음.|
|INTEGRITY_ERROR / VERSION_MISMATCH|봉인 자료 또는 승인 버전 검증 실패. 자동 대체 금지.|

같은 점검의 최종 요약에는 적용 가능한 모든 선택 동선의 `recording_id/version/occurrence, attempt_id, reached/expected checkpoints, evidence refs, collection coverage, review status, result/reason` 행을 보인다. 적용 제외와 unknown도 이유를 접어서 숨기지 않는다. 어느 한 동선의 성공으로 다른 동선의 공백을 덮거나 전체 양호로 요약하지 않는다. 필수 범위 미검토는 [결과 계약](08-evidence-results.md)에 따라 판단 불가능 및 해당 동선 이유로 남긴다. 기존 판정 기준을 새로 구현하지 않으며 이 명세의 합성 시험에는 테스트용 결과만 사용한다.

예를 들어 본인확인 안내를 화면에서 관찰했다면 결과는 **안내 관찰**이다. 본인확인 없이 실제 기능이 차단되는지, 서버가 실제로 강제하는지 또는 전체 인증이 적절한지는 이 관찰로 입증되지 않는다. `enforcement_verified=false`, 미검증 범위와 이유를 명시한다. 안내가 안 보였다는 사실도 우회나 취약의 증거로 자동 전환하지 않는다.

## 취소, 늦은 응답과 보존

사용자 취소 시 엔진은 새 입력을 중단하고 기존 안전 정리를 수행하며 다음 동선을 시작하지 않는다. 이미 봉인된 증적은 보존한다. 미도달 체크포인트와 남은 검토에는 cancelled/not_reached 이유를 각각 남긴다. 진행 중 검토에는 취소를 요청하되 원격 중단 성공을 추정하지 않는다. 늦은 응답은 취소된 attempt의 late response로 격리하고 확정 결과를 덮어쓰지 않는다. 다시 검토하려면 새 review attempt를 명시적으로 생성한다. 기기 동작을 자동 반복하지 않는다.

최종 결과는 증적 저장·무결성 상태와 검토 terminal 상태를 함께 확정한 뒤 결과 로그에 게시한다. 중간 진행은 점검 탭에 남는다. 저장 오류/정리 불확실성은 정상 완료와 구별하고 기존 recovery_required 규칙을 유지한다. 보존된 정상 동선·이전 실행은 취소나 재시작으로 지우지 않는다. 보존 기간/삭제 정책은 기존 프로젝트 정책을 따르며 이 문서가 무기한 보존이나 자동 삭제를 새로 승인하지 않는다.

## 합성 QA 수용 계획 — 아직 미실행

1. 동선 A/B/C의 동일 점검에 각각 다른 단계/증적 fixture를 지정한다. 승인 목록 순서와 실제 엔진 순서가 일치하고 동시 기기 실행은 0이다. 세 동선의 독립 행·참조가 모두 남는다.
2. B의 단계 미도달, C의 조건 불일치를 주입한다. A의 테스트용 성공 값으로 B/C가 양호 처리되지 않는다. unknown 적용과 not_applicable 이유도 표시한다.
3. 같은 이벤트 재전달은 한 객체, 다른 occurrence/attempt는 별도 객체다. 같은 키의 다른 hash, 다른 run 참조, 손상·누락 자료를 거부하며 정상 원본 hash는 유지한다.
4. 합성 민감 marker가 있는 원본 화면/패킷/입력은 저장소·manifest·로그·검토 입력·결과에서 모두 제외된다. 제외 때문에 부족한 범위가 명시된다. 캡처 제한 fixture를 우회하지 않는다.
5. 검토 응답을 지연/영구 대기/오류로 주입해도 다음 승인 동선은 AI 응답을 기다리지 않는다. 정해진 deadline 이후 review timeout과 재생 결과를 구분하고 final history에 공백을 보존한다.
6. bounded 수집 큐 초과, capture timeout, 디스크 실패를 주입해 silent drop 없이 gap 또는 실패 최종화를 남긴다. 무기록 실행·무한 대기·자동 재생 재시도는 없다.
7. 재생 중 취소 시 후속 동선 not_run, 기존 봉인 자료 유지, 늦은 AI 응답은 원결과 불변. 명시적 새 검토는 새 attempt이며 기기를 재조작하지 않는다.
8. 계획 승인 후 route/step/hash/필드 변경은 실행 전 거부하고 새 승인 필요 상태를 표시한다. 다른 버전의 증적으로 대체하지 않는다.
9. 하위 검토기의 쓰기·다른 run 읽기·기기/셸/네트워크 접근이 차단되는지 호스트별 구조 시험을 별도 수행한다. 미입증이면 unavailable; 모의 검사 Skill이나 실검사 로직을 작성하지 않는다.
10. 합성 본인확인 안내 fixture는 안내 관찰만 보고하고 실제 강제 여부는 미검증으로 남긴다. 실제 인증·거래·공격·우회 시험은 이 수용 범위에 없다.

남은 구현 결정: 호스트별 읽기 전용 격리 검증, 상태 스냅샷의 한도/원자성, 수집 큐 backpressure 측정, 개인정보 제외 표현의 검증, 검토 deadline 기본값과 UI 상세 배치. 구현 시 이 명세의 보존·권한·비차단 경계를 유지하면서 구체 값과 시험 결과를 기록한다.

## 제한된 구조 POC 후속

합성 Plan v2는 `selected_check_ids × ordered_routes의 선택 occurrence` 전체 적용 행렬을 체크포인트와 독립적으로 검증한다. applicable인데 체크포인트가 전혀 없는 선택도 분모에 포함하고 `PLAN_CHECKPOINT_MISSING` 보고 행을 남긴다. 이 행은 단계·액션을 생성하거나 검토기에 전달하는 체크포인트가 아니다. 체크포인트가 있으나 증적이 없는 `EVIDENCE_INSUFFICIENT`, 단계 미도달과 구분한다. 결과는 판단 불가능을 유지한다.

not_applicable과 unknown은 사유와 별도 개수·행을 보존하되 applicable 분모에 포함하지 않는다. 따라서 0/0은 양호나 완료된 검증의 뜻이 아니다. 행렬 누락·중복, 선택하지 않은 항목/동선, 상태별 허용 사유 불일치, not_applicable/unknown에 붙은 체크포인트는 계획 검증에서 거부한다. [v2 보고 계약과 호환성](../../pocs/p4-integration/docs/OBSERVATION-APPLICABILITY.md)은 합성 전용이다. 기존 v1·GPUI 소비자는 아직 v2로 이전하지 않았으며 새 보고 행의 GPUI 렌더링은 미검증이다.

[P1 재생 경계 연결](../../pocs/p4-integration/docs/P1-OBSERVATION-BRIDGE.md)은 실제 P1 엔진·큐와 합성 기기 어댑터를 사용해 시점·동선 귀속·검토 지연·취소를 별도로 시험한다. GPUI 계획 UI와 실기기 상태 취득, 실제 검토기 격리를 완료했다는 뜻은 아니다.

[합성 체크포인트 POC](../../pocs/p4-integration/docs/OBSERVATION-CHECKPOINT-POC.md)는 고정 계획·QA 상태·가짜 검토기로 일부 경계를 시험한다. 위 전체 수용 계획의 완료가 아니다. 실제 자식 프로세스 격리와 기기 연결은 미구현이며, 일반 Python 실행을 읽기 전용 격리로 간주하지 않는다.
