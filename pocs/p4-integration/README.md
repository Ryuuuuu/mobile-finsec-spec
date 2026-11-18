# P4 최소 통합 PoC — synthetic / fake only

Python supervisor가 단일 합성 기기에서 fake main/item provider와 **기존 실제 P2/P3
코드**를 순차 연결한다. [구현 전 명세](docs/EXECUTION-SPEC.md)를 먼저 커밋했으며,
실행한 검증과 결과는 [검증 보고서](docs/VALIDATION.md)에 별도로 기록한다.

**P1, GPUI/gpui-kit, 실제 모델, 실기기 통합은 미검증**이다. P1의 별도 Android CLI
3회 성공은 GUI 기록 검증이나 P4 성공을 뜻하지 않는다. P2 최초 HTTP 38개/P3 58개 기존 테스트도
제한된 synthetic 검증이다. 사용자 PC·GUI·실기기를 사용하지 않는다.

## 구성과 경계

|구성|이번에 실행하는 것|주장하지 않는 것|
|---|---|---|
|Supervisor / lease|SQLite 트랜잭션, 세대·attempt fencing, watchdog, cancel/cleanup, 최종화|실기기/외부 CLI의 OS 격리|
|Main / item provider|모델 비종속 API와 `fake-a`, `fake-b` 설정|두 실제 모델의 호환성·AI 판단|
|P2 adapter|기존 Relay로 loopback HTTP/1.1 1건 전달·기록·검증, OFF 빈 기록|실제 앱 귀속, TLS, 전체 패킷 수집|
|P3 adapter|기존 CHK-07 fixture 실행·증적 재검증, common+AOS Skill snapshot|실제 Android 변조 검사|
|선택 항목|CHK-07의 pass/fail/inconclusive **fixture variant** 3개|서로 다른 공식 점검 3개|

main은 선택 순서를 제안한 뒤 정상 종료하고, 각 item은 허용된 P3 작업을 제안한다.
Python만 실행 권한을 발급하며 provider의 자체 판정은 채택하지 않는다. 정상 종료,
비정상 종료, 오류, heartbeat 단절, heartbeat는 있지만 진행 없는 hang을 구분한다.
무출력 작업도 heartbeat/progress와 deadline 안에서 정상이면 허용한다.

원래 앱 방향은 gpui-kit **점검 탭에서 체크 후 실행**, common Skill 필수와 AOS/IOS
Skill 선택, 단일 기기 순차 수행이다. UI는 구현하지 않았다. 이번 AOS만 지원하며
IOS는 거부한다. P1 route/기록 없는 package launch는 adapter 자체가 없다.

## 재현: Linux 클라우드, Python 3.11+

저장소 루트에서 환경을 준비한다. Android SDK, ADB, Appium, 모델 키가 필요 없다.

