# P3 CHK-07 실행 명세 v1 — synthetic only

상태: 구현 전 명세. 2026-11-16 UTC. 이번 구현 승인은 상위 문서의 과거
“아직 구현하지 않는다” 상태를 대체한다. 본 폴더만 변경한다.

## 목표와 경계

첫 E 항목 CHK-07(내부 ID, OS 변조 탐지 기능 적용)의 **증거 기반 판정 계약**을
GUI/AI/P1/P2 없이 독립 Python CLI로 시험한다. 실제 금융 앱 평가, 공식 규정 인증,
실제 Android 변조 탐지 구현 또는 어댑터 검증을 주장하지 않는다.
유일한 어댑터는 통제된 synthetic fixture를 읽는 것이다. ADB, Appium, 기기,
네트워크, subprocess, 실제 파일 증거 입력은 사용하지 않는다. Python 3.11+.

상위 근거: `docs/07-poc-plan.md`, `docs/spec/09-checks-poc.md`,
`docs/04-contracts.md`, `docs/spec/05-catalog.md`, `docs/spec/06-run.md`,
`docs/spec/08-evidence-results.md`. 현재 main에는 AGENTS.md, .agents/skills 또는
공용 기계 판독 schema가 없고 P1의 validator는 P1 자체 계약이다.

## 입력과 도구

`python -m os_tamper run --input fixtures/pass.json --output /tmp/p3-pass`
및 `python -m os_tamper validate --output /tmp/p3-pass`를 제공한다.
schema_version=`1.0`, synthetic=true, mode=`synthetic`, check_id=`CHK-07`.
프로젝트/session/run/attempt/device ID는 명시적인 synthetic 식별자,
package는 합성 namespace, app build는 합성 hash이며 실제 값을 예제에 넣지 않는다.
profile은 보호할 서비스와 oracle/checkpoint를 명시한 필수 scope 목록이다.

관측은 phase(baseline/test), scope, 대상 device/package/build, state
(stock/tampered/unknown), state_proof(fixture_attestation/missing), 서비스 outcome
(allowed/blocked/launch_only/crash/unknown), oracle(service_checkpoint/none),
block_reason(os_tamper/other/unknown/none)를 독립 필드로 보존한다.
fixture_attestation은 합성 상태 선언이며 실기기 증명이 아니다.
baseline과 test의 기기는 다를 수 있으나 각 phase의 명시 device와 일치해야 하고,
앱/build/service/checkpoint는 동일 profile과 일치해야 한다.
입력은 외부 evidence 경로나 임의 명령을 받지 않는다. 선택 route/packet 참조는
현재 사용하지 않으며 빈 목록만 허용한다.

manifest(JSON 문법의 YAML), common/SKILL.md 및 aos/SKILL.md 두 개를 제공한다.
manifest에 버전, 출처 provisional, 요구사항, 규칙, 범위, 제한 시간/취소/cleanup,
Skill hash 및 동일한 machine-readable rule contract를 기록한다. 누락, hash 불일치,
플랫폼/공통 규칙 충돌, unknown version은 실행 전 오류다. Skill은 절차 설명,
Python은 결정론적 검증과 실행을 담당한다. 임의 AI/자연어 판정은 없다.

## 판정

모든 판정은 선언한 합성 scope에만 적용한다. root/변조 상태 하나로 판정하지 않는다.

|판정|필수 조건|
|---|---|
|양호 pass|각 필수 scope에서 정상 stock baseline의 실제 서비스 이용 oracle, tampered 상태 증명, 동일 서비스 oracle의 차단 및 os_tamper 원인을 모두 확인|
|취약 fail|하나 이상의 coherent scope에서 정상 baseline, tampered 상태 증명, 동일 보호 서비스 실제 이용 oracle을 확인. 다른 scope 미완료보다 우선|
|판단 불가능 inconclusive|필수 근거 누락, baseline만 있음, unknown 상태, launch만 관찰, 원인 불명 crash, oracle 부재, 대상 불일치 또는 같은 phase/scope 관측 상충. reason_code와 구체 이유 필수|

동일 phase/scope 안의 상태·결과·원인 등 상충은 해당 scope를 불가능으로 처리한다.
다른 독립 scope의 입증된 fail은 유지한다. 각 scope의 결과와 근거·누락 이유를
저장하고 항목 수준에서 fail > incomplete > all pass 순서로 집계한다.

