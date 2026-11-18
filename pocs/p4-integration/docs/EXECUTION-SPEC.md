# P4 최소 통합 실행 명세 v1 — 구현 전 기준선

2026-11-17 UTC. 사용자 승인 범위는 클라우드의 synthetic/fake PoC 작성·검증·커밋·push다.
과거 상위 계획의 문서 전용 상태를 이번 P4 범위에서 대체한다. 모든 변경은 이 폴더에 한정한다.
명세를 먼저 커밋하고 구현, 검증 보고서를 별도 커밋한다.

## 근거와 검증하려는 가설

`docs/07-poc-plan.md`, `docs/04-contracts.md`, `docs/spec/06-run.md`,
`docs/spec/07-ai.md`, `docs/spec/08-evidence-results.md`, P2/P3 실행 명세와 코드를 따른다.
checkout 및 상위 `/workspace`, `/`에 AGENTS.md가 없고 저장소에 `.agents/skills`도 없다.
P3 common/AOS SKILL.md는 실제 P3 계약 입력으로 읽고 snapshot/hash를 보존한다.

검증 가설: Python supervisor가 모델과 독립적으로 단일 합성 기기 소유권, 선택 작업의
순차 실행, main/item 생존·진행·deadline, 취소, 종료 확인, cleanup, 최종화를 통제할 수 있다.
가짜 provider와 실제 기존 P2/P3 도구의 경계를 결과에서 구분할 수 있다.

## 지원 / 미지원

- Python 3.11+, Linux cloud, asyncio, SQLite, P3의 기존 jsonschema 의존성.
- 합성 기기 `synthetic-device-p4`와 앱 `dev.finsec.synthetic`만 허용한다.
- CHK-07 pass/fail/inconclusive fixture variant를 독립 item_id/attempt_id로 순차 실행한다.
  여러 공식 점검 항목을 구현한 것이 아니다. common 필수 + 선택 플랫폼 Skill 구조를
  유지하되 실제 지원 플랫폼은 P3가 제공하는 AOS뿐이다. iOS는 실행 전 거부한다.
- 실제 P2 Python relay + loopback fixture HTTP/1.1 요청/영속 packet 조회.
- 실제 P3 Python 평가기 + 입력/manifest/Skill/증적 검증. 그 관측은 전부 synthetic이다.
- main/item Provider 인터페이스는 모델 비종속, 구현은 fake만 허용한다. 실제 모델 호출,
  인증, 외부 API, 숨겨진 사고과정 수집을 하지 않는다.
- 미지원: P1 route/replay/package launch, GPUI/gpui-kit/UI, 사용자 PC, 실기기/ADB/Appium,
  실제 패킷/금융 앱/계정/인증정보, TLS/HTTP2/HTTP3, 두 실제 backend의 호환성,
  OS 수준 악성 provider 격리, 실제 기기 취소·복원, 전체 제품 통합.
- P1은 별도 Android 실기기 CLI 3회 성공 이력이 있으나 GUI 기록은 미검증이다.
  P2 38개/P3 58개 기존 synthetic 테스트는 실제 기기/전체 통합 성공을 뜻하지 않는다.
- 원래 UX는 점검 탭 체크→common+플랫폼 Skill→한 기기에서 항목별 순차 수행이다.
  이번에는 CLI로 같은 실행/최종 결과 경계만 시험한다.

## 입력 / snapshot / provider

versioned RunPlan은 command_id, synthetic device/app, platform, 선택 item_id/check_id/fixture,
provider configuration, deadline, proxy mode를 가진다. 허용된 fixture/enum만 받으며
외부 endpoint, shell, credential, 실제 기기 ID를 받지 않는다. 형식 오류는 run 생성 전
command error. START 수신 후 capability/preflight/busy 오류는 선택 항목 모두
not_run/inconclusive + 구체 이유로 최종화한다. 선택 없는 plan/중복 item ID는 거부한다.
plan은 deep-copy/hash하고 Skill/manifest와 provider capabilities를 snapshot한다.
동일 프로세스 내 동일 command_id+동일 plan은 같은 handle, 다른 plan은 conflict다.
명령 재시도 캐시는 재시작까지 영속화하지 않는다(이번 축소 범위).

Provider: start_job(context, tool_catalog), stream_events(job_id), cancel(job_id),
get_result(job_id), capabilities(). fake main은 선택 item 순서만 제안하고 scheduler가
snapshot과 정확히 일치하는지 확인한다. fake item은 허용 P3 fixture만 요청한다.
provider의 pass 주장만으로 결과를 만들지 않는다. 실제 P3 검증 결과만 채택한다.
capability는 cancellation, structured_output, streaming, local_only, gateway enforcement
mode=fake_cooperative를 선언한다. 실제 강제 격리를 뜻하지 않는다.

