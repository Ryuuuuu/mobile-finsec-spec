# P2 검증 기록

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
