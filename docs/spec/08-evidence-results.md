# 08. 증적·최종 결과·날짜별 이력

관련 기능: F-39~43. 승인 UI06의 구조를 유지하며 중간 실행 로그는 점검 탭에만 표시한다. 아래 정책은 설계 검토 결정이며 구현 검증 완료를 뜻하지 않는다.

## 1. 결과 상태와 판정

실행 상태와 보안 판정은 서로 다른 축이다.

|구분|값/정책|
|---|---|
|실행 중 판정|`verdict=null`. 아직 판단하지 않았다는 뜻이며 네 번째 보안 판정이 아니다.|
|최종 판정|`pass`=양호, `fail`=취약, `inconclusive`=판단 불가능|
|항목 실행 상태|`completed`, `failed`, `timed_out`, `cancelled`, `not_run` 등 실행 계약의 terminal 값|
|미선택 항목|run의 선택 목록/결과 행/판정 집계에 포함하지 않음|
|선택했으나 미실행|행을 유지. `execution_status=not_run`, `verdict=inconclusive`, `reason_code=RUN_CANCELLED_BEFORE_START` 등 구체 원인|
|도중 실패·취소|검증이 완결되지 않았다면 `inconclusive`. 이미 검증이 완결된 항목의 유효 결과는 유지.|

- 양호: 해당 항목의 정의된 필수 검증 범위와 기대 방어를 증적으로 확인했을 때만 허용한다.
- 취약: 항목별로 정의된 취약 조건을 증적으로 확인했을 때 허용한다. 거래·권한 항목은 실제 처리/반환 대상/상태 변화를 확인하며, 정적 분석 등 다른 항목에 불필요한 실제 거래 증거를 요구하지 않는다.
- 한 가지 방어가 확인됐다고 평가항목 전체를 양호로 확대하지 않는다. 점검 범위를 `tested_scope`에 적는다.
- check의 필수 scope 중 하나에 증거가 검증된 취약이 있으면 다른 scope가 미완료여도 취약으로 남기고 미검증 범위를 limitations에 표시한다. 취약 증거가 없고 필수 scope 하나라도 미완료이면 판단 불가능이며, 모든 필수 scope가 충족될 때만 양호다.
- 판정 생성에 성공했더라도 그 판정을 입증하는 필수 증적이 저장되지 않았거나 참조가 유효하지 않으면 결과 검증을 실패시키고 판단 불가능 사유를 남긴다.
- 메인 AI 요약은 검증된 항목 결과를 대체하지 않는다. 도구의 구조화 관찰 결과, 항목별 판정 기준, 증적을 대조한다.
- 앱 종료·팝업 부재·HTTP 200만으로 양호/취약을 결정하지 않는다.

## 2. 데이터 계약

```text
RunSummary
  schema_version, project_id, run_id
  started_at_utc, ended_at_utc, display_timezone
  execution_status, cleanup_status
  selected_check_ids, completed_count, not_run_count
  verdict_counts {pass, fail, inconclusive}
  device_snapshot, app_snapshot, route_snapshot
  config_version/hash, skill_versions/hashes, backend_snapshot
  finalization_version, finalized_at

CheckResult
  run_id, check_id, attempt_id
  execution_status, verdict
  reason_code, reason, tested_scope, limitations
  evidence_refs[], observation_refs[], follow_up
  started_at, ended_at, duration_monotonic_ms

Evidence
  evidence_id, project_id, run_id, check_id, attempt_id
  recording_id?, action_id?, packet_id?, tool_call_id?
  captured_at_utc, source_clock_offset?
  media_type, byte_length, content_hash, relative_blob_ref
  collection_method, original_or_derived, derived_from[]
```

시간 문자열은 고유키가 아니다. `run_id`로 모든 결과·증적·요약을 연결한다. 시작/종료는 UTC+timezone 정보로 보존하고 사용자 화면에서 일관되게 표시한다. 소요 시간은 벽시계 변경에 영향받지 않는 monotonic duration으로 계산한다. 원본 시간 오차를 알 수 없으면 알 수 없다고 표시한다.

`backend_snapshot`에는 provider/model·런타임 버전·capability·설정의 비밀이 아닌 식별 정보만 넣는다. API key/token 자체는 넣지 않는다. 원문 기준의 저작물 전체, 고객 데이터 및 증적은 설계 Git 저장소에 넣지 않는다.

## 3. 영속화와 불변성

