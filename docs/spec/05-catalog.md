# 05. 점검 카탈로그와 실행 조건

상태: 상세 설계 채택안. 공식 평가기준 적용 범위는 원본 대조 게이트를 유지한다.

## 기능과 분류

CAT-01 카탈로그 로딩, CAT-02 분류별 checkbox, CAT-03 조건 계산과 비활성 사유, CAT-04 선택 항목 상세, CAT-05 실행 직전 재검증, CAT-06 Skill/절차 버전 snapshot.

점검 탭에서만 선택한다. 기록 탭에 항목 선택·요약·시작을 추가하지 않는다. E/S/U/N은 구현 우선순위이고 M은 수동 증적 보완이다. 하나의 항목이 여러 실행 수단을 사용할 수 있으므로 primary group과 capability tags를 구분한다.

## 카탈로그 구조

`checks/<check-id>/manifest.yaml`, `common/SKILL.md` 필수, `aos/SKILL.md` 및 `ios/SKILL.md` 선택. 최대 세 Skill을 유지한다. manifest는 네 번째 Skill이 아니다.

Manifest 필드:
- stable check ID, title, source reference/scope, implementation group, schema/skill version
- supported platforms, procedure variants
- requirements: root/device state, artifact, route, packet, test accounts, tool/backend capabilities
- step/tool/total timeout, cleanup contract, expected evidence, result schema

한 평가항목에 여러 procedure variant를 둘 수 있다. 변형은 manifest 내 절차 메타데이터이며 별도 Skill을 무제한 증식시키지 않는다. common과 현재 플랫폼 Skill을 함께 읽는다. 플랫폼 Skill이 없다고 지원으로 추정하지 않는다.

원문 공식 ID와 내부 ID를 분리한다. 기존 문서의 13 모바일/5 HTS 구분도 원본 대조 전 최종 공식 범위라고 주장하지 않는다. 사용자 제공 18개 제목의 누락 여부를 추적하고 HTS 전용 항목의 모바일 응용은 명시적 확장 ID로 관리한다. 입력정보 보호·접근매체 발급은 U/M 보완 대상으로 유지한다. 전체 18개 항목 매핑은 09 항목별 명세를 참조한다.

## 조건 계산

입력은 선택 기기의 연결·root·도구 capability snapshot, 대상 설치 앱·artifact snapshot, route 및 packet coverage, 테스트 데이터, provider capability다.

출력은 `eligible`, 실행 가능한 variant IDs, blocking reasons, warnings, context hash다. root는 rooted/stock/unknown을 구분한다. unknown을 stock으로 취급하지 않는다. 자동 감지와 수동 보정·근거를 따로 보관하며 수동 보정이 실제 도구 접근 가능성을 대신하지 않는다.

실행 가능한 variant가 하나 이상이면 checkbox를 활성화한다. 같은 목표를 검증하는 대안 variant는 manifest의 고정 우선순위로 하나를 선정하고 사용자에게 표시한다. 서로 다른 필수 scope를 검증하는 variant는 모두 필요하다. 어떤 variant가 누락되었는지 tested scope와 limitations에 남긴다. 조건 미충족은 해결 가능한 설명을 제공한다. 예: '이 동선에는 비밀번호 변경 완료 checkpoint가 없습니다.' 기기 변경 또는 조건 만료로 선택이 무효해지면 자동 해제하고 그 사유와 해제 개수를 표시한다.

route 존재만으로 거래 동선 충족을 인정하지 않는다. route semantic tags, checkpoints, 대상 앱/build 호환성, incomplete action을 확인한다. 기본 앱 실행 route는 launch-only이며 거래 인증 동선으로 확장 해석하지 않는다.

packet eligibility는 recording 전체의 partial 라벨만 보지 않고 해당 절차의 필요한 endpoint/transaction/시간 구간별 coverage를 계산한다. 관련 없는 구간의 gap이 모든 항목을 비활성화하지는 않되, 검사에 필요한 구간의 손실은 차단한다. coverage 요구와 실제 확인 범위를 snapshot한다. packet 존재만으로 N 검사를 허용하지 않는다. endpoint/필드 구조/세션 유효성/attribution/coverage 및 A·B 리소스가 요구되는지 검사한다. live replay 시 오래된 인증정보를 정상 인증으로 간주하지 않는다.

## 선택과 START

선택 UI는 현재 eligibility를 표현한다. 행 상세는 목적·적용 scope·필요조건·수행 절차 요약·기대 증적을 표시한다. 다중 선택이 있어도 상세는 focus한 한 항목을 표시한다.

START에서 server-side preflight를 다시 수행한다. context hash가 달라지면 새 결과를 반환한다. 부적합 항목을 조용히 건너뛰고 실행하지 않는다. 사용자가 수정할 때까지 시작을 차단한다. context hash는 device stable ID+connection generation, capability revision, app/artifact fingerprint, sealed route/packet revision, config/Skill/provider capability hash 같은 의미 있는 필드로 계산한다. heartbeat 시각이나 UI 정렬 순서는 포함하지 않는다.

