# P2 실행 명세 — v1 기준선 및 v2 TLS/WS 확장

## 가설과 범위

GUI/AI 없이 Python relay가 합성 HTTP 메시지를 실제 전달하면서 RECORD~STOP 범위의 요청/응답을 영속 저장하고 재시작 후 조회할 수 있다. P1·기기·Appium·GPUI·점검 실행과 독립이다. 기록은 점검 판정을 생성하지 않는다.

- Python 3.11+ 표준 라이브러리, loopback client → loopback relay → 고정 loopback QA upstream.
- 지원: HTTP/1.1 origin-form GET/POST, 요청 Content-Length 또는 요청 body 없음(응답은 Content-Length 필수), 연결당 요청/최종 응답 한 쌍. 요청/응답 framing을 검증하며 TCP read chunk를 메시지로 세지 않는다.
- 제외: TLS/CA/복호화, CONNECT, HTTP/2·3, QUIC, chunked/close-delimited body, upgrade, interim response, keep-alive/pipelining, 실제 앱 routing/attribution, replay·변조, AI·UI, 자동 네트워크 설정 변경.
- Hawkeye 문서만 설계 참고한다. 원본 경로 접근이나 코드 복제는 하지 않는다.

## P0 적용과 인터페이스

참조: `docs/04-contracts.md`, `docs/spec/03-record.md`, `docs/spec/04-proxy.md`, `docs/07-poc-plan.md`.

v1 JSON 출력은 schema_version, event_id, timestamp를 가진다. recording_id는 UUID, session_id는 프로세스 UUID, run_id는 null(점검 없음)이다. RECORD는 명시적 합성 device_id/app_id를 요구하되 attribution은 사용자 입력 snapshot이며 실제 앱 귀속 증명이 아니다. packet은 논리 transaction으로 명시하고 connection_id, request/response 방향별 raw bytes/base64·SHA256·크기, sequence, UTC/monotonic 시각, parser version, incomplete/received_after_stop을 제공한다.

`serve`는 표준입력 command ID가 있는 ON/OFF/RECORD/STOP/STATUS/QUIT 명령을 처리하고 JSON을 출력한다. 저장된 recording 목록, packet 목록/상세는 별도 `query` CLI에서 페이지 단위로 조회한다. SQLite의 metadata 및 BLOB을 함께 사용한다(PoC 축소; 별도 blob store는 통합 과제).

변경 명령의 같은 command_id+payload는 기존 결과를 반환하고 다른 payload는 conflict다. STATUS는 캐시하지 않는 조회다. 변경 명령은 단일 asyncio lock에서 직렬화한다. command 결과는 저장 후 응답하며 process crash 직전의 mutation/결과 원자성까지 보장하지 않는다. 재시작은 항상 OFF로 안전하게 시작하고 미완료 기록은 interrupted/partial로 회수한다. 재시작 후 오래된 성공 명령 재시도는 과거 결과임을 session_id로 식별한다.

## 경계와 실패

RECORD는 저장 준비 후 귀속을 연다. 지원 요청의 전체 framing이 완료되어 upstream 전달을 시작하기 직전 transaction을 식별한다. 이전에 수락된 연결도 이 시점에 RECORD가 열려 있으면 포함되며 handshake 이전 context 부재를 표시한다.

STOP은 즉시 신규 귀속을 닫는다. 그때 식별된 transaction의 응답만 `record_stop_response_drain_ms`(기본 2000) 내 연결한다. 늦은 응답은 received_after_stop, 만료는 incomplete다. STOP은 relay를 끄지 않는다. OFF는 listener를 닫아 신규 연결을 막고 기존 연결만 `relay_off_drain_ms`(기본 5000) 후 종료한다. 기록 중 OFF/ON은 gap으로 남는다. OFF 상태에서도 RECORD 가능하며 network_coverage=none이다.

