# P3 CHK-07 — synthetic-only Android OS tamper contract PoC

OS 변조 상태에서 보호 서비스의 차단/허용 근거를 판단하는 독립 Python 도구입니다.
**현재 입력과 출력은 모두 통제된 synthetic fixture입니다. 실제 Android 어댑터는
없습니다. 실제 금융 앱 평가 또는 공식 규정 인증이 아닙니다.** GUI, AI, P1/P2,
ADB, Appium, 네트워크, 실제 기기를 사용하지 않습니다.

[실행 명세](docs/EXECUTION-SPEC.md)를 구현 전에 별도 커밋했습니다.
[검증 결과](docs/VALIDATION.md), [공통 Skill](checks/CHK-07/common/SKILL.md),
[AOS Skill](checks/CHK-07/aos/SKILL.md), [manifest](checks/CHK-07/manifest.yaml)를
함께 확인하세요. manifest는 JSON 문법의 유효한 YAML이며 별도 YAML 파서가 필요 없습니다.

## 실행

Python 3.11 이상. 저장소 루트에서 다음 폴더로 이동합니다.

```sh
cd pocs/p3-android-os-tamper
python -m pip install -r requirements.txt
python -m os_tamper run --input fixtures/pass.json --output /tmp/p3-pass
python -m os_tamper validate --output /tmp/p3-pass
python -m os_tamper run --input fixtures/fail.json --output /tmp/p3-fail
python -m os_tamper run --input fixtures/inconclusive.json --output /tmp/p3-inconclusive
python -m unittest discover -s tests -v
```

Windows에서는 `/tmp/p3-pass` 대신 새 로컬 경로를 사용하세요. 기존 output 경로는
덮어쓰지 않습니다. 다시 실행할 때 새 output 및 새 synthetic run_id를 지정합니다.
fixture의 고정 run_id는 재현 시험용입니다. 여러 반복 결과를 실제 단일 run처럼
합치면 안 됩니다. 생성 폴더는 Git 외부에 보관합니다.

|명령 exit|의미|
|---|---|
|0|run: 실행 completed(양호/취약/불가능 모두 가능), validate: bundle 검증 통과|
|2|입력·계약·저장·검증 오류 또는 failed 실행|
|3|timed_out|
|4|cancelled|
|5|선행조건 부족 not_run|

`--cancel`은 실행 전 취소를 재현합니다. fixture의 `faults.interrupt_after`는 성공적으로
수집한 관측 수이고 `interrupt_kind`는 `timeout/cancel/tool_error`입니다.
`faults.cleanup=failed/unknown`은 합성 정리 오류입니다. 정상값은 각각 null/none/completed.
관측 `cost_ms`와 step 1,000ms/total 10,000ms 제한은 **논리 시간**입니다. 실제 외부
도구 timeout이나 SIGINT 이후 기기 정지 검증으로 해석하면 안 됩니다. OS 강제 종료나
SIGINT로 쓰기가 중단되면 marker 없는 미완료 폴더를 성공 이력으로 사용하지 않습니다.

## 판정과 근거

`execution_status`와 `verdict`는 독립입니다. 루팅·변조 여부만으로 판정하지 않습니다.
모든 scope는 같은 앱/build/보호 service/checkpoint를 가진 정상 baseline과 비교합니다.
fixture의 `fixture_attestation`은 합성 상태 선언이며 실기기 증명이 아닙니다.

- `pass`: 선언한 모든 scope에서 순정 정상 이용, 변조 증명, OS 변조에 의한 보호 서비스 차단을 확인.
- `fail`: 하나 이상의 일관된 scope에서 정상 baseline, 변조 증명, 보호 서비스 이용을 확인.
- `inconclusive`: baseline만 있음, unknown 상태, launch/crash, oracle/상태 증명 누락,
  대상 불일치, 상충 근거, 일부 필수 scope 또는 예정 관측 미완료. 이유를 반드시 보존.

입증된 취약은 다른 scope 부족이나 후속 timeout/취소/cleanup 오류로 덮어쓰지 않습니다.
같은 scope의 상충 근거는 그 scope의 판정을 불가능으로 만듭니다. cleanup failed/unknown은
`follow_up_blocked=true`, `recovery_required=true`를 별도로 기록합니다. 완료 실행만 failed로
전환하고 기존 timeout/cancel/not_run은 유지합니다. 이 flag는 외부 프로세스나 실제 기기를
잠그지 않습니다. 추후 실행 관리자가 읽고 진행을 차단해야 합니다.

## 산출물과 검증

```text
run.json              입력, manifest/Skill 원문 snapshot, run/session/check/attempt
events.jsonl          시퀀스, UTC 논리 시각, tool-call, event/evidence 참조
result.json           판정, 실행 상태, 각 scope, 근거, 제한, 정리/후속 차단
evidence-index.json   관측별 길이, SHA-256, blob 위치와 event/observation 참조
blobs/*.json          synthetic 관측 원본 envelope (실제 단말 증적 아님)
finalized.json        모든 저장·검증을 마친 뒤 기록하는 완료 marker
```

`schemas/`의 versioned JSON Schema와 Python semantic validator를 함께 사용합니다.
형식·날짜·버전·중복 ID/key·범위 외 입력을 거부합니다. 최대 입력 1MiB, 100관측,
10 scope. 빈 scope 또는 checkpoint 정의 없음은 not_run입니다. 빈 관측은 정상 처리된
inconclusive입니다. route/packet 참조는 현재 빈 목록만 허용합니다.

검증기는 저장된 입력과 immutable manifest/Skill snapshot을 사용해 결정론적으로
bundle을 재생성하여 모든 결과·event·증적을 바이트 단위로 대조합니다. 누락, 변조,
다른 run 참조, 잘못된 판정, 경로 탈출과 symlink를 거부하며 원결과를 수정하지 않습니다.
hash는 손상 탐지이며 원본 관측의 진실성이나 서명이 아닙니다. 입력과 전체 bundle을
함께 다시 작성한 공격자의 진위는 이 도구로 인증할 수 없습니다.

각 파일은 새 파일 생성+flush+fsync로 저장하고 완료 marker를 마지막에 만듭니다.
저장 실패 시 완료를 주장하지 않으며 남은 부분 폴더는 검증에서 거부합니다.
전원 장애에 대한 파일시스템 전체 transaction이나 자동 복구는 구현하지 않았습니다.

## 다음 검증 조건

P1의 기기 사용 종료 후 별도 승인된 QA 앱/build, 정상 서비스 baseline, 변조 상태 증명,
보호 서비스와 차단 원인 oracle, 단일 기기 소유·취소·복원 계약을 먼저 확정해야 합니다.
그 후 실제 어댑터를 별도 구현·검증합니다. 현재 결과는 그 검증을 대체하지 않습니다.
공식 원본의 ID·버전·적용 플랫폼 대조도 별도 게이트입니다.
