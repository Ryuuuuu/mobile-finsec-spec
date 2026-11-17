# 04. 프록시 릴레이와 네트워크 수집

상태: 상세 설계 채택안. 구현 완료/프로토콜 지원 검증을 뜻하지 않는다.

## 기능과 분류

네트워크 기반 기능으로, 상단 Proxy ON/OFF, 기록 탭의 패킷 목록/요청·응답 상세, 점검 시 조회·재전송 도구를 제공한다. E/S/U/N은 평가항목의 구현 우선순위이며 이 기반 기능의 개발 순서를 제한하지 않는다.

- PXY-01: 앱 시작 시 relay 프로세스 기동과 상태 조회.
- PXY-02: 실제 relay ON/OFF 및 활성 연결 정리.
- PXY-03: RECORD/STOP 경계의 지속 가능한 패킷 수집.
- PXY-04: 선택 기기·앱 attribution, protocol 및 capture coverage 표시.
- PXY-05: packet 목록·상세·요청/응답 연계 조회.
- PXY-06: 항목 에이전트의 조회·제한된 replay/변조 호출.

## 구조와 책임

Python relay 프로세스가 연결 전달, 규칙 적용, 기록 저장을 담당한다. UI나 AI의 응답을 기다리는 전달 경로를 금지한다. 기존 Hawkeye의 Electron 결합 경로는 Python으로 옮기고 고정 device ID/IP를 설정으로 대체한다. 과거 프로젝트가 TCP 기반이라는 사실을 일반 HTTP CONNECT proxy 지원으로 바꾸어 해석하지 않는다.

API 서비스는 상태/명령/검색 계약을 제공한다. relay의 metadata/event는 영속 저장하고 payload는 blob store에 저장한다. UI에는 페이지 단위 목록과 선택 payload만 전달한다. UI 미리보기 절단과 원본 저장 절단을 구분한다.

서버 프로세스 상태와 전달 상태는 별개다. 앱 시작 시 API와 relay supervisor를 기동한다. 최초 설정의 relay ON을 시도하되 실패하면 error를 표시한다. 사용자 OFF는 명시적으로 보존한다. ON은 listener 준비를 뜻하며 실제 기기 traffic 경유나 복호화 가능을 뜻하지 않는다.

## 상태와 명령

`starting → off → enabling → on → draining → off`, 각 단계에서 `error` 가능.

ON은 포트 확보·설정 검증·listener 준비 후 성공한다. OFF는 신규 연결 수락을 닫고 기존 연결을 bounded drain 후 종료한다. OFF 연결 drain은 `relay_off_drain_ms` 설정값이며 초기 기본 5,000ms, 검증 후 조정한다. 강제 종료 연결은 incomplete로 기록한다. 재시도는 동일 command ID와 동일 payload hash일 때 기존 결과를 반환한다. 같은 ID에 다른 payload는 conflict로 거부한다. lifecycle 변경은 단일 직렬 상태 전이 큐가 소유한다. enabling 중 OFF는 enable 취소 후 정리로, draining 중 ON은 drain/복원 완료 후 새 enable로 처리한다. 이전 generation의 늦은 완료 이벤트는 현재 상태를 덮지 못한다.

기록 중 OFF를 허용하며 capture gap을 남긴다. 점검 실행 중 OFF 요청은 네트워크 사용 작업을 조용히 끊지 않는다. 활성 run 중지는 명시적 명령으로 먼저 처리하고, cleanup 후 OFF로 전환한다. 기록·점검 외 idle 상태는 바로 OFF 가능하다.

OFF 및 오류 종료 시 이 relay가 적용한 routing/hook/임시 proxy 설정만 변경 journal을 따라 복원한다. 기존 사용자 설정을 snapshot하고 자원 소유권을 확인한다. 복원 실패 또는 실제 상태 미확인이면 `recovery_required`로 표시하고 다음 enable/device 검사에 대한 preflight를 차단한다. 새 연결 전환을 덮어쓰며 복구했다고 간주하지 않는다.

TLS upstream 인증서 검증은 기본 활성이다. 검증 실패를 자동 우회하지 않는다. QA 자체 CA가 필요한 경우 명시적 trust 설정을 사용하고 검증모드·CA fingerprint·설정 버전을 snapshot한다. relay CA/key는 프로젝트 로컬 비밀 저장소에서 관리하며 생성/적용/회전/만료/제거를 추적한다. 실제 key는 Git·AI context에 포함하지 않는다. 기기 CA 설치/제거는 명시적 설정 작업이며 원래 trust 상태와 소유 여부를 기록한다. 임의 기존 인증서 제거를 금지한다.

## 기록 경계와 완전성

API는 recording ID를 만들고 recorder/relay를 prepare한다. 양쪽 준비 확인 전 사용자 입력 수락을 시작하지 않는다. 공통 시작 marker와 host monotonic time을 저장한 후 recording을 활성화한다. 분산 원자적 시작을 보장한다고 주장하지 않는다. 부분 준비 실패 시 취소·정리하고, 어떤 구성요소가 준비/실행되었는지 기록한다.

