# P2 실행 명세 v1 — 구현 전 기준선

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
