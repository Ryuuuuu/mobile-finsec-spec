# P3 CHK-07 검증 기록 — synthetic only

검증일: 2026-11-16 UTC. 환경: 클라우드 Linux, Python 3.12.14,
jsonschema 4.26.0. Python 최소 지원 선언은 3.11이며 이번 실제 실행은 3.12에서 했다.
실행 명세를 구현 전에 별도 commit한 뒤 구현·독립 검토·회귀 검증했다.

**실제 기기/ADB/Appium 접속, 금융 앱 평가, 공식 규정 인증은 수행하지 않았다.**
시험 입력·관측·산출물·시간은 전부 synthetic이다. fixture 상태 선언은 실제 단말의
변조 증명이 아니며, 결과는 검사 계약의 동작을 검증한다.

## 실행한 명령과 결과

PoC 디렉터리에서:

```sh
python -m unittest discover -s tests -v
```

결과: **58 tests, OK, exit 0**. subTest를 포함하지만 58은 unittest test method 수다.
핵심 수용기준 시험은 다음과 같다.

|시험|확인 결과|
|---|---|
|pass/fail/inconclusive 각 3회|각각 3/3 기대 판정, completed, 동일 fixture의 전체 bundle byte 동일|
|순정 baseline만/관측 없음/unknown/증명 누락|자동 양호 금지, 이유 있는 inconclusive|
|launch/crash/oracle 없음/원인 미확인 차단|서비스 차단·이용 증거로 확대하지 않음|
|baseline 불충분/대상·build·서비스 불일치|inconclusive|
|같은 scope 상충/복수 scope 일부 부족|상충 scope 불가능; 전체 양호 금지|
|독립 scope의 입증된 취약|다른 scope 부족·상충보다 fail 우선|
|timeout/cancel/tool_error|관측 전·중간 중단, cleanup 기록, 미관측 성공 금지|
|입증된 취약 이후 timeout/cancel/tool_error|실행 상태와 fail 판정 독립 유지|
|cleanup failed/unknown|fail 보존, failed 실행 및 follow_up_blocked/recovery_required|
|step/total 논리 timeout|한계 초과 관측 미수집, 예정 scope 미완료는 pass 금지|
|JSON/계약 이상|malformed/중복 key/비유한 수·overflow/unknown version·field/실제 모드/날짜/중복 ID/범위 외 참조 거부|
|manifest/Skill 이상|필수 필드/Skill 누락, hash/규칙 충돌, updated hash와 synthetic 타입 변조 거부|
|결과·증적 이상|누락·수정·다른 run/잘못된 참조·중복·길이/hash·event 순서 변조 거부|
|경로·저장|path traversal/외부 참조/symlink, 기존 출력 재사용 거부|
|저장·최종 marker fsync 실패|최종화 marker 미게시, 정상 bundle 검증 거부|
|기기 접근 경계|core에서 socket/Popen 호출 시 실패하도록 patch한 테스트 통과|
|CLI|completed 0, 오류 2, timeout 3, cancel 4, not_run 5; validate 성공 0|

별도로 CLI를 통해 3개 fixture를 각 3회 실행하고 각각 `validate`를 실행했다:

```sh
python -m os_tamper run --input fixtures/pass.json --output /tmp/p3-pass-1
python -m os_tamper validate --output /tmp/p3-pass-1
# fixture 이름을 fail/inconclusive로, output을 반복마다 새 경로로 바꾸어 각 3회
```

**실행 9/9, bundle 재검증 9/9, 모두 exit 0**, 각 실행의 evidence 2개 확인.
실행별 요약은 [validation-summary.json](validation-summary.json)에 있다.
실제 생성 폴더는 Git 외부의 임시 synthetic 폴더였고 원본 bundle을 저장소에 게시하지 않았다.

`Draft202012Validator.check_schema`로 `schemas/*.schema.json` **8/8** meta 검사 통과.
각 bundle 최종화는 input/manifest/run/result/event/evidence/index의 구조 검사와
결정론적 재계산을 수행한다. 완료 marker는 후속 validate에서 별도 검사한다.
`git diff --check`도 통과했다.

## 검토 후 보완한 경계

- 같은 scope의 예정 관측이 남아 있으면 차단 관측이 있어도 pass하지 않는다.
- marker는 임시 파일의 fsync 성공 후 원자적으로 게시해 마지막 쓰기 오류를 완료로 오인하지 않는다.
- microsecond 시작시각을 보존해 종료시각 절삭 역전을 막는다.
- 잘못된 manifest root·필수 정책 누락과 도달 불가능한 fault 설정은 명확한 계약 오류다.
- 지원 버전의 manifest 판정/절차 문구를 고정하고 Skill structured rule과 hash를 검사한다.

## 남은 검증 게이트

실제 Android 어댑터, 실기기/Windows 인수시험, 전원 장애 transaction, 기기 lease,
외부 도구의 실제 deadline·취소·복원, GUI/AI 통합은 구현·검증 범위 밖이다.
P1 기기 사용 종료 후 별도 QA 앱/build, 정상 baseline, 변조 증명 방법, 보호 서비스
완료/차단 oracle, 복원 및 단일 기기 소유 계약이 준비되어야 실기기 검증을 시작할 수 있다.
공식 원본과 내부 CHK-07 ID·범위 대조도 아직 필요하다.

GitHub CI 설정은 검증 시점의 저장소에 없었다. 로컬 테스트 성공을 CI 성공으로 표시하지 않는다.
게시 직전 remote fetch/rebase 및 관련 테스트 재실행, 게시 후 remote 포함 여부 확인은
작업 대화의 최종 커밋 SHA와 함께 보고한다.
