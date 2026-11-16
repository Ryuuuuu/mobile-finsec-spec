# CHK-07 common Skill v1 — synthetic only

이 절차는 내부 점검 ID CHK-07의 통제된 합성 fixture 판정 계약이다.
실기기 관측, 실제 금융 앱 평가, 공식 규정 인증을 수행하거나 주장하지 않는다.
Python 도구가 결정론적으로 입력·관측·증적·결과를 검증하고 이 Skill은 그 절차와
판정의 의미를 설명한다. GUI 또는 AI가 필요하지 않다.

```json
{"rule_contract":"CHK-07.synthetic.v1","synthetic":true,"schema_version":"1.0"}
```

## 필수 입력과 검사 범위

명시적 synthetic project/session/run/attempt/device ID, 합성 package/build,
보호 서비스와 checkpoint를 가진 필수 scope 목록 및 관측 fixture가 필요하다.
baseline/test의 device는 다를 수 있으나 각 phase에 선언된 device와 일치해야 한다.
scope/service/checkpoint/package/build는 정상 baseline과 변조 시험에서 같아야 한다.
route나 packet을 사용하지 않는다. scopes가 비었거나 checkpoint 정의가 없으면
실행하지 않고 구체 이유와 not_run/inconclusive를 남긴다.

## 절차와 판정

1. 입력 형식, manifest/Skill 버전과 hash, 공통·플랫폼 rule contract를 검증한다.
2. scope별 정상 stock 상태 증명과 protected-service 이용 oracle을 확인한다.
3. test phase의 tampered 상태 증명과 같은 보호 서비스 이용/차단 oracle을 읽는다.
4. 관측 대상·근거의 누락 및 같은 phase/scope 내 상충을 먼저 검사한다.
5. 각 scope를 판정하고, coherent fail 하나가 있으면 항목은 fail로 집계한다.
   fail이 없고 필수 scope가 하나라도 불완전하면 inconclusive다. 모든 scope가
   정상 baseline·변조 증명·서비스 차단·os_tamper 차단 원인을 확인할 때만 pass다.
6. 실행 상태와 판정, 실제 확인 범위, 미확인 범위, 이유, 증적 참조를 별도로 저장한다.
7. 합성 cleanup을 실행하고 복원 결과 및 후속 진행 차단 여부를 기록한다.

`fixture_attestation`은 합성 상태 선언이다. 진짜 단말의 rooting 또는 변조 증명이
아니다. 변조 상태 단독, 순정 baseline 단독, 단순 package launch, 원인 불명 crash,
oracle 부재로 양호를 만들지 않는다. 팝업/프로세스/HTTP 상태 하나로 판정하지 않는다.
상충하는 같은 scope의 관측은 취약 우선 규칙으로 덮지 않는다. 다른 독립 scope에서
일관된 취약 증거가 이미 성립했다면 해당 취약은 보존하고 미완료 scope를 명시한다.

## 증적과 종료

원본 관측 envelope, run/check/attempt/tool/event/scope 참조, 합성 시간과 출처,
byte length 및 SHA-256을 보존한다. hash는 손상 탐지이고 관측 진실성 인증이 아니다.
result validator는 형식뿐 아니라 관측에서 판정을 다시 계산하고 필수 근거와 참조를
대조한다. 누락·변조·다른 run 참조를 정상 완료로 받아들이지 않는다.

timeout/cancel/tool error는 execution_status이며 보안 판정이 아니다. 관측을 추가로
수집하지 않고 cleanup을 기록한다. 이미 확인된 취약은 후속 중단 또는 cleanup 실패
때문에 inconclusive로 덮어쓰지 않는다. cleanup 실패/unknown이면 recovery_required와
follow_up_blocked를 설정한다. 이것은 외부 스케줄러의 실제 잠금을 보장하지 않는다.
모든 산출물은 synthetic 표시를 유지한다. 실제 어댑터가 없으므로 실기기 판단은 하지
않으며 향후 별도 승인된 QA 어댑터 검증이 필요하다.
