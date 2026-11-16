# 04. 데이터와 Skill 계약 초안

이 문서의 필드명과 저장 형식은 제안이다. 구현 전에 schema 버전을 확정한다.

## 1. 항목별 폴더

```text
checks/<check-id>/
  manifest.yaml
  common/SKILL.md       # 필수
  aos/SKILL.md          # 선택
  ios/SKILL.md          # 선택
```

Skill은 최대 3개이다. manifest는 실행용 메타데이터이며 네 번째 Skill이 아니다. 하위 에이전트는 common과 현재 플랫폼 Skill을 함께 읽는다. 플랫폼 Skill 부재가 자동으로 지원을 뜻하지 않으므로 manifest에서 capability를 선언한다.

manifest 제안:
- check_id, title, source_reference, source_scope, implementation_group
- schema_version, skill_version
- supported_platforms
- requirements: device_state, root, artifact, route, packets, tools
- timeout 및 cleanup 정책
- expected_evidence 및 result_schema

원본 기준과 모바일 확장 항목은 서로 다른 식별자를 사용한다. 구현 분류와 공식 평가 식별자를 섞지 않는다.

## 2. 기록 모델

- Recording: recording_id, device snapshot, app snapshot, 시작/종료 시각, proxy 상태, action/packet 참조.
- Action: action_id, sequence, action type, locator 및 보조 coordinates, 화면 방향/크기, wait 조건, 입력 참조, screenshot/UI tree 참조, 시각.
- Packet: packet_id, connection_id, direction, timestamp, endpoint, protocol, payload reference, request-response 연계가 확인된 경우 correlation.
- Run: run_id, 선택 항목, device/app/Skill/config/backend snapshot, route/packet 범위, 실행 상태.
- Evidence: evidence_id, run/check/action/packet/tool call 참조, 수집 시각, 종류, 내용 저장 위치와 integrity hash.

시간상 가까운 UI 동작과 패킷을 연관 후보로 보여줄 수 있지만 인과관계로 확정하지 않는다. 단말 시각과 호스트 시각 차이를 보정하거나 기록한다.

JSON을 내부 표준으로 두고 YAML은 설정/가독성 용도로 사용할 수 있다. 최종 형식은 미확정이다.

## 3. 결과 계약

- check_id, run_id, execution_status
- verdict: 양호 / 취약 / 판단 불가능
- reason, evidence_refs, tested_scope, limitations
- skill/config/backend version 및 수행 시각

판단 불가능은 reason이 필수다. 결과만 있고 evidence가 없으면 자동 양호 처리하지 않는다. 중단된 항목은 실행 상태와 함께 미완료 범위를 명시한다. 최종 보고서의 누락·미선택 처리 규칙은 후속 확정한다.

## 4. IDOR 설정

QA 테스트 사용자 A/B, 각 사용자의 소유 resource reference, 대상 endpoint와 method, 치환 위치, 정상/거부 기대조건, 사전 상태와 복원 조건을 설정할 수 있어야 한다.

비밀번호, token, 계좌 실데이터는 저장소의 예제 설정에 넣지 않는다. 실제 값은 로컬 비밀 저장소의 참조를 사용한다. 단순 응답 코드만으로 권한 검증 결과를 확정하지 않고 실제 반환 대상과 상태 변화를 증거로 확인한다.

## 5. 감사 로그와 모델에 전달할 정보

메인 AI·하위 에이전트의 실행 및 다음 정보를 구조화해 기록한다:
- 누가 어떤 항목에서 어떤 도구를 요청했는지
- 실행 입력의 안전한 요약 및 필요한 원본 증적 참조
- 시작/종료, 도구 결과, 오류, 취소, timeout
- 결과에 연결된 근거와 판단 불가능 이유

숨겨진 사고과정을 요구하거나 저장하지 않는다.

큰 패킷 전체를 매번 프롬프트에 넣기보다 요약/목록을 제공하고 필요한 payload를 도구로 조회하는 구조를 제안한다. 외부 모델로 전송하는 필드, 마스킹 규칙, 로컬 모델 사용 정책과 보존 기간은 구현 전에 확정해야 한다. QA 환경도 인증정보와 고객사 데이터 보호가 불필요하다는 뜻은 아니다.

## 6. 예외·검증 테스트 제안

- 동일 기기에 두 항목이 동시에 접근하려는 경우 한 작업만 허용.
- main AI 종료, item AI hang, proxy 단절, device unplug 각각 구분.
- 취소 후 도구 잔존 여부 확인 및 다음 작업 차단.
- 기록 없는 실행은 기본 package launch로 재현.
- Skill/version snapshot을 통해 결과 재검토 가능.
- 백엔드 변경 후에도 route/packet/result 계약 유지.
- 실패한 검사를 양호로 계산하지 않음.
## 7. 최종 결과 이력 조회

승인된 UI는 완료된 실행을 날짜·시각별로 선택한다. 표시 시각과 별도로 run_id를 고유키로 사용한다. 각 실행은 시작/종료 시각과 timezone, 대상 앱·기기 snapshot, 최종 항목 결과와 증적 참조를 보존한다. 같은 시각의 실행도 구분할 수 있어야 한다. 이력 선택 시 모든 상세를 같은 run_id로 조회하며, 현재 연결 기기가 바뀌어도 과거 snapshot을 유지한다. 저장소/schema 구현 방식과 보존 기간은 미확정이다.