- 로컬 프로젝트 저장소를 메타데이터 저장소와 content-addressed 또는 고유 ID 기반 blob 저장 영역으로 나눈다.
- 원본 route/packet/evidence를 덮어쓰지 않는다. 변조·요약·재전송 결과는 새 객체이며 원본 참조를 가진다.
- blob 임시 기록→flush/완료→메타데이터 등록으로 참조가 미완성 파일을 정상 객체로 가리키지 않게 한다. 실패 시 orphan 정리 또는 진단을 수행한다.
- hash는 변경/손상 검출 수단이지 원본 관찰의 진실성을 보장하는 서명은 아니다. 최종화 후 증적이 손상되면 원판정을 몰래 수정하지 않고 `integrity_status=corrupt/missing` 및 검토 필요 경고를 표시한다. 재검증은 새 run으로 수행한다.
- DB와 blob 사이의 불일치는 재시작 검사로 진단한다. 누락 증적을 다른 run의 파일로 대체하지 않는다.
- run이 terminal이어도 최종화가 실패하면 정상 결과 이력에 넣지 않는다. 점검 탭의 복구 필요 상태에서 사유와 재시도 경로를 표시한다. 최종 결과 이력은 `terminal && finalized`만 조회한다.
- run 최종화 시 선택 항목별 terminal 결과를 한 번 모아 검증하고 요약·집계를 저장한다. repeated finalize는 같은 버전 결과를 반환하며 중복 이력을 생성하지 않는다.
- 최종 결과는 불변이다. 재검사는 새 run_id로 남긴다. 결과를 수동 편집하는 기능은 MVP에서 제외한다.
- disk-full 상황은 오류 자체도 영속화할 수 없을 수 있다. UI 메모리 상태에 저장 실패를 유지하고 정상 완료를 표시하지 않는다. 재시작 시 DB·blob reconciliation으로 불완전 기록을 찾아 복구 필요 상태로 표시한다. 저장됐다는 보장은 실제 쓰기 완료 확인 후에만 한다.
- 자동 삭제·자동 업로드를 기본 동작으로 넣지 않는다. 보존/내보내기/삭제 UI는 별도 요구가 생기면 설계한다. 현재는 사용 가능한 공간을 확인하고 부족 시 수집 실패를 명시한다.
- 스키마 마이그레이션은 버전 점검·백업 가능한 변경 절차 및 과거 fixture 재조회 테스트를 갖춘다. 지원하지 않는 새 버전을 억지로 열지 않는다.

## 4. 결과 로그 UI 동작

### 왼쪽 이력

- 날짜·시각 내림차순, 앱 패키지·선택 항목 수·실행 완료/중단 상태를 보조 표시한다.
- 날짜 검색은 화면에 표시하는 timezone 기준으로 해당 날짜/범위를 해석한다. 날짜 오류, 0건, 이력 없음, 조회 오류를 분리한다.
- 동일 시각 실행은 추가 run 식별 표시로 구분한다. 실행 도중 run은 최종 이력 목록에 포함하지 않는다.
- terminal 실패/취소도 이력에 포함한다. 이미지의 모든 이력이 녹색 완료 아이콘인 예시는 규범이 아니다.
- pagination 또는 virtualized 목록으로 전체 이력을 한 번에 메모리에 올리지 않는다.

### 요약 및 항목 목록

- 선택 run의 기기/앱 snapshot, 시작·종료 및 실행 상태, 양호/취약/판단 불가능 수를 표시한다.
- `pass+fail+inconclusive == selected_check_ids.count`가 최종화 불변식이다. 별도로 미실행 개수를 안내하여 판단 불가능을 실제 검사 수행으로 오해하지 않게 한다.
- 항목명 검색 및 판정 필터는 선택 run 내부에만 적용한다. 필터된 행 수가 원본 판정 집계를 바꾸지 않는다.
- 이력 전환 시 선택 항목 상세를 비우고 새 run의 행을 선택한다. 늦게 도착한 이전 조회 응답은 request generation/run_id 확인 후 무시한다.
- 현재 기기가 연결 해제되거나 다른 기기로 바뀌어도 결과 조회는 가능하다. 상단 현재 기기와 과거 snapshot의 역할을 구별한다.

### 상세 및 증적 미리보기