relay hot path는 bounded queue에 nonblocking enqueue한다. disk worker의 지연/오류·queue overflow는 전달을 멈추지 않고 dropped/storage_errors 및 coverage partial로 표시한다. bounded header/body/connection/recording 한도를 둔다. 한도 초과와 미지원 framing은 명시 오류이며 무손실을 주장하지 않는다. 정상 종료는 queue flush, SQLite close, listener/task 정리를 수행한다. 영구 저장 실패 시 상태는 메모리에서 알 수 있지만 해당 오류 자체의 디스크 보존은 보장할 수 없다.

capture coverage는 complete_for_supported_scope/partial/none/unknown이며 실제 앱 전체 수집 성공을 뜻하지 않는다. process running, listener ON, 관찰된 메시지 건수, attribution 미검증을 각각 표시한다. 저장 실패·decoder 실패·손실·중단은 정상 완료 또는 양호로 승격하지 않는다.

## 시험과 통과 기준

클라우드 loopback 합성 fixture만 사용한다. 실제 계정/기기/패킷/키/인증서/토큰/개인 경로는 저장소에 넣지 않는다. runtime DB는 Git ignore 대상이다.

1. 식별자 있는 합성 요청 20건 실제 전달·응답 및 recording 내 20개 고유 transaction 확인, payload hash 일치.
2. RECORD 이전/STOP 이후 제외, STOP 중 신규 요청 제외, 기존 in-flight response drain 성공/만료 구분.
3. OFF/ON, 별도 OFF drain 강제 종료, 포트 회수, 중복 명령 및 payload conflict, 경쟁 명령 직렬화.
4. upstream 거부/timeout/잘못된 framing, unsupported request, 저장 오류, queue overflow 및 capture 한도 가시성.
5. 조회가 없어도 전달 계속, 별도 조회/재시작 후 상세/hash 보존, crash 뒤 미완료 상태 회수.
6. 최종 코드의 자동 테스트, 한국어 Windows 실행법, 검증한 환경·미실행 실기기 시험·한계를 문서화.

## 단계별 기록

- 단계 1: 기존 설계/P0 읽기 완료. 저장소 및 상위 경로에서 적용할 AGENTS.md/관련 .agents SKILL.md 없음. 이 명세를 구현 전에 커밋한다.
- 단계 2: 독립 relay/SQLite/CLI/합성 fixture 구현. 초기 28개 loopback 시험 통과 후 CLI·저장 장애 회귀 검증을 추가한다. 최종 결과는 VALIDATION.md에 기록한다.


## v2 확장 명세 (2026-11-17, 구현 전 확정)

사용자 요구는 Hawkeye가 지원하던 HTTPS 및 실제 앱 트래픽 WebSocket/WSS 수집이다.
이번 Hawkeye 로컬 조사 시도는 실행 환경 초기화 오류로 파일을 읽지 못했다. 원본 TLS/WS
코드를 검토·실행·재사용하지 않는다. 기존 검토 문서와 사용자 요구를 바탕으로 독립 구현한다.
아래 범위는 v1의 TLS/upgrade 제외를 대체하며, 기본 HTTP 및 P4 JSON v1 계약은 유지한다.

### 전달과 trust

- 고정 `127.0.0.1` client → relay → upstream 구조를 유지한다. TLS listener와 upstream TLS는
  각각 opt-in이며 TLS listener에는 명시적 테스트 인증서/키 파일을 제공한다. TLS1.2 이상,
  HTTP/1.1 ALPN 범위다. TLS는 relay에서 종단되어 평문 HTTP/WS를 수집한다.
- upstream TLS는 체인/만료/호스트 이름 검증을 활성화한다. 시스템 기본 신뢰 또는 명시적인
  테스트 CA 파일을 사용한다. 검증 실패를 우회하거나 평문으로 fallback하지 않는다.
- 상태와 기록에 TLS 각 leg, 검증 모드, CA/서버 인증서 fingerprint와 설정 버전을 snapshot한다.
  키·원문 인증서·개인 경로는 출력하거나 Git에 저장하지 않는다.
- 일반 CONNECT/임의 목적지 proxy, 암호화 바이트 터널, 동적 MITM CA 발급, OS/기기 trust 설치,
  pinning 우회, routing/hook 및 OS proxy 변경은 지원하지 않는다. HTTPS/WSS 복호화 검증은
  테스트 client가 테스트 relay 인증서를 명시적으로 신뢰하는 localhost 환경에 한정한다.
