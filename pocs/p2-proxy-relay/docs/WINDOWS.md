# Windows 합성 실행 가이드

이 문서는 **Windows에서 이후 사용자가 실행할 절차**입니다. Windows 실행·실기기 인수시험의 통과를 뜻하지 않습니다. 실제 수행한 cloud 검증은 [VALIDATION.md](VALIDATION.md)에 구분해서 기록합니다.

Python 3.11 이상만 필요하며 추가 패키지는 없습니다. 이 절차는 같은 PC의 `127.0.0.1` 합성 통신만 사용합니다. 기기 연결, Appium, 관리자 권한, CA 설치, 프록시/방화벽 설정 변경은 필요하지 않습니다. `fixture.py`를 대상으로만 실행합니다.

## 1. 폴더와 Python 확인

저장소를 받은 뒤 PowerShell 터미널 세 개에서 모두 저장소의 `pocs\p2-proxy-relay` 폴더로 이동합니다. 저장소 루트에서라면:

```powershell
cd pocs\p2-proxy-relay
py -3 --version
```

3.11 이상인지 확인합니다. `py` 대신 사용 중인 Python 명령이 `python`이면 아래 `py -3`을 `python`으로 바꿉니다.

## 2. 터미널 A — 합성 upstream

```powershell
py -3 fixture.py upstream --port 8790
```

`fixture=synthetic-only`, `port=8790` 출력 후 대기합니다. 포트가 사용 중이면 다른 프로세스를 종료하지 말고 비어 있는 포트로 바꾸되, 다음 단계의 `--upstream-port`도 같은 값으로 맞춥니다.

## 3. 터미널 B — relay와 RECORD

```powershell
py -3 relay.py serve --db runtime/capture.sqlite3 --upstream-port 8790 --port 8780
```

첫 출력에서 `process_state=running`, `relay_state=off`를 확인합니다. 아래 JSON은 PowerShell 명령이 아니라 **실행 중인 relay의 표준입력에 넣는 한 줄 명령**입니다. 한 줄씩 붙여 넣고 Enter를 누릅니다.

```json
{"schema_version":1,"command_id":"win-demo1-on","command":"ON"}
```

`ok=true`, `relay_state=on`을 확인한 뒤 기록을 시작합니다.

```json
{"schema_version":1,"command_id":"win-demo1-record","command":"RECORD","device_id":"synthetic-device","app_id":"synthetic.qa"}
```

응답의 `recording_id`를 보관합니다. 위 device/app 값은 합성 식별 라벨입니다. 실제 기기나 앱을 선택하거나 해당 앱의 트래픽을 수집했다는 뜻이 아닙니다.

## 4. 터미널 C — 요청 20건과 STOP 전 확인

```powershell
py -3 fixture.py client --port 8780 --count 20
```

`delivered: 20`과 `ids: [0, ..., 19]`를 확인합니다. 이는 client가 20개 기대 응답을 받았다는 뜻이며 저장 성공은 다음 단계에서 따로 확인합니다.

터미널 B에 STATUS를 입력할 수 있습니다.

```json
{"schema_version":1,"command_id":"win-demo1-status","command":"STATUS"}
```

프로세스 전체 counters와 `active_recording.counters`는 범위가 다릅니다. 기록 구간의 `observed`, `captured`, 저장 queue 깊이 및 오류 counters를 확인합니다. `captured`는 귀속 수이며 영속 저장 건수의 보증이 아닙니다.

## 5. 터미널 B — STOP, 터미널 C — 저장 조회

터미널 B:

```json
{"schema_version":1,"command_id":"win-demo1-stop","command":"STOP"}
```

정상 fixture의 기대값은 `status=completed`, `network_coverage=complete_for_supported_scope`이며 손실·절단·오류 counters는 0입니다. 이 coverage는 제한된 지원 프로토콜 범위에만 해당합니다. 실패하거나 partial이면 성공으로 간주하지 않고 JSON 오류와 counters를 확인합니다.

터미널 C에서 기록을 조회합니다.

```powershell
py -3 relay.py query --db runtime/capture.sqlite3 --kind recordings
```

출력 ID를 아래 변수 값에 넣습니다. 꺾쇠가 있는 예시 문자열 전체를 바꿉니다.

```powershell
$recordingId = '<recording_id>'
py -3 relay.py query --db runtime/capture.sqlite3 --kind packets --recording-id $recordingId --limit 100 --offset 0
```

