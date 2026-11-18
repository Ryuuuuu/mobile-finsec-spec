# P2 HTTPS/WS 확장 검증 기록

2026-11-17 UTC. **localhost synthetic 통신만 검증했다.** 실제 사용자 기기·앱·트래픽·계정·키를
사용하지 않았으며 OS trust store/proxy/보안 설정을 변경하지 않았다. 아래 v2 결과와 이어지는
v1 과거 기록을 구분한다. 기계 판독 결과는 [validation-summary.json](validation-summary.json).

## 단계와 코드 기준

1. 최신 원격 기준선 `270c8bbb8680107ea805b6268471c3bc1f32250b` 확인. 적용할 AGENTS.md/
   .agents skill, lint 설정, GitHub workflow는 발견하지 못했다.
2. 구현 전 명세 commit `5dab1c925e002c04466bda46ca9e930fe90c3b57`.
3. 독립 TLS/WS 구현·테스트·한국어 실행 문서 commit `a55a6101d6217e00ccf8e1b90b9f06d901963b32`.
   검증한 tree는 `87dfd3449f0716abba58d2474526474af5eaa91e`다.
4. 본 검증 보고서는 구현 뒤 별도 commit한다. 마지막 SHA는 원격 main 확인 후 완료 보고에 남긴다.

Git CLI의 HTTPS 쓰기 인증이 없어 연결된 GitHub 도구로 동일 tree의 commit과 fast-forward ref
갱신을 수행했다. expected SHA를 확인했고 force=false로 반영했다. 로컬/원격 tree 일치를 확인했다.

Hawkeye가 HTTPS/WebSocket을 지원했다는 사용자 요구를 반영했다. 이번 로컬 조사 시도는 환경
초기화 오류로 파일을 읽지 못했다. 원본 TLS/WS 코드를 검토·실행·재사용했다고 주장하지 않는다.

## 실행 환경 및 결과

Linux x86_64 cloud, Python 3.12.14, SQLite 3.53.1, Python SSL OpenSSL 3.5.8,
인증서 생성 OpenSSL CLI 3.5.7, websockets 16.0, P4 기존 jsonschema 4.26.0.
TLS test helper는 임시 폴더에 합성 CA/localhost leaf 인증서·키를 생성하고 종료 시 제거한다.
인증서·키·runtime DB는 Git에 넣지 않았다. Windows·실기기 결과로 해석하지 않는다.

|suite|test method 수|시간|결과|
|---|---:|---:|---|
|P2 전체|74|7.048s|통과, 실패 0, skip 0|
|P4 회귀|126|14.175s|통과, 실패 0, skip 0|
|합계|200||통과|

P2는 기존 HTTP/CLI 38개 + WS 20개 + TLS/WSS 15개 + 실제 CLI WSS 1개다.
subTest case는 method 수에 더하지 않았다. 시간은 이 cloud 실행값이며 성능 기준이 아니다.

저장소 루트에서 재현:

```bash
python -m pip install -r pocs/p4-integration/requirements.txt
(cd pocs/p2-proxy-relay && python -m unittest discover -s tests -v)
(cd pocs/p4-integration && python -m unittest discover -s tests -v)
```

기준선 검증도 P2 38/38, P4 126/126 통과했다. 첫 P4 실행을 repo 루트에서 수행했을 때
2개 module import 오류가 있었으며 README 지정 P4 cwd에서 정상화했다. 제품 코드 결함으로
취급하지 않았다. 신규 TLS 시험의 초기 CA 개수 assertion 실패는 cloud SSLContext의 추가
신뢰 metadata 차이였다. 설정한 CA 파일 자체를 fingerprint하도록 수정한 뒤 위 최종 시험은 통과했다.

## 확인한 범위