- 판정 사유, 확인된 관찰·근거, 시험 범위/한계, 증적, 후속 조치를 보여준다.
- 증적 목록에는 이름·종류·크기·수집 시각·무결성 상태를 표시한다. 이미지의 증적 날짜 불일치를 그대로 구현하지 않는다.
- evidence 조회는 현재 project/run/check membership을 서버에서 검증한다. 파일 경로를 직접 받지 않고 evidence_id를 해석한다. 저장 루트 밖 path traversal·symlink escape·외부 URL/리소스 로딩을 거부한다.
- 텍스트/JSON/이미지는 지원 viewer로 미리보기, binary/지원 불가 형식은 metadata만 표시한다. HTML/스크립트/문서 macro를 실행하지 않는다.
- 큰 파일은 제한된 preview 및 부분 조회. 원본과 truncation/derived 요약 여부를 표시한다.
- 체크박스에 대응하는 일괄 동작이 없으므로 증적 checkbox는 구현하지 않는다. `미리보기`를 명확한 단일 동작으로 둔다. 새로운 export/delete 기능은 도출하지 않는다.
- 결과 로그에는 main/item agent 실시간 로그, heartbeat, 대기열을 표시하지 않는다. 오류 로그 파일이 최종 증적이면 정적 증적으로 미리보기할 수 있다.

## 5. 수동 증적 제출·검토

- 자동화 범위가 아닌 절차 확인은 **점검 탭**의 해당 항목 상세에서 `수동 증적 추가/검토`로 처리한다. 결과 로그에 입력 작업이나 진행 대기열을 추가하지 않는다.
- 시작 전 필요한 수동 자료가 없으면 eligibility 이유를 보여준다. 실행 중 보완이 필요한 항목은 명시적 `awaiting_manual_evidence` 상태와 기한/취소 경로를 가지며, agent heartbeat 미수신 hang과 구별한다. 기기를 계속 점유할 필요가 있는지는 항목 계약에서 정하되 다음 항목 자동 실행으로 임의 우회하지 않는다.
- 운영자가 파일/설명/확인 내용을 추가하면 제출자 식별, 제출·관찰 시각, collection_method=manual, 원본/파생 여부, 대상 run/check, 근거 설명을 저장한다. 직접 관찰 도구가 만든 증거와 구분한다.
- 형식·hash·대상 참조를 검증하고 검토자의 식별·검토 시각·검토 결론·범위를 남긴다. 로컬 단일 사용자 제품에서 검토자 표시는 자기신고 기록이며 강한 신원 증명으로 과장하지 않는다.
- 미검토·일치하지 않는 자료, 단순 주장, 진위가 확인되지 않은 자료를 AI가 직접 관찰한 것으로 쓰거나 자동 양호 처리하지 않는다. 검증하지 못한 범위는 판단 불가능 사유에 적는다.
- 최종화 이후 추가·수정은 원결과 덮어쓰기가 아닌 새 검토 run으로 기록한다.

## 6. 대표 오류 코드

`EVIDENCE_MISSING`, `EVIDENCE_HASH_MISMATCH`, `RESULT_SCHEMA_INVALID`, `RESULT_INSUFFICIENT_EVIDENCE`, `STORAGE_FULL`, `RUN_CANCELLED_BEFORE_START`, `TOOL_TIMEOUT`, `DEVICE_DISCONNECTED`, `UNSUPPORTED_EVIDENCE_TYPE`.

기계 코드와 한국어 설명을 함께 보관한다. 단순 `실패`로만 저장하지 않는다. 판단 불가능 이유는 관찰 범위와 필요한 후속 준비를 구체적으로 설명한다.

## 7. 수용기준

1. 동일 timestamp를 가진 두 run을 만들고 각각의 요약·결과·증적이 섞이지 않는다.
2. 양호 1/취약 1/취소 미실행 1 run은 합계 3, 판단 불가능 1, 미실행 1로 표시한다.
3. 실행 중 결과 로그를 열면 이전 terminal run만 조회되며 실시간 로그는 점검 탭에 남는다.
4. 결과가 없는 상태, 검색 0건, DB 조회 오류가 서로 다른 빈 상태로 표시된다.
5. run A→B 빠른 선택과 네트워크 응답 순서 역전에서도 B 화면에 A 증적이 나타나지 않는다.
6. 기기 분리 후 앱 재시작해도 저장된 이력·근거를 조회한다.
7. 증적 삭제/1 byte 변조/지원하지 않는 MIME fixture를 각각 정확히 진단하고 원본으로 가장하지 않는다.
8. disk-full/쓰기 오류 시 성공 최종화하지 않는다. 오류 기록 자체가 저장 불가한 경우에도 UI와 재시작 복구 검사가 불완전 상태를 정상 완료로 오인하지 않는다.
9. repeated finalize는 이력을 중복 생성하지 않는다. 재검사는 별도 run으로 보존한다.
10. raw packet/증적 fixture에 실행 가능한 문자열을 넣어도 viewer·agent instruction으로 실행되지 않는다.

11. 다른 run의 evidence ID, `../` 경로, symlink escape 및 외부 리소스 참조를 거부한다.
12. 수동 증적의 제출·검토 출처를 최종 근거에 보존하고 미검토 자료로 자동 양호 판정을 만들지 않는다.
