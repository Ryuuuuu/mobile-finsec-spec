# P4 클라우드 검증 보고서

2026-11-17 UTC. **synthetic/fake 최소 결합만 검증했다.** 사용자 PC, GUI, 실기기,
실제 모델, 실제 금융 앱·packet·인증정보는 사용하지 않았다.
기계 판독 결과는 [validation-summary.json](validation-summary.json)에 있다.

## 변경과 커밋 단계

- 시작 기준선: `631e1ad` (`main`, P2/P3 기존 구현 포함).
- 구현 전 설계/계약/합격 조건: `c2b57cdfb113ae27fb50a672ea5b509c41f13c2d`.
- 구현과 테스트 코드: `a9281bde845f3ce7ff6450e1dfc57a2f9572390e`.
- 본 검증 보고서는 구현 뒤 별도 커밋한다. 마지막 보고서 커밋 SHA와 원격 HEAD의
  일치는 push 후 `git ls-remote origin refs/heads/main`으로 확인해 전달한다.

모든 변경은 `pocs/p4-integration` 아래다. 기존 P1/P2/P3와 상위 설계는 수정하지 않았다.
명세의 과거형 주장과 실제 실행 결과를 구분하며, 이 문서는 아래 실행의 결과다.

## 환경과 명령

Linux x86_64 cloud, Python 3.12.14, SQLite 3.53.1, jsonschema 4.26.0.
P4 requirements는 기존 P3의 고정된 jsonschema 의존성을 재사용한다.
이번 환경에는 해당 버전이 이미 설치되어 있었다.

저장소 루트 기준 각 명령을 실행했다:

```bash
(cd pocs/p4-integration && python -m unittest discover -s tests -v)
(cd pocs/p2-proxy-relay && python -m unittest discover -s tests -v)
(cd pocs/p3-android-os-tamper && python -m unittest discover -s tests -v)
```

|suite|unittest test method 수|시간|결과|
|---|---:|---:|---|
|P4|126|14.477s|통과|
|기존 P2 회귀|38|3.133s|통과|
|기존 P3 회귀|58|3.861s|통과|
|합계|222||통과|

P4 구성: CLI 10, plan/history 계약 19, lease 16, P2 adapter 13, P3 adapter 12,
fake provider 14, 검토 회귀 5, supervisor 통합 37. subTest/fixture case는
test method 수에 별도로 더하지 않았다. 시간은 이 cloud 실행값이며 성능 보장이 아니다.

## 확인한 동작과 실패 경로

- 실제 기존 P2 loopback relay로 요청/응답 1건을 전달하고 SQLite packet·payload hash를
  재조회했다. OFF에서는 coverage none/0을 확인했다. upstream 실패 partial, 취소 도중
  startup/command, listener·handler·writer·DB lock 회수를 검증했다.
- 실제 기존 P3 평가기와 bundle validator로 세 판정, common+AOS Skill snapshot,
  run/session/attempt/device, 증적 hash·namespace를 검증했다. P2 참조를 CHK-07 근거에
  넣지 않았고 P3 route_refs/packet_refs는 빈 목록이었다.
- 정상 무출력 provider, main/item error·빈 종료·heartbeat 단절·진행 hang,
  run/item/tool deadline, fake disconnect를 분리했다. main은 계획 제안 후 종료하는
  축소 모델이며 상시 실행 중인 실제 main AI를 검증한 것은 아니다.
- 10개 START 경쟁, 다른 manager 및 독립 프로세스의 동일 DB lease 경쟁에서 한 소유자만
  허용했다. stale owner/epoch/generation/attempt/operation과 cleanup 중 일반 요청을 거부했다.
- 반복 START/STOP, cancel 즉시 revoke, 취소 무시 후 늦은 결과 제외, 이전 item의
  늦은 이벤트 제외, 정상 정리 뒤 새 generation, 실패 뒤 재시작 차단을 확인했다.
