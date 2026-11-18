# P2 — 독립 HTTP(S)·WS(S) 릴레이 기록 PoC

고정 localhost upstream으로 합성 HTTP(S) 요청과 opt-in WS(S) 프레임을 실제 전달하고, RECORD~STOP 구간의 논리 요청/응답·프레임·연결 이벤트를 SQLite에 저장·조회합니다. P1, Appium, 실제 기기, 최종 GPUI 화면, AI 및 점검 실행과 독립입니다. 이 PoC는 보안 항목의 양호/취약 판정을 생성하지 않습니다.

- [구현 전 실행 명세](docs/EXECUTION-SPEC.md)
- [Windows 합성 실행 가이드](docs/WINDOWS.md)
- [검증 환경·결과·남은 시험](docs/VALIDATION.md)

## 실행

Python **3.11 이상**이 필요합니다. HTTP/TLS 경로는 표준 라이브러리이며 WS는 고정된 `websockets==16.0` codec을 사용합니다. 전체 테스트는 OpenSSL CLI도 필요합니다. 인증서는 테스트 실행 때 임시 폴더에 생성합니다. 아래 명령은 이 폴더에서 실행합니다. Windows에서는 `python` 대신 `py -3`을 사용할 수 있습니다.

```text
python --version
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

수동으로는 터미널 세 개를 사용합니다. Windows의 복사 가능한 전체 순서는 [실행 가이드](docs/WINDOWS.md)에 있습니다.

1. 합성 upstream: `python fixture.py upstream --port 8790`
2. 릴레이: `python relay.py serve --db runtime/capture.sqlite3 --upstream-port 8790 --port 8780`
3. 합성 client와 저장 조회: 아래 명령 사용.

릴레이 터미널에 JSON을 **한 줄씩** 입력합니다. 최초 상태는 `off`입니다.

```json
{"schema_version":1,"command_id":"demo1-on","command":"ON"}
{"schema_version":1,"command_id":"demo1-record","command":"RECORD","device_id":"synthetic-device","app_id":"synthetic.qa"}
```

다른 터미널에서 요청 20건을 보냅니다.

```text
python fixture.py client --port 8780 --count 20
```

릴레이 터미널에서 STOP을 실행합니다.

```json
{"schema_version":1,"command_id":"demo1-stop","command":"STOP"}
```

`STOP` 결과의 `recording_id`를 복사하여 조회합니다. `<recording_id>`와 `<packet_id>`는 실제 출력 ID로 바꿉니다.

```text
python relay.py query --db runtime/capture.sqlite3 --kind recordings
python relay.py query --db runtime/capture.sqlite3 --kind packets --recording-id "<recording_id>" --limit 20 --offset 0
python relay.py query --db runtime/capture.sqlite3 --kind detail --packet-id "<packet_id>"
```

릴레이 터미널에 JSON 대신 `QUIT` 한 줄을 입력하면 기록 마감·연결 정리·저장 완료 후 종료합니다. 종료 후에도 같은 DB를 조회할 수 있습니다. 다음 시험에서는 `demo2-on`처럼 **새 command ID**를 사용합니다.

## 기본 HTTP 전달 범위

경로는 `합성 client → 127.0.0.1 relay → 고정 127.0.0.1 upstream`입니다. `--upstream-port`로 목적지를 고정하며, 요청의 Host나 URL로 임의 목적지를 선택하지 않습니다. 모든 listener는 IPv4 loopback에만 바인딩합니다.

- HTTP/1.1 origin-form GET/POST만 지원합니다. 요청 예: `GET /synthetic/0 HTTP/1.1`.
- 요청은 Host가 필요하며, body가 있으면 Content-Length로 크기를 지정합니다. Content-Length 없는 요청은 body가 없는 것으로 처리합니다.
- 응답은 최종 HTTP/1.1 응답과 명시적 Content-Length가 필요합니다. body 없는 응답도 `Content-Length: 0`을 사용합니다.
- 연결당 요청/응답 한 쌍만 처리하고 닫습니다. upstream으로 전달할 요청에는 `Connection: close`를 적용합니다. 저장된 요청 원문은 relay가 client에서 받은 바이트입니다.
- TCP 조각이 나뉘어 도착해도 framing을 완료한 뒤 논리 메시지로 취급합니다. 저장 API의 `packet`은 `kind=http_transaction`인 요청/응답 묶음이며 TCP packet/chunk 개수가 아닙니다.
- 중복 header, Transfer-Encoding, Expect, Trailer, 비정상 framing 등은 거부합니다. Upgrade는 `--websocket`을 켠 RFC6455 경로에서만 허용합니다. 일반 HTTP 구현보다 좁은 지원 범위입니다.

**미지원**: 범용 HTTP CONNECT proxy, 동적 CA lifecycle, HTTP/2·3, QUIC/UDP, chunked·close-delimited body, interim response, HTTP keep-alive/pipelining, replay/변조, 실제 앱 라우팅 및 앱별 attribution. 여러 요청을 한 연결에 보내는 fixture로 전체 수집을 기대하면 안 됩니다. 네트워크/보안 설정이나 기기 trust를 변경하지 않습니다.

Hawkeye는 저장소의 [검토 문서](../../docs/05-hawkeye-review.md)에서 구조와 제약을 참고했습니다. 원본 프로젝트에 접근하거나 소스를 복사·재사용하지 않았습니다.

## 상태와 기록 경계

| 관찰 | 의미 |
| --- | --- |
| `process_state=running` | 서비스 프로세스와 명령 처리가 실행 중 |
| `relay_state=on` | listener 준비 완료; 실제 앱 트래픽 경유를 뜻하지 않음 |
| `counters.observed` | 지원 HTTP transaction/WS handshake·frame·lifecycle의 관찰 수; 저장 성공 수와 다름 |
| 저장 목록/상세 | 실제 영속화된 transaction과 payload 확인 |
| `attribution=unverified`, `app_routing_verified=false` | device/app ID는 합성 라벨이며 실제 귀속은 미검증 |

RECORD는 저장 준비가 끝난 뒤 신규 귀속을 엽니다. **요청 전체의 header/body framing 완료 시점**에 recording을 결정합니다. RECORD 전에 수락한 연결도 그 시점이 기록 구간이면 포함되며 `context_before_recording`으로 앞선 context 부재를 표시합니다.

STOP은 명령 잠금과 command ID 확인을 통과한 시점에 신규 요청의 귀속을 닫습니다. 조회용 WAL 연결을 별도로 사용하므로 packet writer 지연을 기다린 뒤 경계를 닫지 않습니다. 앞선 변경 명령의 완료 대기나 표준입력 전달 지연까지 원자적으로 제거하는 계약은 아닙니다. 이미 식별된 요청의 응답만 기본 **2초**(`record_stop_response_drain_ms`) 동안 같은 recording에 연결하며 `received_after_stop=true`로 표시합니다. 만료 시 `incomplete=true`이며, 나중에 도착한 응답으로 마감된 기록을 수정하지 않습니다. STOP 뒤에도 relay 전달은 계속됩니다.

OFF는 listener를 닫고 활성 연결을 기본 **5초**(`relay_off_drain_ms`) 기다린 뒤 남은 연결을 종료합니다. RECORD 자체는 유지되며 OFF/ON 구간은 gap입니다. OFF 상태에서 RECORD를 시작하고 요청 없이 끝낸 기록은 `network_coverage=none`입니다.

명령 변경은 직렬 처리합니다. 저장된 성공 명령은 같은 `command_id`와 같은 payload로 재시도하면 과거 결과를 반환하고, 다른 payload로 재사용하면 `command_conflict`입니다. 재시작 후에도 과거 결과가 반환되므로 **기존 ON 성공 응답을 다시 받았다고 현재 listener가 켜진 것은 아닙니다**. 응답의 `session_id`와 새 STATUS로 확인합니다. STATUS는 매번 현재 상태를 읽는 조회이며 결과를 캐시하지 않습니다.

```json
{"schema_version":1,"command_id":"demo1-status","command":"STATUS"}
{"schema_version":1,"command_id":"demo1-off","command":"OFF"}
```

## 저장과 손실 표시

출력은 `schema_version=1`, `event_id`, UTC `timestamp`, `ok`, `result` 또는 `error`를 가집니다. 명령 적용 후 journal 저장만 실패하면 `ok=false`, `error=command_journal_error`, `applied=true`, `durable_command=false`와 적용된 `result`를 함께 반환합니다. recording/connection/packet ID와 sequence, parser version, monotonic 시각을 보존합니다. `run_id=null`은 별도 점검 run이 없다는 뜻입니다.

SQLite 한 파일에 metadata와 payload BLOB을 저장하며 상세 조회에서 `raw_base64`로 반환합니다. 목록은 payload를 제외하고 페이지 단위로 조회합니다(`limit=1..100`, `offset>=0`). 별도 조회 프로세스는 read-only 연결을 사용합니다. 동시에 같은 DB를 사용하는 두 `serve`는 파일 잠금으로 차단합니다.

기본 한도는 header 16 KiB, 메시지 body 1 MiB, 동시 연결 64개, recording당 귀속 transaction 1,000개, 저장 queue 128개입니다. 저장 원문은 방향별 **전체 HTTP 메시지 앞부분 64 KiB**까지입니다. 설정명 `capture_body_bytes`도 실제로는 header를 포함한 raw 메시지에 적용됩니다. 전체 메시지의 `sha256/size`와 저장한 부분의 `stored_sha256/stored_size`, `truncated`를 구분합니다. 원문이 절단되었으면 전체 payload를 복원할 수 없습니다. 이 한도는 Python `Config`에 있으며 현재 CLI는 한도 변경 옵션을 제공하지 않습니다.

relay 전달 경로는 디스크·조회·AI를 기다리지 않고 bounded queue에 저장 이벤트를 제출합니다. 포화되면 전달을 계속하면서 `dropped`를 증가시킵니다. 이는 누락된 저장 이벤트 또는 귀속 한도 초과 수로, 정확한 누락 transaction 수와 같지 않습니다. `captured`도 귀속 수이므로 실제 저장 건수는 STOP의 `persisted_packets`와 목록으로 확인합니다. 마지막 갱신을 잃은 미완료 row는 `capture_write_lost`로 마감합니다. `storage_errors`, `decoder_errors`, `upstream_errors`, `truncated`, `connection_rejections`를 별도로 표시합니다.

`network_coverage`는 지원 범위 내의 `complete_for_supported_scope / partial / none / unknown`입니다. 앱 전체 트래픽 수집이나 보안상 안전함을 보장하지 않습니다. 저장 실패·손실·절단·decoder 오류·gap은 partial로 표시됩니다. relay가 생성한 400/502는 upstream의 정상 응답으로 기록하지 않습니다.

## 알려진 한계와 다음 검증

- 정상 종료 시 queue를 flush합니다. 비정상 종료 후 다음 `serve`는 미완료 기록을 `interrupted/partial`로 표시하고 항상 OFF로 시작합니다. 아직 queue에만 있던 payload는 복구하지 못합니다.
- 명령의 상태 변경과 결과 저장은 하나의 원자적 transaction이 아닙니다. 그 사이 crash가 발생하면 exactly-once를 보장하지 않습니다. 같은 프로세스에서는 적용 결과와 오류를 메모리에 보관하여 같은 ID 재시도로 중복 실행하지 않습니다. 실패 결과 cache는 최대 128개이며 가득 차면 신규 변경 명령을 `command_recovery_required`로 거부합니다. 오류 후에는 STATUS와 저장 기록을 확인해야 합니다.
- 디스크 오류는 메모리 상태에 표시하지만, 영구 저장 불가 시 오류 자체의 디스크 보존도 보장하지 못합니다. 저장된 진행 중 metadata는 최신 메모리 counters보다 늦을 수 있습니다.
- 단일 요청/연결/queue의 한도와 별도로 DB 전체 용량·보존 기간·자동 삭제 정책은 구현하지 않았습니다. OS/장치 전원 장애 내구성, 장시간 부하, 영구 파일시스템 stall은 미검증입니다.
- Windows 실행과 파일 잠금, Android/iOS/웹 실제 트래픽 경유, 일반 CONNECT/동적 CA·프로토콜 확장은 별도 검증 대상입니다. 이 PoC의 cloud loopback 성공을 실기기 성공으로 해석하지 않습니다.
- runtime DB·sidecar·lock은 Git에서 제외합니다. 실제 사용자/기기 데이터, 계정·토큰·인증서·키·실제 패킷은 이 공개 저장소에 추가하지 않습니다. 예제는 공개 합성 값만 사용합니다.


## HTTPS와 실제 WebSocket/WSS

이번 확장은 Hawkeye가 HTTPS와 WebSocket을 지원했다는 사용자 요구를 반영한 독립 구현입니다.
이번 원본 조사는 환경 초기화 오류로 코드를 읽지 못했으며, Hawkeye 원본 재사용은 없습니다.
GUI 이벤트 전송용 WS가 아닌 실제 localhost client/upstream 사이 트래픽을 수집합니다.

|경로|설정과 수집 의미|
|---|---|
|HTTP|기존 기본 동작, 연결당 제한 HTTP/1.1 transaction 하나|
|HTTPS|명시적 listener cert/key로 TLS 종단, upstream TLS는 검증 활성; 복호화된 HTTP 저장|
|WS|`--websocket`, HTTP Upgrade 및 양방향 RFC6455 frame/lifecycle 수집|
|WSS|WS와 listener/upstream TLS 결합; 복호화된 WS wire frame 저장|
|CONNECT/암호화 tunnel|미지원; 터널 바이트를 평문 수집 성공으로 표시하지 않음|

TLS listener와 upstream은 각각 선택합니다. 한쪽만 TLS인 경우에도 `tls.listener_enabled`와
`tls.upstream_enabled`, negotiated version, `upstream_verified`로 각 leg를 구분합니다.
`transport=TLS`는 한쪽 이상이 TLS임을 뜻하며 양쪽 TLS 보장을 뜻하지 않습니다.
`capture_mode=decrypted`는 TLS record가 아닌 애플리케이션 평문을 수집한다는 뜻입니다.

아래는 **이미 준비한 테스트 전용** 인증서 파일과 localhost upstream을 사용하는 실행 예시입니다.
일반 기기/브라우저 프록시 설정으로 쓰는 명령이 아닙니다. 자동 재현은 전체 unittest에 포함됩니다.

```text
python relay.py serve --db runtime/tls.sqlite3 --port 8780 --upstream-port 8790 --listener-cert runtime/relay-cert.pem --listener-key runtime/relay-key.pem --upstream-tls --upstream-ca runtime/test-ca.pem --upstream-server-name localhost --websocket
```

client는 테스트 relay 인증서를 전용 SSLContext에서 명시적으로 신뢰해야 합니다. upstream은
기본 체인/만료/호스트 이름 검증을 적용하고, `--upstream-ca`를 생략하면 시스템 기본 신뢰를
읽습니다. 검증 실패를 자동 무시하거나 평문으로 재접속하지 않습니다. TLS1.2 이상이며 ALPN은
HTTP/1.1만 제안합니다. `SSLKEYLOGFILE` 환경변수로 키 기록을 켜지 않습니다. TLS 설정 snapshot은
버전·모드·설정 CA/인증서 fingerprint만 포함하며 PEM, 개인 키, 파일 경로는 출력하지 않습니다.

OS trust store, OS proxy, 기기 설정은 바꾸지 않습니다. 동적 MITM CA 생성/설치/회전, pinning
우회, 실제 앱 routing/attribution은 지원하지 않습니다. 테스트 인증서 생성 helper는 테스트용이며
제품 CA lifecycle을 제공하지 않습니다.

## WS 데이터와 기록 경계

- `kind=http_transaction / websocket_handshake / websocket_frame / websocket_open / websocket_close`를
  구분합니다. `captured`/`persisted_packets`는 전체 row 수이며 HTTP 요청 수가 아닙니다.
  종류별 observed counter는 `http_transactions`, `websocket_handshakes`, `websocket_frames`,
  `websocket_events`에 있습니다. 같은 handshake의 request/response 갱신은 row 하나입니다.
- frame 상세의 request 또는 response 슬롯 하나에 **원본 WS wire frame**을 넣습니다. masking key와
  header를 포함한 bytes이며 TLS record나 unmasked payload가 아닙니다. 방향, opcode, FIN,
  message ID/fragment 순서, frame 순번, unmasked payload의 size/hash를 별도 metadata로 저장합니다.
  저장 prefix 한도를 넘으면 wire bytes가 절단되며 전체 원문 복원을 주장하지 않습니다.
- text/binary/continuation/ping/pong/close를 지원합니다. TCP read chunk와 frame, frame과 message를
  구분합니다. split UTF-8은 message 단위로 검증하지만 실제 frame byte 경계는 그대로 보존합니다.
  peer의 ping/pong/close를 전달하며 relay가 가짜 제어 프레임을 추가하지 않습니다.
- WS frame은 완전히 읽고 검증한 순간 현재 recording에 귀속합니다. STOP 뒤 frame/close는 기존
  기록에 추가하지 않습니다. HTTP handshake 응답만 기존 HTTP drain 규칙을 사용합니다.
  STOP은 WS 연결을 종료하지 않으며 같은 연결에서 다음 RECORD를 시작할 수 있습니다.
- `websocket_at_stop`은 열린 연결/부분 frame/fragmented message snapshot입니다. 부분 frame 또는
  미완료 message는 partial입니다. 이전 구간에서 시작한 message의 continuation은
  `message_context_before_recording=true`로 표시하고 partial로 둡니다. 앞선 연결/handshake context는
  `context_before_recording`으로 표시합니다. STOP 이후 늦은 데이터로 snapshot을 갱신하지 않습니다.
- OFF는 listener와 TLS handshake 및 양방향 pump를 소유하고 bounded drain 후 취소·join합니다.
  정상 close handshake와 abrupt EOF, invalid frame, timeout, 강제 OFF 종료를 구분합니다.

WS 기본 frame/message 한도는 각각 1 MiB, frame 조립/쓰기 제한은 `io_timeout` 2초,
방향별 idle timeout은 30초입니다. 저장 queue 128, recording 전체 row 1,000 한도는 동일합니다.
설정 한도는 Python Config에 있고 CLI는 TLS/WS 활성화 옵션만 제공합니다. 느린 소비자의 backpressure는
해당 연결에만 적용됩니다. 장시간/대규모 트래픽 처리 성능은 미검증입니다.

extensions(압축 포함), subprotocol negotiation, HTTP/2 extended CONNECT·HTTP/3·QUIC, 일반 forward
proxy, HTTP keep-alive/chunked는 미지원으로 거부합니다. 제한된 codec adapter는 고정 버전의
`Frame.parse` 메서드에 의존하므로 라이브러리 교체 시 회귀 검증이 필요합니다. P4는 기존 HTTP
기본 인터페이스 회귀만 검증하며 P4의 WSS 통합 지원을 주장하지 않습니다.

## Disposable Android network QA

[App-origin HTTP/HTTPS/WS/WSS design, execution and measured results](docs/ANDROID-APP-VALIDATION.md) uses a separate loopback-only QA app and owned ADB reverse mappings. No global proxy or CA installation is performed. This does not establish arbitrary-app attribution or interception.