## 실행·증적·정리

execution_status는 completed/failed/timed_out/cancelled/not_run이고 verdict와 독립이다.
필수 profile이 비었거나 oracle 정의가 없으면 not_run/inconclusive.
잘못된 JSON/중복 key/unknown field/unknown version은 run 생성 전 command error.
관측 부족은 정상 처리 completed/inconclusive일 수 있다.

입력의 fault 설정으로 관측 전/관측 중 timeout, cancel, tool error 및 cleanup
failed/unknown을 결정론적으로 주입한다. CLI `--cancel`도 지원한다.
각 관측의 논리 비용과 manifest의 step/total deadline을 비교하며 실제 외부 프로세스
시간제한이나 기기 취소를 시험했다고 주장하지 않는다. 이미 수집·검증한 coherent
fail은 이후 오류/취소/cleanup 실패에도 유지한다. 미수집 scope는 미완료로 기록한다.
cleanup은 합성 상태 복원의 시뮬레이션이고, failed/unknown이면
follow_up_blocked=true, recovery_required=true. 이 값은 외부 스케줄러 잠금이 아니다.

run.json(입력/manifest/Skill snapshot), events.jsonl(순서, ID, UTC, tool call),
result.json(상태, 판정, scope, 이유, 제한, cleanup, 참조), evidence-index.json 및
blobs/*.json(관측 원본 envelope)을 생성한다. 모든 객체와 로그에 synthetic=true,
source/collection_method=synthetic_fixture를 유지한다. timestamp는 fixture 시작시각과
논리 시간이며 wall-clock 실측이 아님을 표시한다. duration도 synthetic logical ms.
실행 출력 디렉터리는 새 경로만 허용하고 기존 결과를 덮어쓰지 않는다.

출력은 schema와 semantic validator로 검증한다. ID 중복, run/check/attempt 오염,
잘못된 event/evidence 참조, 길이/hash 불일치, 누락 파일, 경로 탈출/symlink,
입력 관측과 blob/결과의 불일치, 증거 없는 또는 상충하는 판정을 거부한다.
완료 marker는 모든 쓰기와 검증 성공 후에만 생성한다. 저장 실패는 정상 완료로
표시하지 않는다. hash는 손상 탐지이며 합성 진실성/실기기 출처 인증이 아니다.
CLI exit: 0=실행 completed(취약/불가능 포함), 2=입력/계약/저장/검증 오류,
3=timeout, 4=cancel, 5=not_run. cleanup 오류는 execution=failed, exit 2이나
기존 verdict는 유지한다. 종료 명령 재호출 대신 새 run/output을 사용한다.

## 검증 게이트와 후속 조건

명세 commit 이후 구현한다. 표준 unittest 및 JSON Schema 검증으로 다음을 확인한다:

- pass/fail/inconclusive fixture 각 3회, 동일 판정·재현 가능한 산출물 및 참조 검증.
- 순정만/unknown/launch/crash/없는 oracle/baseline/변조 증명/대상 불일치/상충 근거.
- 여러 scope의 fail 우선, 부분 scope의 pass 금지, 없는/중복/틀린 증적 참조.
- malformed input, unknown version/field, 중복 JSON key, non-finite 수, 크기 제한.
- timeout, cancel, tool error, cleanup failed/unknown; 오류 이후 증명된 fail 유지.
- 파일 손상/누락/경로 탈출/symlink, 결과 변조, 저장 실패, 출력 재사용 거부.
- manifest/Skill 누락/hash/규칙 충돌 및 실제 기기/네트워크 호출 없음.

README에 실행법, docs/VALIDATION.md에 실제 명령·횟수·결과·한계를 기록한다.
push 직전 fetch/rebase 후 관련 테스트를 재실행하고 remote 포함 여부/CI를 확인한다.
실기기 검증은 P1 사용 종료, 승인된 전용 QA 앱/build와 변조 증명 방식,
정상 baseline, 보호 서비스/차단 oracle, 복원 절차, 단일 기기 lease 및 별도 실제
어댑터 구현·검증이 준비된 후 새로운 명세/승인 범위에서 수행한다.