|영역|검증 결과|
|---|---|
|HTTPS|실제 client TLS → relay 종단 → 검증된 upstream TLS 전달; 복호화 HTTP 원문/hash 저장. 한쪽 leg만 TLS인 설정도 명시적으로 구분|
|Trust|알 수 없는 CA, 잘못된 hostname 거부; client의 relay 신뢰 실패; plaintext fallback 없음; 실제 협상 TLS version/peer fingerprint/upstream_verified 기록|
|Handshake 소유권|TLS를 보내지 않는 연결도 relay task가 소유하며 OFF로 종료. 활성 TLS stream/port/DB 자원 회수|
|실제 WS/WSS|HTTP Upgrade와 양방향 text/binary/continuation/ping/pong/close 전달. GUI 이벤트 채널이 아닌 localhost socket traffic|
|Frame 경계|분할 TCP/합쳐진 frame/Upgrade 직후 frame, 원본 masking·opcode·FIN·direction·frame 순번·message ID, wire 및 unmasked payload hash 보존|
|Fragment|분할 UTF-8과 중간 ping, continuation 순서/누적 message 한도. 기록 경계를 건너는 message context 부재를 partial로 표시|
|RECORD/STOP|부분 frame 제외, 열린 message snapshot/gap, 기존 WS/WSS 연결에서 다음 RECORD, STOP 후 송수신 지속. 늦은 frame/close/오류가 마감 recording metadata·counter·packet을 수정하지 않음|
|HTTP drain|TLS에도 기존 식별된 HTTP 응답만 drain; deadline 이후 기록 불변. WS frame을 임의 request-response pair로 만들지 않음|
|실패 경로|잘못된 handshake/확장·subprotocol, masking/opcode/RSV/control/길이/UTF-8/close/크기 거부; abrupt EOF와 OFF 강제 종료 partial|
|손실/저장|WS queue overflow·storage fault·raw prefix 절단 시 전달 지속과 partial 표시, 전체/저장 hash 구분; 재시작 query 동일|
|CLI/P4|독립 websockets client/server + 실제 relay.py subprocess WSS 송수신/STOP/QUIT/재시작 조회; P4 동적 로드/기본 HTTP exact bytes·hash·기록·cleanup 계약 유지|

독립 검토에서 발견한 WSS frame/lifecycle의 협상 metadata 누락, handshake 이후 recording 오류
counter 귀속, 방향별 frame 순번 누락을 수정하고 시험으로 확인했다. `websockets` codec을 고정
버전으로 사용하며 직접 전체 RFC6455 decoder를 작성하지 않았다. 작은 adapter가 bounded read,
fragment/message 상태와 UTF-8, strict 지원 scope를 관리한다.

## 정적·공개 저장소 점검

- `git diff --check`, Python AST parse, `python -m tabnanny` 통과.
- 별도 repository lint config/명령 및 CI workflow 없음. 이를 lint 전체 규칙 또는 CI 성공으로
  과장하지 않는다. 원격 SHA의 연결된 status/workflow 조회 결과는 완료 보고에서 확인한다.
- 변경 파일의 실제 private-key/certificate block, GitHub/AWS/API token 패턴, credential URL 및
  추적 대상의 PEM/key/DB/pcap 등 runtime 파일 점검에서 발견 0. 합성 코드의 PEM parser 문자열은
  실제 인증서 값과 구분했다. 이 패턴 점검이 가능한 모든 비밀 탐지를 보장하는 것은 아니다.
- 테스트 PKI는 임시 생성하며 `SSLKEYLOGFILE`을 통한 key logging이 활성화되지 않음을 확인했다.

## 정확한 한계와 다음 게이트

- **고정 loopback TLS 종단/복호화**다. 일반 CONNECT/임의 목적지 forward proxy나 암호화 tunnel,
  동적 MITM CA 발급·설치·회전·만료/제거 lifecycle, pinning 우회는 구현하지 않았다.
- HTTP는 기존 제한 HTTP/1.1 GET/POST Content-Length, 연결당 transaction 하나다. WS extensions/
  compression/subprotocol, HTTP/2 extended CONNECT·HTTP/3·QUIC/UDP는 미지원이다.
- wire frame 원문은 TLS record가 아니다. raw prefix 한도 초과 시 원본 복원 불가이며 payload는
  별도 hash/size만 제공한다. record row 수는 HTTP 요청 수와 다르다.
- Python 3.11 및 다른 OS/OpenSSL 조합, Windows TLS/WS·파일 잠금·종료, 실제 앱 routing/attribution,
  실제 기기 신뢰/프록시 복원, P4 자체 WSS 시나리오는 미검증이다.
- TLS 만료 검증은 SSLContext에 위임하며 만료/revocation/client-certificate/mTLS 별도 fixture는
  시험하지 않았다. OS 기본 CA trust 변화·제품 CA 관리도 검증하지 않았다.
- WS frame 조립 시간과 방향별 idle timeout은 bounded지만 장시간 slow-trickle/대규모 부하/
  영구 filesystem stall/전원 장애 시험은 수행하지 않았다. 기존 전체 DB quota·보존 정책·
  exactly-once crash 한계도 그대로다.
- complete_for_supported_scope는 명시한 synthetic 지원 범위의 수집 상태다. 전체 앱 트래픽
  수집이나 보안 항목의 양호 판정이 아니다.