실행 관리자는 요청 validation → device lease 획득 → lease 안에서 변경 가능한 기기/앱 조건 재검사 → snapshot/run 생성 순서로 처리한다. preflight와 lease 사이 기기 분리/앱 교체가 있으면 실패시키고 lease를 정리한다. 이후 각 mutation tool도 lease generation과 필요한 precondition을 다시 확인한다. 통과 시 선택 항목/variant/Skill hash/설정/기기/앱/route/packet을 immutable run plan으로 고정한다.

## 판정 기준

보안 판정은 양호/취약/판단 불가능만 사용한다. 각 항목 절차에는 통제 조건, 자극, 관찰, 정상 방어 기대조건, 취약 증거, 한계, cleanup을 명시한다. 팝업 없음=취약, 프로세스 종료=양호, HTTP 200=IDOR 성공 같은 단일 신호 판정을 금지한다.

하나의 check에 여러 필수 scope가 있으면 증거가 확인된 취약 하나가 전체 check의 취약 판정에 우선한다. 취약 증거가 없고 필수 scope 중 하나라도 미완료/증거 부족이면 판단 불가능이다. 모든 필수 scope가 양호 조건을 충족할 때만 check 전체를 양호로 판정한다. 대안 variant 중 하나의 완료는 그 variant가 동일 전체 scope를 검증한다고 manifest에 명시된 경우만 충분하다. 일부 scope만 검증한 결과를 전체 범위 양호로 확대하지 않는다.

선택하지 않은 항목은 해당 run 결과 모집단 밖이다. 선택했지만 취소되어 수행하지 않은 항목은 실행 상태 not_run 및 판단 불가능 이유를 남긴다. '미수행'은 네 번째 보안 판정이 아니다.

## 수동 증적 보완(M)

자동 검증이 어려운 절차는 M variant로 수동 증적 등록·검토를 제공한다. 항목 상세에서 필요한 증적과 확인 질문을 제시하고 사용자는 로컬 파일/관찰 기록을 등록한다. evidence에는 source type, 원본 생성 시간(알려진 경우), 등록 시각, 등록자, 검토자, 대상 check/run/scope, 설명 및 hash를 남긴다. 출처·검토자 미확인은 unknown으로 명시한다.

등록 자체가 양호 판정은 아니다. 검토자는 기대조건과 실제 근거를 연결한 결론·한계를 제출하고 result validator가 scope/필수 근거를 검증한다. 증거 부족은 판단 불가능이다. 초기 구현은 finalization 전에 제출한 증적만 해당 run에 포함한다. 제출을 기다리는 항목은 명시적 `awaiting_manual_evidence` 상태와 timeout/취소 경로를 가지며, 다음 device 점검을 임의 병렬 실행하지 않는다. 사용자가 기다림을 종료하면 미완료 이유를 남긴다. terminal run 수정·재승인은 후속 기능으로 보류하고 추가 검토는 새 run으로 남긴다.

## 실패와 인수 기준

1. malformed manifest/Skill 누락/지원하지 않는 schema는 해당 check 비활성 및 오류로 표시한다.
2. root unknown과 root required 조합은 활성화되지 않는다.
3. device/app 변경 후 stale 체크가 새 run에 포함되지 않는다.
4. 일부 variant만 충족되어도 가능한 variant와 한계를 명확히 선택한다.
5. route는 있으나 checkpoint가 없거나 packet coverage가 부족한 fixture에서 시작이 차단된다.
6. UI 검사를 우회한 START API에도 동일 preflight가 적용된다.
7. run 생성 이후 Skill 파일 변경은 기존 snapshot에 영향을 주지 않는다.
8. 사용자 제시 18개 항목이 정식/확장/범위 밖/수동 보완 중 하나로 추적되고 누락되지 않는다.
9. partial recording의 관련 구간/무관 구간을 구분한 eligibility fixture가 통과한다.
10. 일부 필수 scope 미완료는 전체 양호가 되지 않으며 확인된 취약은 불가능보다 우선한다.
11. preflight 이후 기기/app 변경을 주입하면 lease 내 재검증에서 차단된다.
12. M 증적 등록만으로 양호가 되지 않고 출처·검토자·시각·scope와 검토 근거가 결과에 연결된다.

## 검증 게이트

합법적으로 보유한 공식 2026 원본과 ID/플랫폼 적용을 대조한다. 첫 E 항목의 양호/취약/판단 불가능 QA fixture와 테스트 oracle을 실험으로 검증한다. 악성코드 대응 항목은 실제 악성코드를 기본 fixture로 사용하지 않으며 통제된 시뮬레이션으로 검증 가능한 범위를 명시한다.