Proxy OFF에서 시작하면 UI-only 기록임을 표시하고 network coverage를 `none`으로 둔다. RECORD 전에 존재한 연결도 구간 내 메시지는 수집할 수 있지만 앞선 handshake/context 부재를 기록한다.

STOP은 신규 수집 귀속 경계를 닫는 session seal이다. relay OFF가 아니다. STOP 이전에 시작한 식별 가능한 transaction의 응답은 별도 `record_stop_response_drain_ms`(초기 기본 2,000ms) 동안 동일 transaction에 연결하고 `received_after_stop=true`로 표시한다. drain 만료는 incomplete transaction으로 종료한다. 식별 불가능한 TCP bytes를 임의 request-response 쌍으로 만들지 않는다.

capture 상태: `complete_for_supported_scope / partial / none / unknown`. 이는 전체 앱 트래픽 완전 수집 보장이 아니다. 지원 scope, 시작/종료 marker, gap 구간, dropped/truncated 건수, decoder 실패, attribution 근거를 함께 저장한다. 저장 실패나 overflow를 조용히 누락시키지 않는다. bounded queue가 넘치면 전달 경로는 유지하되 수집 손실을 명시하고 해당 구간을 이용한 양호 판정을 차단한다.

## 데이터 계약

Packet에는 packet/connection/recording ID, transport/protocol, direction, host timestamp+sequence, endpoint, payload reference+hash+size, parser version, truncation/incomplete 여부를 둔다. 논리 메시지와 TCP chunk는 별도 타입이다.

Attribution에는 `device_id`, `app_id`, `confidence`, `method`, `limitations`를 둔다. endpoint나 시각 일치만으로 선택 앱의 트래픽이라고 단정하지 않는다. UI action과 packet은 시각상 연관 후보일 뿐 인과관계가 아니다.

IDOR/replay 입력은 승인된 QA endpoint, 테스트 사용자 A/B의 로컬 secret reference, 리소스 소유 관계, 치환 필드, 정상/거부 기대조건, 사전·사후 상태, 복원 절차다. HTTP status만으로 소유주 검증을 확정하지 않는다. AI가 임의 대상을 추가하거나 모든 packet을 재전송하지 못하도록 Tool Gateway가 scope를 검증한다.

## 실패 처리

포트 충돌은 실제 listener 소유 여부를 확인한 오류로 표시하고 다른 프로세스를 종료하지 않는다. routing 미설정, TLS 해독 불가, unsupported protocol, upstream 실패, 저장 실패를 서로 다른 오류로 제공한다. UI 연결 끊김은 relay 중지 원인이 아니다. 프로세스 종료 후 활성 connection 상태는 interrupted로 보존하고 자동 replay하지 않는다.

## 인수 기준

1. UI/AI 종료 중에도 지원 fixture 20건의 relay 전달이 동작한다.
2. RECORD 전/STOP 후의 신규 transaction은 기록에 섞이지 않는다. 경계에 걸친 응답은 명시 정책대로 귀속된다.
3. 기록 중 OFF/ON은 gap을 만들며 정상 수집 구간으로 표시되지 않는다.
4. storage failure/queue overflow fixture가 capture partial을 발생시키고 로그·UI·AI context에 동일하게 반영된다.
5. 다른 앱/기기와 섞인 fixture는 attribution 미확정으로 표시된다.
6. 같은 command ID 반복 ON/OFF는 중복 listener를 만들지 않는다.
7. 재시작 후 이전 packet 상세와 hash를 조회할 수 있다.
8. 미지원 protocol 또는 해독 불가 상태는 빈 패킷=안전으로 판정되지 않는다.
9. OFF/오류 후 자체 routing/hook 복원이 검증되며 실패는 recovery_required가 된다.
10. 동일 command ID의 상이한 payload는 conflict, ON/OFF 경쟁은 정의된 직렬 상태로 수렴한다.
11. upstream 인증서 오류가 자동 우회되지 않고 실제 TLS trust snapshot이 run 증적에 남는다.

## 검증 게이트

Hawkeye headless relay 분리, 선택 기기에 대한 routing 적용, TLS/certificate lifecycle, HTTP·HTTP/2·QUIC 등 실제 지원 목록, reconnect/drain 성능을 독립 PoC로 검증한다. 확인 전 지원을 선언하지 않는다. 실제 키·payload·계정은 Git에 저장하지 않는다.


## P2 HTTPS/WS 독립 검증 범위 (2026-11-17)

P2 확장 실행 명세는 [v2 계약](../../pocs/p2-proxy-relay/docs/EXECUTION-SPEC.md)에 고정한다.
고정 localhost TLS 종단에서 HTTPS 및 실제 WS/WSS frame을 수집하고 upstream 인증서를 검증한다.
이는 일반 CONNECT tunnel, 동적 MITM CA, 실제 앱 routing 또는 GUI용 WebSocket 채널과 다르다.
WS는 방향별 frame/연결 lifecycle을 별도 kind로 기록하며 STOP 후 임의 server frame을 HTTP
응답 drain에 포함하지 않는다. 최종 지원/시험 완료 범위는 구현 후 검증 보고서로 확인한다.