---

# v1 HTTP 기준선의 과거 검증 기록

## 최종 코드와 결과

- 검증일: 2026-11-16 UTC.
- 코드 기준: `dddef56344595778f507c011fde653e28ff4f62e` (`feat(p2): add bounded HTTP relay recording and independent synthetic tests`). 이 문서 추가 단계에서는 실행 코드를 바꾸지 않았다.
- 환경: 클라우드 Linux x86_64, Python 3.12.14, SQLite 3.53.1, 표준 라이브러리만 사용.
- 대상: loopback 합성 upstream/client, 임시 SQLite DB. 사용자 PC·실기기·실제 앱·실제 패킷에는 접근하지 않았다.
- 최종 자동 시험: **38개 실행, 38개 통과, 실패 0, skip 0**. 최종 코드 실행 출력 `Ran 38 tests in 3.015s / OK`.

저장소 루트에서 재현:

```text
python -m unittest discover -s pocs/p2-proxy-relay/tests -v
```

PoC 폴더에서는 같은 suite를 다음과 같이 실행한다:

```text
python -m unittest discover -s tests -v
```

Windows에서는 `python` 대신 `py -3`을 사용할 수 있으나 Windows에서의 실행 결과는 아직 없다. [Windows 가이드](WINDOWS.md)는 후속 실행 절차다.

## 검증한 내용

| 시험 | 확인한 결과 |
| --- | --- |
| 합성 20건 동시 전달 | upstream에 20개 고유 경로 도달, client가 기대 응답 20개 수신, 20개 고유 recording transaction 저장. request/response hash·크기 일치 및 페이지 조회 확인 |
| RECORD 전/STOP 후 | 구간 밖 요청은 실제 전달되지만 해당 recording에 신규 귀속되지 않음 |
| STOP 진행 중 | 기존 식별된 응답만 drain 안에서 기록, `received_after_stop=true`; STOP 뒤 신규 요청 제외 |
| STOP timeout | `stop_drain_timeout`/incomplete 보존; 이후 실제 응답은 전달되지만 마감 기록은 바뀌지 않음 |
| 부분 수신·분할 TCP | 요청 body 파싱 전 STOP이면 제외. 여러 TCP read로 나뉜 메시지는 transaction 하나로 기록 |
| OFF/ON | listener 닫힘·재개, 기존 recording 유지, gap/partial 보존. OFF부터 시작해 ON으로 바뀌어도 gap을 지우지 않음 |
| 별도 OFF drain | STOP 예산 700ms와 별도로 OFF 25ms 예산으로 강제 정리, `relay_off_timeout`; Python 3.12 서버 종료 대기로 무한 지연하지 않음 |
| 명령 반복·경쟁 | 동일 ID/payload 기존 결과, 다른 payload conflict, 중복 RECORD busy, ON/OFF/ON 직렬 수렴 |
| 명령 journal 오류 | 상태 적용 후 결과 쓰기 실패를 applied/non-durable로 구분, 같은 프로세스 재시도 중복 없음. 관계없는 오류가 완료 기록을 변경하지 않음 |
| upstream 장애 | 접속 거부·timeout·잘못된 framing·짧은 응답을 incomplete/partial로 표시; 합성 502를 upstream 정상 응답으로 저장하지 않음 |
| 저장 장애 | 결정적 SQLite write 예외 주입. RECORD 준비 실패 시 활성화 안 됨; 기록 중 실패해도 전달 지속, 메모리 counter 표시, 복구 후 partial/interrupted 영속화 |
| queue overflow | 느린 writer와 작은 queue로 손실 재현. 전달 지속, dropped/partial 표시 |
| bounded capture | transaction/동시 연결/header/body 한도, 원문 저장 prefix 절단과 실제 전달 body 구분 |
| protocol 범위 | CONNECT·HTTP/2·chunked·중복 header·absolute-form 등 거부, pipeline의 두 번째 요청은 처리하지 않는 단일 transaction 계약 |
| 재시작 조회 | 프로세스 종료·재시작 뒤 상세/hash 동일, 자동 OFF. 과거 command 결과 replay와 현재 listener 상태 구분 |
| crash 복구 | 자식 프로세스를 종료한 뒤 미완료 기록을 interrupted/partial로 회수; 자동 replay 없음 |
| DB·포트 소유권 | 두 번째 DB writer 차단, 포트 충돌 때 기존 listener를 종료하지 않음, 자기 upstream 포트 설정 거부 |
| 실제 CLI 프로세스 | 표준입력 JSON ON/RECORD/STOP, client 20건, query 목록/상세, 정상 종료·재시작 조회 |
| UI/조회 독립성 | 조회 없이 20건 전달. stdout 소비 중단으로 출력이 막혀도 별도 client 20건 전달·저장 유지 |
| 명령 입력 한도 | 과대 physical line의 JSON suffix가 다음 명령으로 실행되지 않음, 중복 JSON key 거부 |