## 소유권 / gateway / watchdog

단일 SQLite lease row에 device, owner run, boot_epoch, 영속 증가 generation, attempt,
lifecycle(active/cleaning/free/recovery_required)를 보관한다. 트랜잭션으로 경쟁 START를
직렬화한다. 같은 DB를 사용하는 여러 supervisor도 active lease를 빼앗지 않는다.
기존 active/cleaning/recovery row는 재시작 시 자동 해제하지 않는다. 새 실행은 차단된다.
이 PoC는 자동 복구/자동 재개를 구현하지 않는다. 안전 확인 없는 recovery 해제 CLI도 없다.

Gateway는 정확한 run/device/epoch/generation/attempt, item scope와 허용 operation을
검증한다. 일반 요청은 active에서만 가능하다. cancel/timeout/error 즉시 revoke하여
cleaning으로 전환한다. 종료·cleanup 확인 전에는 generation을 새 작업에 주지 않는다.
cleanup은 supervisor의 고정 자원 journal에만 적용하고 provider 임의 명령은 받지 않는다.
stale/다른 item token, cleanup 중 일반 요청, 선택 밖 도구/항목을 거부한다.

watchdog는 출력 문자열 대신 task alive, heartbeat, last progress, active tool,
tool deadline, item/run deadline을 사용한다. 정상적인 무출력 작업은 deadline 안에서
성공한다. heartbeat가 살아도 진행 없는 작업은 hang, heartbeat 단절도 별도 원인이다.
main/item error 또는 비정상 종료, main/item hang, TOOL_TIMEOUT, DEVICE_DISCONNECTED,
PROXY_ERROR를 구별한다. 연결 해제는 fake fault이고 실제 USB를 조작하지 않는다.

취소는 즉시 cancelling event, 일반 capability revoke, provider cancel 요청, grace 후
종료 요청과 실제 종료 확인 순이다. cancel을 무시하는 fake task가 남으면
recovery_required를 영속화하고 신규 run을 차단한다. 늦은 이벤트/결과는 최종 결과에
반영하지 않는다. P3 동기 함수를 thread 취소로 멈췄다고 주장하지 않는다: adapter의
동기 작업은 bounded fixture 실행이며 실제 adapter 작업 완료 전 소유권을 해제하지 않는다.
필요시 adapter 자체의 owned 작업을 추적하며 미종료는 recovery_required다.

항목 완료 + cleanup 성공은 다음 선택 항목 허용. main/item/tool timeout·오류·disconnect·
cancel은 이번 최소 구현에서 보수적으로 run 중단, 뒤 항목 not_run. 이미 검증한 결과는
보존한다. cleanup failed/unknown은 별도 environmental 오류 + recovery_required이며
이미 입증된 취약을 지우지 않는다. timeout 후 종료/cleanup 성공이면 같은 run의 다음
항목은 중단하지만 새 run은 새 generation으로 가능하다.

## P2/P3 얇은 adapter와 참조

P2는 실제 Relay 시작→ON(또는 OFF)→RECORD→고정 loopback synthetic HTTP→STOP을
사용한다. packet DB를 보존하고 조회한다. STOP은 OFF가 아니다. cleanup에서 OFF/close,
listener/handler/writer 종료를 확인한다. 영구 filesystem stall의 강제 중단은 미검증이며
종료 미확인은 소유권 차단으로 처리한다. P2 원본 run_id=null/session_id는 수정하지 않는다.
P4 envelope에 run/session/item/recording/packet 원본 ID 및 출처를 매핑한다.
proxy OFF는 none/0이고 수집 성공이나 보안 판정을 뜻하지 않는다.

P3는 기존 fixture를 읽고 P4 synthetic run/session/attempt/device ID에 맞춰 복사한 뒤
기존 run 및 validate_bundle을 호출한다. 실제 common+AOS snapshot을 대조한다.
P3 packet_refs/route_refs는 원래대로 비워둔다. P2 packet은 P4 실행의 연결 증거이며
CHK-07의 원인/판정 증거가 아니다. P3 evidence ID는 bundle+attempt로 namespace한다.
P3 fail/pass/inconclusive 및 검증된 증거/범위/한계를 보존하고 cleanup 실패를 상위
스케줄러 차단으로 승격한다. P1 adapter는 제공하지 않고 route unavailable을 명시한다.

