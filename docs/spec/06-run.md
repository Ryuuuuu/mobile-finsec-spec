# 06. 순차 실행·취소·복구·최종화

상태: 상세 설계 채택안. 구현은 이후 독립 PoC로 검증한다.

## 기능과 분류

RUN-01 immutable run plan, RUN-02 단일 기기 순차 scheduler, RUN-03 main/item AI 감시, RUN-04 실시간 상태/로그, RUN-05 취소·정리, RUN-06 재시작 복구, RUN-07 최종 결과 봉인. 공통 실행 기반 기능이다.

메인 AI는 검사 계획·항목 수행 지시·결과 검토를 담당한다. Python 실행 관리자는 실제 시작 권한, 순서, timeout, 취소, cleanup, 다음 항목 허용을 결정한다. 프롬프트만으로 동시성을 제어하지 않는다.

## 상태 모델

Run: `created → preflight → preparing → running → finalizing → completed`.
취소: `created|preflight|preparing|running → cancelling → finalizing → cancelled`. preflight를 독립 조회한 것만으로 run 이력을 만들지 않는다. START에서 run ID가 발급된 뒤에는 preflight 실패/취소도 terminal history로 남기며 선택 항목은 not_run + 판단 불가능 + 이유를 가진다. START 수신 전 형식 validation 오류는 command error이며 run을 만들지 않는다.
오류·중단: `failed / interrupted`도 finalization을 거쳐 terminal history에 남는다.

Item: `queued → preparing → running → cleaning → completed`. M 절차는 running에서 `awaiting_manual_evidence`로 전환 후 근거 제출/검토가 끝나면 cleaning으로 간다. 대기 timeout/취소는 이유를 남기고 finalization으로 이어진다.
종료 분기: `failed / timed_out / cancelled / not_run`.
실행 상태와 보안 판정은 별도 필드다. 실행 완료가 양호를 뜻하지 않는다.

최종화가 실패하면 `finalizing_failed` 상태로 보존하고 완료 표시를 하지 않는다. 증적 저장/결과 검증 재시도는 가능하지만 기기 테스트 자체를 자동 재실행하지 않는다.

## 단일 기기 소유와 fencing

API 실행 관리자만 기기 작업 lease를 발급한다. recording 입력, replay, item tool 모두 같은 device ID 소유권을 사용한다. lease는 owner ID, boot_epoch, 영속 단조 증가 generation/fencing token, attempt ID, acquisition time, heartbeat, lifecycle를 가진다. 재시작 시 boot_epoch를 바꾸고 durable generation을 증가시켜 과거 token을 재사용하지 않는다.

모든 기기 변경 tool 요청은 device ID와 owner/generation을 제출한다. Gateway는 현재 boot_epoch/generation/attempt와 일치하지 않거나 cleanup 중인 일반 agent 요청을 거부한다. 이전 agent의 지연된 호출은 새 run의 기기를 건드릴 수 없다.

lease 만료는 다음 작업 시작 허가가 아니다. 이전 process/tool 종료와 cleanup 확인이 먼저다. 미확인 시 `recovery_required`로 두어 신규 lease를 막는다. DB lock 또는 Python mutex만으로 외부 CLI의 직접 ADB 접근까지 방지했다고 주장하지 않는다. 모든 backend가 gateway를 우회하지 못하는 실행 격리를 별도 검증한다.

RECORD와 SCAN은 동시에 시작하지 않는다. run 시작은 기록 종료·seal 완료 후 가능하다. 항목 agent는 하나만 active하며 다음 항목은 이전 도구 종료·cleanup 성공 후 시작한다. 텍스트 요약 작업 병렬화도 초기 범위에서 제외해 상태 모델을 단순화한다.

## 실행 snapshot과 이벤트

run plan에는 selected checks/variants, Skill 및 config hash, provider/model 정보, device/app/artifact snapshot, route/packet 범위와 coverage, 요구 capability를 저장한다. 실행 중 설정 변경은 기존 run에 영향을 주지 않는다.

명령에 command ID를 사용한다. 동일 START ID 반복은 같은 run ID를 반환한다. 다른 START ID라도 device busy이면 실행을 거부한다. 형식 검증 후 run ID가 이미 발급되었다면 busy 사유로 선택 항목을 not_run으로 최종화한다. STOP 반복은 같은 취소 요청 상태를 반환한다.

이벤트에는 event ID, run/check/tool-call ID, sequence, timestamp, source, type, payload를 둔다. UI 재연결은 마지막 seq 이후 replay 또는 snapshot으로 복구한다. UI는 이벤트의 run ID를 확인하고 다른 이력 화면을 덮어쓰지 않는다.

## Watchdog와 hang

Watchdog는 AI 밖의 결정론적 supervisor다. main AI도 item 상태를 관찰하지만 main AI 자체 장애를 독립 watchdog가 탐지한다.

분리 관측: process alive, heartbeat, last progress, active tool, tool deadline, item deadline, device connection. 출력이 없다는 사실 하나로 hang을 확정하지 않는다. tool은 자체 timeout을 갖고 item 전체 timeout과 구분한다. 초기 기본값은 manifest의 검증된 procedure별 값이며 공통 무제한 timeout을 허용하지 않는다.

