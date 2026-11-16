# v1 계약과 구현 경계

`pc/protocol.py`가 실행에 사용하는 권위 있는 엄격 validator입니다. `tap`, `swipe`, `text`, `back`, `wait`만 허용합니다. script/shell/launch URI/임의 execute endpoint는 route에서 제공할 수 없습니다. unknown field, unknown version, 중복 action ID/JSON key, 1 MiB 초과 route, 100단계 초과, 비유한 timeout, 임의 패키지/resource ID/비공개 text를 거부합니다.

route: schema_version, recording_id, status(completed만 재생), device_id, package_id, target(version_code/version_name/apk_sha256), initial, secure, network_coverage(none), actions[]. 각 step은 action_id와 action을 갖습니다. action에는 type, timeout(1~15초), post{id,text?}, 유형별 locator/point/end/geometry/text가 있습니다. point/end는 [0,1) 정규화 좌표입니다. 예제는 `examples/route.schema-example.json`; 이것은 실제 기록/실기기 성공 증거가 아니라 validator 통과용 합성 데이터입니다.

initial은 initial_state=`reset:0::`뿐 아니라 빈 username/password, 선택 패키지 foreground를 확인합니다. 같은 device/설치 APK SHA256/secure 설정을 요구합니다. 다른 장치에 locator route를 이식하는 기능은 구현하지 않았습니다. signer digest/root 탐지/전체 DeviceSnapshot/secret-reference는 미구현입니다. 지원 범위를 합성 fixture와 공개 literal로 좁혔습니다.

`events.jsonl`은 UTC timestamp, monotonic elapsed, sequence, session_id/event_id/action_id와 관찰 파일 경로를 가진 append-only 로그입니다. intent fsync → dispatch marker fsync → 실제 호출 → postcondition 확인 → result fsync 순서입니다. 파일 교체는 같은 디렉터리의 임시 파일+os.replace입니다. OS/저장장치 수준 전원 장애 내구성까지 검증하지는 않았습니다.

완료 route는 재작성하지 않습니다. 재생은 다른 UUID 디렉터리로 결과를 만듭니다. 입력 후 result 쓰기 실패는 완료 step에 추가하지 않으며 자동 재전송하지 않습니다. route가 없더라도 journal은 partial 증거입니다. route 복구/편집 승격 UI는 없습니다.

postcondition은 고유 resource ID 존재/선택적 exact text입니다. 이것은 제한된 관찰 predicate이지 금융 의미·성공 판정이 아닙니다. text는 clear + value의 두 Appium 요청이며 clear만 성공한 경우도 incomplete가 될 수 있습니다. 자동 재시도는 없습니다. wait는 입력을 하지 않습니다. tap가 전송되어도 postcondition이 실패하면 성공이 아닙니다.

관찰 파일은 before/after XML 및 PNG입니다. image API 성공은 `available_uninterpreted`, hierarchy 성공은 `available`, 입력은 실제 dispatch 및 checkpoint 결과로 별도 저장합니다. 이미지 내용/검은 화면 원인은 자동 판독하지 않습니다. PNG 실패만으로 locator 기반 입력까지 불가능하다고 단정하지 않습니다. 필수 hierarchy/checkpoint가 없으면 진행하지 않습니다.

UI에는 한 작업만 제출할 수 있고 worker는 단일 큐를 직렬 실행합니다. 활성 기록/재생 중 다른 시작과 수동 입력을 엔진에서 검사합니다. STOP은 수용 경계를 닫고 현재 작업은 취소로 관찰 부족 처리할 수 있습니다. 재생의 남은 step은 not_run입니다. transport는 요청당 20초, Appium read/launch/ADB는 15초, postcondition polling은 1~15초입니다. step timeout은 관찰 polling 예산이며 전체 step wall time 상한은 여러 순차 transport/evidence 호출 때문에 그보다 길 수 있습니다.

OS file lock은 이 프로그램을 사용하는 프로세스 간 장치 중복을 차단하며 .active marker는 crash 후 자동 재시작을 막습니다. 외부 adb/다른 Appium 도구 및 단말의 물리 손터치까지 통제하지는 않습니다. 연결 동안 lease를 유지하므로 다른 PoC가 협조하지 않는 경우 전역 통제를 보장하지 않습니다. uncertain 결과 또는 cleanup 미확인은 quarantine marker로 보존합니다. 취소는 이미 전송된 입력을 되돌리지 않습니다.

비교적 얇은 W3C HTTP client를 직접 사용하므로 Appium Python Client 패키지 의존성은 없습니다. 이 코드의 가짜 서버 테스트는 직렬화/엔드포인트 동작 계약을 확인하지만 실제 Android driver의 제스처/좌표/IME 동작을 증명하지 않습니다.