- 동기 P3 thread 실행 중 취소에서 wrapper 취소를 종료로 오인하지 않고 quarantine했다.
  P2 cleanup timeout/실패, provider cancel RPC 오류/대기, lease 저장 오류도 시험했다.
  cleanup이 뒤늦게 끝나도 영속 quarantine을 자동 해제하지 않았다.
- 실행 완료와 양호를 구분하고 이미 확인한 취약은 후속 실패 시 유지했다. 뒤의 미실행
  항목은 not_run/inconclusive+사유로 최종화했다.
- 실행 이벤트는 별도 seq/run stream으로 제공했고 history는 최종 결과만 반환했다.
  finalization I/O 오류는 finalizing_failed이며 정상 이력에 게시하지 않았다.
- 누락 선택 항목, 빈/공백 사유, 증거 없는 pass·완료, 다른 run/item 증적 교환,
  P3와 다른 실행 상태/범위/cleanup 표시, 증적 훼손, 경로 탈출을 거부했다.

검토 중 발견한 취소 후 completed 게시, 늦은 이벤트의 새 token 사용,
최종 결과의 선택 항목/증적 바꿔치기 허용 문제를 수정하고 회귀 테스트를 추가했다.

## CLI 데모

자동 테스트와 별도로 10개 demo scenario를 새 `/tmp/p4-validation-*` 하위에서 실행했다.
각 결과에 `validate --run`을 실행하여 통과했고 `history --output`은 정확히 1개
최종 결과를 반환했다. 원본 runtime 산출물/DB는 저장소에 넣지 않았다.

```bash
WORK=$(mktemp -d /tmp/p4-demo-XXXXXX)
python -m integration demo --scenario normal --output "$WORK/normal"
python -m integration history --output "$WORK/normal"
# demo JSON의 output 경로를 사용:
python -m integration validate --run /tmp/p4-demo-XXXXXX/normal/synthetic-run-UUID
```

위 명령은 `pocs/p4-integration`에서 실행한다. 실패 demo는 README의 동일 방식으로
scenario를 바꾸고 새 output을 준다. `normal`은 completed와 양호 1/취약 1/불가능 1,
proxy-off도 세 판정은 같지만 P2 none/0이다. main-error는 exit 2, main/item hang과
tool-timeout은 exit 3, cancel/ignored-cancel은 exit 4다. ignored-cancel은
recovery_required=true이고 cleanup-failed는 확인한 취약 1을 보존한 채 exit 2다.
disconnect도 recovery_required=true/exit 2다. 전체 상태는 JSON 보고서에 보존했다.

## 미검증과 다음 게이트

**P1/GPUI/실제 모델/실기기 통합은 미검증**이다. P1의 별도 Android 실기기 CLI
재생 3회 성공은 GUI 기록 검증이 아니며 P4 전체 통합 성공으로 확대하지 않는다.
P2 38개는 제한 HTTP/1.1 synthetic, P3 58개는 CHK-07 synthetic 회귀 범위다.

- IOS Skill/실기기, P1 route/replay/기록 없는 launch, gpui-kit 점검·결과 화면 없음.
- 모델 API/CLI, 인증·외부 전송, 두 실제 provider 교체 검증 없음. `fake-a/b`는 같은
  fake 구현의 설정 교체이며 모델 호환성을 입증하지 않는다.
- lease 보장은 같은 SQLite 저장소를 쓰는 협력적 gateway 범위다. 외부 CLI의 ADB 접근,
  악성 provider, 서로 다른 DB를 쓰는 실제 기기 공유까지 격리한 것이 아니다.
- Python thread 강제 종료, 영구 filesystem stall, OS/process 강제 격리/kill은 미검증이다.
  살아 있는 작업과 불확실한 cleanup은 차단하며, 실제 복구 성공을 주장하지 않는다.
- durable START cache, 자동 resume/recovery, 전체 RUN/AI 계약과 production migration,
  전원 차단 내구성, 전체 UI 재연결·history 기능은 이번 범위 밖이다.

실기기 통합은 승인된 전용 QA 대상, P1 사용 종료/소유권 공유, 실제 gateway 격리,
프로세스 종료·복원 증명과 별도 실행 명세가 준비된 이후의 게이트다.