```bash
cd pocs/p4-integration
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

정상 CLI 데모는 실제 P2 synthetic HTTP 1건과 실제 P3의 세 판정을 연결한다.
`completed`는 보안상 양호라는 뜻이 아니다. 정상 결과는 양호 1/취약 1/판단 불가능 1이다.

```bash
WORK=$(mktemp -d /tmp/p4-demo-XXXXXX)
python -m integration demo --scenario normal --output "$WORK/normal"
python -m integration history --output "$WORK/normal"
```

첫 명령 JSON의 `output`을 복사하여 검증한다 (`workspace`는 history용 루트).

```bash
python -m integration validate --run /tmp/p4-demo-XXXXXX/normal/synthetic-run-UUID
```

각 demo의 output은 **새 경로**여야 한다. 같은 경로를 다시 사용하면 덮어쓰지 않고
`OUTPUT_EXISTS`, exit 2로 거부한다. runtime DB/증적은 Git에 포함하지 않는다.

```bash
python -m integration demo --scenario tool-timeout --output "$WORK/timeout"
python -m integration demo --scenario cancel --output "$WORK/cancel"
python -m integration demo --scenario ignored-cancel --output "$WORK/ignored"
python -m integration demo --scenario cleanup-failed --output "$WORK/cleanup"
```

위 실패 명령의 nonzero exit는 의도한 시험 결과다.

|scenario|기대 상태 / 코드|후속 소유권|
|---|---|---|
|normal / proxy-off|completed / 0|정리 후 free; OFF는 coverage none/0|
|main-error|failed / 2, MAIN_ERROR|종료·정리 확인 후 free|
|main-hang / item-hang|failed / 3, MAIN_HANG / ITEM_HANG|현재 run 중단, 정리 확인 후 free|
|tool-timeout|failed / 3, TOOL_TIMEOUT|현재 run 중단, 정리 확인 후 free|
|cancel|cancelled / 4|취소·정리 확인 후 free|
|ignored-cancel|cancelled / 4|미종료 fake를 확인하여 recovery_required|
|cleanup-failed|failed / 2|검증된 취약 유지, recovery_required|
|disconnect|failed / 2, DEVICE_DISCONNECTED|가짜 연결 해제, recovery_required|

P2/P3 회귀 테스트도 독립 실행한다.

```bash
(cd ../p2-proxy-relay && python -m unittest discover -s tests -v)
(cd ../p3-android-os-tamper && python -m unittest discover -s tests -v)
```

## API와 소유권 범위

`Supervisor(root).start(Plan(command_id, items=(Item(...),)))`는 handle을 반환하고
`await handle.task`로 최종화를 기다린다. `cancel(run_id)`는 반복 가능하며 즉시
cancelling 이벤트와 capability revoke를 수행한다. `events_after(run_id, seq)`는
실행 화면용 복사본이다. `history.list()`는 검증된 최종 결과만 반환한다.

경쟁 START는 큐로 겹쳐 실행하지 않고 busy/not_run으로 최종화한다. 동일 command/plan은
같은 handle, payload가 다르면 conflict다. 캐시는 동일 프로세스 범위다.
같은 `root/lease.sqlite`를 공유하는 manager/process에서 활성 소유자는 최대 1개다.
다른 root는 별도 격리된 **합성 실험**이며 실제 동일 기기의 전역 잠금이나 복구 방법이
아니다. 새 root로 실제 기기 차단을 우회할 수 있다는 의미가 아니다.

취소/timeout 후 종료와 cleanup이 모두 확인되어야 free가 된다. 실패/미확인은
recovery_required로 남고 재시작해도 차단한다. 자동 recovery/재개와 차단 해제 명령은
없다. 테스트는 정상 정리 후 새 generation과 이전 token 거부를 검증한다.

P3 동기 작업은 소유한 thread에서 실행하고 실제 완료를 추적한다. asyncio 취소로
thread가 끝났다고 간주하지 않는다. thread나 cleanup task가 남으면 차단을 유지한다.
무한 filesystem stall, 강제 process kill, malicious provider의 우회 방지는 미검증이다.

## 산출물과 결과 계약

- workspace: `lease.sqlite`, 최종 이력만 담는 `history.sqlite`.
- run: `run.json`(불변 plan/hash, Skill 원문/hash, provider snapshot), `events.jsonl`,
  `p2.sqlite`, item별 P3 bundle, 검증 후 원자 저장하는 `final.json`.
- 실행 상태는 completed/failed/timed_out/cancelled/not_run과 별도다. 보안 판정은
  pass=양호, fail=취약, inconclusive=판단 불가능이며 사유가 필수다.
- 이벤트의 verdict는 null이다. 결과 로그에는 terminal+finalized만 게시하며,
  저장 실패는 finalizing_failed로 남고 성공 이력에 넣지 않는다.
- P2 자체 run_id=null/session_id를 바꾸지 않고 P4 correlation envelope로 연결한다.
  P2 packet은 CHK-07의 인과/판정 증거가 아니다. P3 route_refs/packet_refs는 빈 목록이다.
- P3 증적은 bundle+attempt로 구분한다. 다른 run/item 혼입, 빠진 선택 항목, 잘못된
  판정/사유/범위, 증적 훼손, 출력 경로 탈출을 거부한다. hash는 진실성 서명이 아니다.

실데이터, 고객/사용자 기기 정보, 실제 packet·계정·인증정보를 추가하지 않는다.
최종 제품의 RUN/AI 수용기준 전체를 통과한 구현이 아니라 제한된 최소 결합 PoC다.


P2의 후속 TLS/WS 확장 이후에도 이 adapter는 기본 HTTP 경로를 사용합니다. P4 requirements는
P2의 고정 WS codec 의존성도 연결하지만, P4 자체의 HTTPS/WSS 시나리오를 검증했다는 뜻은
아닙니다. 확장 검증은 [P2 보고서](../p2-proxy-relay/docs/VALIDATION.md)를 참조합니다.


## Windows device-free execution follow-up

The original Linux/cloud scope above is now additionally checked on Windows 11,
Python 3.12.10. This does not integrate P1 or real Android collection into P4.
See [Windows validation](docs/WINDOWS-VALIDATION.md) for the exact tested scope.
Use a dedicated venv and the same requirements, then from this directory:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m integration demo --scenario normal --output NEW_PRIVATE_DIR
.venv\Scripts\python.exe -m integration history --output NEW_PRIVATE_DIR
.venv\Scripts\python.exe -m integration validate --run RUN_PATH_FROM_DEMO_JSON
```

Providers remain fake-a/fake-b; no model API key, ADB, or device security change is required.

Provider implementation and retry/logging limits are reviewed in the [provider boundary audit](docs/PROVIDER-BOUNDARY-AUDIT.md). Both fake names share one implementation; real model compatibility remains unverified.

A separate [Ollama loopback HTTP preparation adapter](docs/OLLAMA-LOCAL-PREPARATION.md) is tested against a local mock server. It is not admitted to Supervisor and does not claim real model execution or remote cancellation.