## 이벤트 / 최종 결과 / 저장

schema_version=1.0, synthetic=true. event에는 event_id, session_id, run_id, item/check,
tool_call_id, 단조 seq, UTC timestamp, source, type, payload를 둔다. live event의 verdict는
null이며 실행 화면 전용이다. after_seq replay는 해당 run만 반환한다.

run 상태: created→preflight→preparing→running→finalizing→completed/failed/cancelled.
항목 terminal: completed/failed/timed_out/cancelled/not_run. 보안 판정은 별도
pass(양호)/fail(취약)/inconclusive(판단 불가능), 모든 inconclusive는 reason_code/reason 필수.
cleanup은 completed/failed/unknown. 선택한 item만 정확히 한 결과를 갖고
pass+fail+inconclusive == selected item count. 실제 실행 없는 row는 pass 불가다.

run.json, events.jsonl, adapter 산출물은 실행 경로에 보존한다. final result는 모든 선택
항목과 증적을 검증한 뒤 원자적으로 봉인하고 SQLite history에 terminal+finalized만
등록한다. history 조회에 진행 중 이벤트/heartbeat를 넣지 않는다. finalization 저장 실패는
finalizing_failed로 메모리에 남고 history에는 없다. 디스크 오류 자체의 영속화는 보장하지
않는다. 기존 출력/결과를 덮어쓰지 않고 repeated finalize는 같은 결과다. 손상된 P3 bundle,
다른 run 참조, 증거 없는 pass/fail은 거부한다. hash는 출처 진실성 인증이 아니다.

## 합격 조건 / 재현

구현 후 README에 unittest 및 CLI demo/실패 시나리오/결과 검증 명령을 제공한다.
검증 보고서는 실제 환경, 명령, 테스트 수, CLI 결과, 한계와 원격 SHA를 구분한다.

1. pass/fail/inconclusive를 같은 schema로 순차 수행하고 실제 P2 packet/P3 증적을 검증.
2. 동시에 10개 START, 중복 START/STOP, 다중 manager lease 경쟁에서도 active 최대 1.
3. main/item 정상 무출력/오류/heartbeat 단절/진행 hang과 tool/item deadline 구별.
4. cancel/timeout 후 즉시 새 작업 금지, 종료·cleanup 확인 후에만 새 generation 허용.
5. cancel 무시/cleanup failed/unknown/disconnect에서 후속 항목 및 신규 run 차단.
6. stale token, 잘못된 owner/attempt/operation, 취소 후 늦은 호출/이벤트 거부.
7. 재시작 후 미회수 lease 차단, 정상 종료 후 새 generation, 이전 token 거부.
8. P2 proxy OFF/오류/포트 정리, P3 verdict/증적/Skill 확인, packet 참조의 비인과성 확인.
9. preflight/capability/형식 오류, 부분 결과 보존, 최종화 저장 실패와 history 분리.
10. 최종 P4 전체 테스트 및 P2 38/P3 58 회귀 테스트. 사용자 PC/GUI/기기 호출 없음.

full production RUN/AI 계약, process kill/OS 격리, durable command cache, 자동 recovery,
UI 재연결 및 실제 provider 교체의 모든 수용기준을 충족했다고 주장하지 않는다.


## Windows device-free portability correction

Final run snapshots and sealed results are UTF-8 regardless of host locale. Every
short-lived history SQLite connection must commit/rollback and then close on both
success and error; sqlite3's transaction context alone does not close a connection.
This preserves existing finalization and integrity checks while preventing Windows
cp949 decode failures and locked history files. No provider, lease, evidence, or
security verdict contract changes. Device-free Windows execution extends the
original Linux-only verification scope; real models/devices remain unaccepted.

The injected tool-timeout unit fixture allows 0.5 seconds rather than 0.06 seconds
so ordinary P2 startup does not consume its deadline before the selected item runs.
The deliberately stalled tool still exceeds that deadline; production defaults are
unchanged. Outside-run path rejection and privilege-dependent real symlink rejection
are separate tests so unavailable Windows symlink privilege does not mask path checks.

## Provider RPC boundary follow-up

Provider start/result awaits are tracked and bounded by existing tool/run/item deadlines. Role/phase-specific stop codes and lifecycle events are persisted. Uncertain start failure retains recovery rather than retrying ambiguous admission. No automatic retry or real-provider support is introduced. See [provider audit](PROVIDER-BOUNDARY-AUDIT.md) for confirmed defects, retry policy and remaining adapter isolation work.
