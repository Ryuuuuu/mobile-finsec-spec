# 05. Hawkeye 재사용 검토

기존 로컬 프로젝트의 읽기 전용 검토 결과를 설계에 반영한 기록이다. 원본 코드를 복제하거나 수정하지 않았다. 검토 시점의 실제 checkout 기준이며 향후 변경될 수 있다.

## 1. 재사용 후보

- Python proxy manager와 TCP/TLS relay 구조.
- interception / 변조 / 재전송 개념.
- packet metadata 및 조회 구조.
- AI 도구 연결에 사용된 bridge/MCP 개념.

## 2. 분리해야 할 부분

현재 전달 경로는 Python만으로 완결되지 않고 Electron GUI의 메시지 처리에 의존하는 부분이 있다.

- Python에서 받은 패킷을 WebSocket 이벤트로 GUI에 전달한다.
- GUI 측 scope/Match & Replace 처리 후 relay 요청으로 되돌려준다.
- 실제 writer를 통한 전송이 이 경로와 연결되어 있다.

새 앱에서는 relay 전달, 규칙 적용, 기록 저장을 Python 서비스로 옮겨 UI/AI 정지 때문에 네트워크가 함께 멈추지 않도록 한다. 단순히 Python 폴더만 가져오면 동일하게 작동한다고 가정하지 않는다.

## 3. 확인된 제약과 검증 과제

- Android Frida 기반 연결 전환 중심이며 일반 HTTP CONNECT proxy와 동일한 것으로 보지 않는다.
- 단일 USB 기기 선택 및 고정 IP 등 가정을 선택 device ID/설정으로 바꿔야 한다.
- TCP 위주다. UDP/QUIC와 HTTP/2·HTTP/3 등 지원은 검증 전까지 선언하지 않는다.
- polling, timeout과 취소 처리 보완이 필요하다.
- 고정 인증서/키와 upstream 인증서 검증 설정은 새 프로그램의 인증서 lifecycle로 재설계한다.
- 메모리 packet store의 오래된 데이터 삭제 정책은 증적 유실 방지 요구와 맞춰 바꿔야 한다.
- recording_id/action_id/run_id로 연계되는 영속 데이터 모델이 필요하다.
- 기존 AI bridge는 GUI와 packet store에 결합되어 있어 공통 Tool Gateway로 분리한다.
- 문서에 기술된 에이전트 구조와 실제 존재하는 코드가 다를 수 있으므로 구현 실체를 우선한다.

## 4. 우선 PoC

1. GUI 없이 Python relay만 실행하여 데이터가 정상 전달되는지 확인.
2. RECORD 시작/종료 경계와 packet 영속 저장 검증.
3. 선택 기기에만 연결 전환 적용.
4. UI/AI crash, proxy toggle, 취소 시 연결 정리 검증.
5. 재전송은 요청 범위와 실행 결과가 로그·증적에 남도록 검증.

패킷 전송/변조의 실제 동작은 이 문서 작성 과정에서 실행하지 않았다.

## 2026-11-17 HTTPS/WebSocket 요구 보완

사용자가 Hawkeye의 HTTPS 및 WebSocket 지원을 알려 주어 P2 요구에 반영했다.
이번 로컬 원본 조사 시도는 실행 환경 초기화 오류로 파일을 읽지 못했다. 이번 확장이 원본의
TLS 종단·upstream 검증·실제 WS frame 처리 방식을 확인하거나 코드를 재사용한 결과는 아니다.
GUI 이벤트용 WebSocket과 앱 트래픽 WebSocket을 구분하고 P2에서 독립 synthetic 검증한다.