AI 종료·item hang·proxy 장애·device unplug·tool timeout은 서로 다른 error code다. device unplug이면 진행 중 device tool을 중단하고 이후 항목을 시작하지 않는다. 연결이 돌아와도 명시적 재검증 없이 자동 계속하지 않는다.

## 취소와 정리

중지는 즉시 UI에 cancelling을 표시한다. 새 tool 요청을 차단하고 활성 tool에 취소를 전달한다. grace period 이후 강제 종료 가능하나 종료 여부를 확인해야 한다. tool cancellation 미지원 backend는 capability로 표시하고 해당 device 작업 실행을 허용하지 않는 것이 기본이다.

취소/오류 시 일반 agent 실행 capability를 먼저 revoke한다. cleanup은 supervisor만 발급 가능한 별도 제한 token으로 journal에 선언된 정리 동작만 허용한다. 이 token은 새 검사 동작이나 임의 shell 권한을 부여하지 않는다. cleanup은 재실행 가능한 작은 단계와 변경 journal을 가진다. fixture 계정 상태, 앱 설치/교체, routing hook, 임시 파일/프로세스 등 해당 항목이 변경한 자원을 대상으로 한다. 이미 존재하던 사용자 자원을 무조건 삭제하지 않는다.

cleanup 실패 시 원래 verdict가 있어도 environmental cleanup 오류를 별도로 보존한다. 신규 검사 차단 이유와 복구 필요 동작을 표시한다. timeout만 기다리고 device lock을 푸는 구현은 금지한다.

## 항목 실패 후 진행 정책

- 정상 절차 완료(판정이 취약 또는 판단 불가능인 경우 포함) + cleanup 성공 + side effect known: 다음 항목 진행.
- read-only 분석 실패/증거 부족 + device 영향 없음이 확인 + cleanup 성공: 해당 항목 failed/판단 불가능으로 종료하고 다음 항목 진행.
- device 변경 tool 오류/timeout: side effect 결과를 supervisor가 확인하고 manifest 복원/재검증을 모두 통과한 경우에만 다음 항목 진행.
- side_effect_state=unknown, device unplug, 권한/소유 위반, cleanup 실패, supervisor/main 복구 불가: 전체 run을 중단한다. 후속 항목은 not_run으로 남긴다.
- 사용자 cancel: 결과 유무와 무관하게 다음 항목을 시작하지 않는다.

side effect unknown을 '실패했으니 아무 일도 없었음'으로 취급하지 않는다. 자동 재시도는 기본 비활성이고, 허용된 read-only/idempotent operation만 동일 attempt 계약으로 제한한다.

## 실행중 UI와 최종화

점검 탭에서 선택한 항목 상태/현재 agent/대기열/실시간 로그·heartbeat를 표시한다. 결과 로그 탭으로 자동 이동하지 않는다. 실행중 project/device/app/route/checkbox는 비활성화하며 이유를 제공한다. 기기 화면 관찰은 가능하지만 입력/back/home/recent는 비활성화한다. 자물쇠 overlay는 추가하지 않는다. 탭 전환·과거 결과 조회는 허용한다.

Finalizer는 선택 항목 전부의 terminal execution status, verdict, reason, evidence refs, tested scope, limitations를 검증한다. 완료된 일부 결과는 유지하며 미실행 항목은 not_run + 판단 불가능 + 이유로 남긴다. 미선택 항목을 결과 건수에 포함하지 않는다. 결과/증적 metadata를 transaction으로 확정한 뒤 terminal history에 게시한다.

앱 재시작 시 active run은 interrupted 후보로 읽는다. 관리 프로세스 생존/소유를 확인하고 정리한다. 확인 없는 PID만으로 임의 프로세스를 종료하지 않는다. 자동 transaction replay나 자동 이어하기는 지원하지 않는다. 재검사는 새 run ID를 만든다.

## 인수 기준

1. 동시에 10개 START를 보내도 동일 device의 active run은 최대 하나다.
2. 이전 generation tool 요청이 새 run 도중 도착하면 실행되지 않는다.
3. cancel 후 느린 tool이 남아 있으면 다음 항목이 시작되지 않는다.
4. cleanup failure는 recovery_required로 보존되고 재시작 후에도 차단된다.
5. main/item process crash, tool timeout, device unplug를 각각 구분한다.
6. 정상적으로 오래 실행되는 tool이 heartbeat만으로 hang 오판되지 않는다.
7. 중복 STOP, UI 재연결, 탭/이력 변경에도 run 상태와 로그가 일치한다.
8. 중간 중단은 완료된 결과를 잃지 않고 모든 선택 항목의 최종 상태를 남긴다.
9. finalization DB 오류에서 completed를 표시하지 않는다.
10. 재시작은 실제 기기 작업이나 거래 재전송을 자동 반복하지 않는다.
11. 재시작 이전 token/attempt가 모두 거부되고 supervisor cleanup token만 journal 범위에서 작동한다.
12. side effect unknown은 후속 항목 중단, 확인된 read-only 실패는 후속 진행 정책을 따른다.

## 검증 게이트

fake provider/tool의 지연·hang·취소 무시·늦은 이벤트·cleanup 실패 fault injection으로 먼저 검증한다. 이후 실제 ADB/Appium/relay/backend 자식 프로세스 종료 능력과 gateway 강제 경계를 실기기에서 확인한다. 테스트 완료 전 '완전한 격리' 또는 '자동 복구 보장'을 선언하지 않는다.