- TLS handshake도 relay가 소유하는 task 안에서 수행하여 OFF의 제한 시간·취소·정리 대상에 둔다.

### 실제 WebSocket frame 계약

- opt-in WS는 HTTP/1.1 GET Upgrade handshake와 RFC6455 text/binary/continuation/ping/pong/close를
  양방향 처리한다. WSS는 같은 WS 경로에 TLS를 결합한다. GUI 이벤트 채널 구현이 아니다.
- WebSocket codec은 `websockets==16.0`의 Frame.parse/Close 및 handshake 검증 도구를 사용한다.
  이 버전의 codec adapter에 의존하며 자체 전체 프로토콜을 구현하지 않는다. 작은 adapter가
  fragment 순서·누적 크기·UTF-8을 검증한다. 원본 frame wire bytes를 전달하고 frame 경계,
  방향, opcode, FIN, connection별 frame 순번과 message 연계를 보존한다.
- HTTP transaction, WS handshake, WS frame, WS lifecycle은 서로 다른 kind다. WS frame은
  request/response 쌍으로 추정하지 않는다. 목록은 payload를 제외하고 상세는 raw base64와
  hash/size를 제공한다. wire frame과 unmasked payload 의미를 명확하게 표시한다.
- opened/closed/error/off 종료와 기록 시작 전 연결 context를 표시한다. ping/pong/close는
  실제 peer가 보낸 프레임으로 전달·기록하며 GUI/AI 응답을 기다리지 않는다.
- extension(압축 포함)/subprotocol negotiation, HTTP/2 extended CONNECT, HTTP/3/QUIC,
  일반 HTTP keep-alive/chunked/pipelining 등 v1의 나머지 제외는 지원하지 않는다.
- header/frame/message/connection/저장 queue/recording row 수는 bounded다. 한도·decoder·TLS·
  upstream·저장 실패를 구분하며 수집 손실은 partial이다. packet 수는 HTTP 요청 수와 같지 않다.

### RECORD/STOP 및 자원 소유권

- HTTP는 기존 완전히 식별된 요청의 response drain 계약을 유지한다.
- WS는 완전히 파싱·검증된 frame 단위로 현재 recording에 귀속한다. STOP은 신규 WS frame와
  lifecycle 기록을 즉시 봉인한다. 이후 server frame을 이전 client frame의 응답으로 추측하여
  drain하지 않는다. 부분 frame/열린 fragmented message·연결 상태를 STOP snapshot에 남긴다.
- STOP 뒤 연결과 실제 전달은 계속된다. 기존 연결에서 새 RECORD를 열 수 있으며 이전 context
  부재를 표시한다. 종료된 recording은 이후 frame/close/error로 변경하지 않는다.
- OFF는 두 방향 pump, TLS handshake, stream을 소유하고 bounded drain 뒤 취소/join한다.
  DB writer·listener·task 정리 및 재시작 조회에 대한 기존 P4 관측값을 보존한다.

### 구현 후 synthetic 인수 시험

1. 신뢰된 테스트 TLS 양방향 HTTPS 전달/평문 저장/hash, upstream 잘못된 CA·호스트 이름 거부,
   평문 fallback 없음, 테스트 client의 relay 신뢰 실패 및 handshake 중 OFF 정리.
2. WS와 WSS의 실제 handshake/양방향 frame 전달, text/binary, 분할 TCP·합쳐진 read·fragment,
   ping/pong/close, frame 경계·direction·연결 lifecycle·hash 및 재시작 조회.
3. RECORD 전/STOP 후 frame 제외, 기존 연결에서 RECORD 재시작, STOP 중 부분 frame,
   열린 fragmented message, 늦은 close/error가 봉인된 기록을 바꾸지 않음.
4. 잘못된 handshake/frame/masking/UTF-8, 크기 제한, abrupt EOF/timeout/OFF, queue loss 및 절단
   가시성. 종료 후 모든 소유 task·포트·DB lock 회수.