해당 recording의 서로 다른 `packet_id` 20개, sequence 1~20, 각 `response`, `incomplete=false`를 확인합니다. 원하는 packet ID로 원문 및 hash를 조회합니다.

```powershell
$packetId = '<packet_id>'
py -3 relay.py query --db runtime/capture.sqlite3 --kind detail --packet-id $packetId
```

상세의 `request/response.raw_base64`는 저장 원문이며 `sha256`는 전체 메시지 hash, `stored_sha256`는 실제 저장 부분의 hash입니다. `truncated=true`이면 저장 내용은 원문의 앞부분만 포함합니다. fixture의 짧은 메시지는 기본 64 KiB 저장 한도보다 작습니다.

## 6. STOP과 OFF 차이 확인

STOP 뒤 터미널 C에서 다시 client를 실행하면 relay가 ON인 동안 응답은 전달되지만, 방금 종료한 recording에 신규 요청은 추가되지 않아야 합니다.

```powershell
py -3 fixture.py client --port 8780 --count 1
py -3 relay.py query --db runtime/capture.sqlite3 --kind packets --recording-id $recordingId --limit 100
```

터미널 B에서 OFF를 입력합니다.

```json
{"schema_version":1,"command_id":"win-demo1-off","command":"OFF"}
```

OFF는 신규 연결을 닫고 진행 중 연결을 기본 5초까지 기다린 뒤 정리합니다. 이후 client 요청은 연결 실패가 예상됩니다. STOP은 신규 기록 귀속을 닫고 이미 식별된 요청의 응답만 기본 2초까지 기다립니다. 두 timeout과 역할은 다릅니다. 기록 중 OFF/ON을 시험하면 recording은 유지되지만 gap/partial이 남아야 합니다.

## 7. 정상 종료와 재시작 조회

터미널 B에 아래 일반 텍스트 한 줄을 입력합니다.

```text
QUIT
```

PowerShell 프롬프트로 돌아오면 터미널 C에서 같은 조회를 다시 수행합니다. relay 프로세스가 없어도 저장 목록·상세가 남아 있어야 합니다.

```powershell
py -3 relay.py query --db runtime/capture.sqlite3 --kind recordings
py -3 relay.py query --db runtime/capture.sqlite3 --kind detail --packet-id $packetId
```

터미널 B에서 동일한 `serve` 명령으로 다시 실행하면 새 `session_id`와 `relay_state=off`가 나옵니다. 새로운 작업에는 `win-demo2-on`, `win-demo2-record`처럼 새 command ID를 사용합니다. 같은 ID/payload를 재사용하면 이전 프로세스가 저장한 성공 응답을 돌려줄 수 있으며 실제 ON을 다시 수행하지 않습니다. 현재 상태는 STATUS로 확인합니다.

같은 DB를 두 relay가 동시에 열면 잠금 오류가 예상됩니다. `.lock` 파일이 남아 있다는 사실만으로 프로세스가 실행 중이라는 뜻은 아닙니다. 프로세스가 종료되면 OS 잠금은 해제됩니다. DB·WAL 등 저장 파일을 임의로 제거하여 실행 중인 잠금을 우회하지 않습니다.

터미널 A의 합성 upstream은 Ctrl+C로 종료합니다. runtime 파일은 `.gitignore`에 포함되며 Git에 추가하지 않습니다.

## 자동 시험 및 남은 확인

모든 수동 프로세스를 종료한 뒤 다음 명령으로 독립 자동 시험을 실행할 수 있습니다. 테스트는 임시 DB와 합성 loopback 서버를 사용합니다.

```powershell
py -3 -m unittest discover -s tests -v
```

자동 시험은 20건 전달·기록, RECORD/STOP/OFF 경계, 반복 명령, 오류·손실 및 재시작 조회 등을 확인합니다. 실제 시험 항목과 최종 결과는 [검증 기록](VALIDATION.md)을 기준으로 합니다. Windows에서는 출력된 통과/실패를 직접 확인해야 하며 cloud 결과로 대체하지 않습니다.

Android/iOS/웹 앱 라우팅, 선택 앱 귀속, TLS/인증서, HTTP/2·QUIC 및 실제 기기에서의 연결 정리는 이번 프로그램이 구현·검증한 범위가 아닙니다. 향후 각각 별도 명세와 승인을 갖춘 검증이 필요합니다. 현재 안내만으로 실제 앱의 시스템 프록시나 CA 설정을 변경하지 않습니다.