추가로 가이드의 `fixture.py upstream`, `relay.py serve`, `fixture.py client`, `relay.py query`를 각각 별도 프로세스로 실행한 smoke도 통과했다. 결과는 `delivered=20`, `persisted_unique_transactions=20`, `coverage=complete_for_supported_scope`, `query_after_exit=PASS`였다. 동적 포트와 임시 DB를 사용했고 종료 후 테스트 자원을 정리했다. Windows PowerShell 자체를 실행한 시험은 아니다.

## 단계와 발견된 문제

1. `ab82103`: 실행 명세를 구현 전에 commit/push. P0·프록시·기록·Hawkeye 문서를 읽고 지원/미지원과 경계를 고정했다.
2. 구현·초기 시험: STOP 결과의 중복 session_id 인자, Python 3.12에서 `Server.wait_closed()`를 drain 전에 호출해 종료가 지연되는 문제를 발견하고 수정했다. OFF에서 시작한 기록의 coverage 승격, 명령 journal 실패 재시도, 과대 입력 줄 처리, SQLite 조회 연결 정리도 보완했다.
3. 초기 28개 시험 통과 후 CLI·저장 오류·자원 한도 회귀 시험을 추가했다. 최종 38개 통과 및 실제 fixture 프로세스 smoke를 확인했다.
4. `dddef56`: 구현·테스트·한국어 실행 가이드를 commit/push. 동시 진행된 P1 원격 commit을 먼저 fast-forward하여 보존했다. P1 코드는 P2 작업으로 수정하지 않았다.
5. 이 검증 문서를 별도 commit으로 추가한다. 실제 최종 원격 SHA는 작업 완료 보고에서 확인한다.

초기 실패는 수정 전 코드의 발견 사항이다. 위 최종 결과는 수정 후 코드에 대한 실제 실행 결과다. 실제 디스크 공간 고갈·전원 차단을 일으킨 시험은 아니며 저장 오류는 fault injection으로 재현했다.

## 재사용과 남은 검증

Hawkeye는 [검토 문서](../../../docs/05-hawkeye-review.md)의 설계상 제약만 참고했다. 원본 프로젝트 접근·실제 코드 재사용은 **없다**. P1 코드 역시 복제하거나 연동하지 않았다. 별도 PyPI 의존성도 없다.

미구현·미실행:

- Windows 실행/파일 잠금/종료 인수시험, Python 3.11 및 그 외 OS·버전 조합. 최소 버전 선언이 모든 조합의 실행 확인을 뜻하지 않는다.
- Android/iOS/웹 실제 앱 라우팅, 선택 기기·앱 attribution, 다른 앱 트래픽 혼합, 기기 연결 해제·복구. 현재 ID는 합성 라벨이며 unverified다.
- TLS 복호화·upstream 인증서 검증·trust snapshot·CA lifecycle, HTTP/2·3·QUIC, 일반 CONNECT proxy, routing/hook 복원. 네트워크/보안 설정을 바꾸지 않으므로 해당 복구 동작을 검증했다고 주장하지 않는다.
- GPUI 기록/점검 탭, P1 입력 recorder와 공통 start marker 조정, main AI·agent·replay/변조·보안 판정. 기록 탭과 점검 탭의 제품 경계를 변경하지 않았다.
- 장시간 부하, DB 전체 quota/보존 정책, 영구 filesystem stall, 전원 장애 내구성, 상태 변경과 command journal 사이 crash의 exactly-once 보장.

실기기 확장은 위 항목별 독립 명세와 검증이 선행되어야 한다. 현재 `complete_for_supported_scope`는 제한된 합성 HTTP 범위의 기록 완전성이지 전체 앱 수집 성공이나 보안상 양호 판정이 아니다.

## Windows / device follow-up

See [2026-11-18 measured Windows and Android transport results](WINDOWS-DEVICE-VALIDATION.md). This supplements the historical cloud-only results above: Windows HTTP/WS checks and a device-shell USB HTTP path were exercised; app attribution and device TLS remain unverified.