5. P2 기존 38개 및 P4 기존 126개 회귀, repo 요구 검증과 비밀정보 점검. 지원/미지원,
   실제 수행 결과와 미검증 Windows/실기기/부하/CA lifecycle을 구분하여 문서화.

테스트 인증서는 실행 때 임시 폴더에서 생성하고 테스트 SSLContext에만 적용한다. 실제 사용자
계정·식별자·트래픽·키·기기 또는 보안 설정을 사용하거나 변경하지 않는다.

기준선: `270c8bbb8680107ea805b6268471c3bc1f32250b`, P2 38/38 통과, P4 지정 디렉터리 126/126 통과.
P4를 repo 루트에서 처음 실행한 경우 import 경로 오류 2개가 있었으며 README 지정 cwd에서 해결했다.
추가 AGENTS.md/.agents, lint 설정, CI workflow는 기준선에서 발견하지 못했다.

공식 참고: [Python SSL](https://docs.python.org/3.12/library/ssl.html),
[asyncio streams](https://docs.python.org/3.12/library/asyncio-stream.html),
[websockets Sans-I/O](https://websockets.readthedocs.io/en/16.0/reference/sansio/server.html).

## Additive v1 recording scope (cooperative clients)

RECORD optionally accepts `recording_id` (1-128 ASCII letters/digits/underscore/dot/colon/hyphen). When omitted, the relay keeps generating an ID. A supplied ID must not already exist in the database, including terminal records after restart; otherwise `recording_id_exists` prevents overwriting prior evidence. The existing command ID/digest journal still returns the original result for an identical retry, and rejects payload changes. These are identity and idempotency rules, not authentication.

STOP optionally accepts `expected_recording_id` with the same syntax. Under the existing command lock, a different active record produces `recording_scope_mismatch` without changing that active record (the delayed-start fence added below still applies to the requested ID). A matching active record follows the existing seal/drain/store path. With no active record it is a no-op (`status=idle`, `scope_matched=false`) and does not claim a completed capture. An identical old STOP command replay returns its stored historical result without stopping a later record. A new command ID with an old expected recording ID is refused while another record is active.

Compatibility: old RECORD and unscoped STOP payloads remain valid and existing schema/database versions remain 1 (optional command fields, no table migration). Unscoped STOP deliberately retains its old global behavior, including relay-owned shutdown. This is not protection from an untrusted client that omits the scope or knows another record ID. Enforcing exclusive ownership would require capability/authentication and migration away from unscoped mutation. The local API is not made safe for arbitrary independent clients by this change.

Updated P1 generates/persists the intended ID before dispatch and includes it on normal/abort/replay STOP. A lost start acknowledgement can therefore trigger one scoped compensation attempt. If the record was replaced meanwhile, cleanup reports uncertainty and leaves the replacement untouched. No automatic unscoped fallback is permitted. Older P2 peers reject the added fields, so upgraded P1 and P2 must be deployed together; capability negotiation/downgrade is not implemented. The initial scoped-stop implementation did not settle a RECORD arriving after an idle STOP; the delayed-start fence below now addresses that ordering for the same durable store and preassigned ID. General remote reconciliation still requires stable request tracking.

Local tests cover same-command retry, distinct-command ID reuse after restart, wrong-owner STOP, historical STOP retry against a newer record, idle no-op, malformed scope and legacy unscoped behavior. Actual P1 Network/Relay tests inject a lost applied RECORD reply both before and after another client replaces the recording. No device, real app or model is involved.
Validation on Windows: P1 combined tests 22/22 PASS (2.076s), P2 relay tests 37/37 PASS (10.226s), actual CLI WSS protocol 1/1 PASS (5.111s), P4 structural tests 132/132 PASS zero skips (23.500s).

## Delayed-start cancellation fence

A deterministic local test reproduced STOP arriving before a delayed RECORD: the old idle STOP succeeded, but the late RECORD started anyway, including after a relay restart. The new scoped STOP first durably cancels its expected ID under the existing command lock. A small additive `cancelled_recordings(id, created_at)` table is initialized when opening the live store. A later RECORD with that ID returns `recording_cancelled` without creating a recording. Existing recording rows already forbid ID reuse, so they do not consume cancellation entries. This closes both arrival orders for cooperating callers using the same preassigned ID against the same updated durable relay store.

The idle scoped STOP now reports `start_fenced=true`; it still does not claim packet capture completion. If another recording is active, STOP leaves it active and reports `recording_scope_mismatch` plus `start_fenced=true` for the requested ID. Thus mismatch now has a deliberate cancellation-side effect on the requested future ID, not on the active recording. Same-command retries retain their original journal result and never create a second recording. Storage failures remain unsuccessful/uncertain. Up to 4096 unknown IDs can be fenced; a new unknown ID beyond that limit fails with `cancellation_registry_full`, without evicting old fences. Existing-record STOP and repeated cancellation of a known ID remain possible at the limit. There is no automatic pruning because that could re-enable delayed work.

Compatibility: the table is additive and artifact schema stays v1; P4 selected snapshots intentionally do not copy cancellation/control tables. Old unscoped commands remain available. Older relay binaries do not enforce cancellation fences, so downgrading or replacing the database loses this guarantee. No schema-version negotiation or authenticated ownership is added. The cap/retention/controlled epoch rollover policy needs a product decision; the POC fails closed rather than silently forgetting cancelled IDs. Disk failure, deleting the store, a client inventing a different ID, and untrusted clients are outside the guarantee.

Tests use explicit test barriers to delay arrival; this is controlled transport reordering, not an observed USB/network incident. Actual P1 CombinedRun times out before relay dispatch, issues one scoped compensation STOP, and the released request is rejected; input never becomes enabled and remains incomplete. Relay tests cover persistence across restart, identical retry, cancellation storage failure, registry capacity and STOP for an existing record at capacity. No device, installer or inspection skill is involved.
Delayed-start validation: P2 relay 39/39 PASS (10.703s), P1 combined 22/22 PASS (2.936s), CLI/WSS 1/1 PASS (4.935s), P4 structural 133/133 PASS zero skips (25.798s).
Closed-instance follow-up: after Relay.close, all commands (including STATUS/ON) return relay_closed before storage access under the existing command lock. This prevents command-history lookup from recreating WAL sidecars after storage seal. Reopen with a new Relay instance. Actual P1/P4 handoff tests distinguish partial input from complete packets and interrupted recovery after injected finalization failure; see ../../p4-integration/docs/LIVE-RELAY-HANDOFF.md.

## Recovery failure transaction boundary (offline follow-up)

The existing Store startup recovery was exercised with two records emitted by
the actual loopback relay. In a temporary database only, their saved terminal
states were changed to unfinished states to create a deterministic recovery
fixture. A SQLite trigger rejects the second recovery UPDATE. This is deliberate
SQL failure injection, not a new observed process crash or physical disk failure.

The failed Relay.start leaves no connection or file-lock owner. All recording,
packet (including request/response BLOB), command and cancellation rows match
their pre-attempt values: the earlier recording UPDATE is rolled back with the
later failure. Removing only the test trigger permits a fresh Relay to reopen
the same DB, recover both records as interrupted/partial, and remain off. A
second successful reopen leaves the recovered records unchanged, with exactly
one process_interrupted gap each. Packet/control rows remain unchanged.

No production defect was reproduced, so no recovery behavior was changed. The
existing startup recovery applies only when the caller explicitly opens the same
database. This does not add automatic DB discovery, salvage of corrupt SQLite,
retention/repair policy, resume of capture, clearing of device quarantine, or a
claim about power-loss durability. A recovery failure must still be reported as
failure rather than treating old unfinished rows as completed. Choices about
operator repair and archival remain product decisions.

Validation: test_relay.py 41/41 PASS (10.988s), ResourceWarning-as-error, including
`test_recovery_write_failure_rolls_back_all_rows_and_releases_owner`. Uses synthetic
records and local loopback only; no device, model, inspection skill or installation.
