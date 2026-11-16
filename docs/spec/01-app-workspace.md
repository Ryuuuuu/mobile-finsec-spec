# 앱 및 프로젝트 스펙

기능 도출 카탈로그 대응: **F-01~F-05**, 영속 저장 기반은 F-43. 도메인 ID(APP/WS)는 분류용 별칭이며 최종 추적의 기준 ID는 F-ID다.

## 범위와 기능

승인 UI의 공통 상단 프로젝트 선택, API/프록시 상태 표시, 기록/점검/결과 로그 3탭의 공통 기반이다. 운영 환경, 계정/팀 협업, 원격 동기화, 스케줄링은 범위 밖이다. 프로젝트는 QA 앱을 점검하는 로컬 작업 공간이며 프로젝트 삭제/자동 증적 삭제는 초기 범위에 넣지 않는다.

- APP-001~003: 서비스 시작·건강 상태·실패·재연결·종료.
- WS-001~002: 생성·열기·선택·최근 프로젝트와 설정/기록/실행 격리.
- 상단 메뉴는 기존 기능으로 연결되는 명령만 둔다. 동작 없는 메뉴/증적 일괄 선택 checkbox 등 장식은 구현 요구로 해석하지 않는다.

## 구조와 데이터

Rust GPUI Kit shell은 렌더링과 사용자 명령 제출만 담당한다. Python API 실행 관리자가 프로젝트/기록/실행의 권위 있는 상태를 소유한다. 프록시 전달은 별도 Python 프로세스에서 UI나 AI 응답을 기다리지 않는다. Appium 및 모델 backend는 필요 시 생성되는 외부 의존 프로세스이며 '두 서버'는 제품의 API+proxy 구성이지 전체 OS 프로세스 수가 정확히 두 개라는 뜻이 아니다.

설계 선택: 프로젝트별 SQLite 메타데이터 DB와 파일 artifact 저장소. 큰 packet payload/이미지를 DB 행에 반복 복제하지 않고 artifact ID로 참조한다. 파일은 임시 기록→flush→최종 이름으로 교체한 뒤 DB 참조를 확정한다. 중간 실패 시 broken 참조를 성공으로 게시하지 않는다. DB/파일의 원자적 단일 transaction을 가정하지 않는다. 미참조 파일은 자동 삭제하지 않고 복구 점검 대상으로 남긴다.

`Project`: project_id(불변 UUID), display_name, schema_version, created_at, updated_at, root_path, target_profiles, provider_profile_refs, proxy_profile, settings_revision. 이름 변경으로 ID를 바꾸지 않는다. 최근 프로젝트 목록에는 경로와 표시 이름만 저장한다. 고객 데이터/인증정보/패킷을 설계 Git에 저장하지 않는다.

프로젝트 기본 디렉터리:

```text
project.json
metadata.sqlite
recordings/<recording_id>/
runs/<run_id>/
artifacts/<artifact_id>
```

API 제어 채널은 기본 loopback에만 bind한다. 프록시 트래픽 listener는 기기 경로에 필요한 주소를 별도 설정한다. API가 노출되도록 프록시 listener 설정을 재사용하지 않는다. UI 시작 시 생성한 session credential로 제어 API를 인증하며 값은 로그에 남기지 않는다. 로컬 모델/CLI 자격증명은 OS/공식 backend 저장 방식의 참조를 사용하고 project.json에 비밀값을 직접 넣지 않는다.

## 시작과 건강 상태

1. 기존 동일 프로젝트 instance/DB 점유 여부를 확인한다. 다른 실행이 점유한 workspace를 두 번째 writer로 열지 않는다. 프로젝트 DB writer lock은 저장 무결성용이고 device lease와 다르다. 동일 호스트에는 단일 실행 관리자를 두며 전역 device lease를 관리한다. 프로젝트 A/B를 별도 창에서 열어도 동일 기기 소유권은 공유된 실행 관리자에서 배타적으로 부여한다. 프로젝트 DB가 다르다고 같은 기기를 동시에 조작할 수 없다.
2. 설정/schema를 검증하고 API를 기동한다.
3. 릴레이 프로세스를 시작한다. 초기 기본은 요청한 ON이지만 listener bind와 health 확인 전 UI를 ON으로 표시하지 않는다. 최초 프로젝트 기본은 ON이며, 이후 사용자가 명시적으로 선택한 ON/OFF를 프로젝트 설정에 보존하고 재시작 때 복원한다. 오류로 OFF가 된 상태는 사용자 희망 상태를 덮어쓰지 않는다. 초기 기본·사용자 희망 상태·실제 상태를 구별한다.
4. schema/설정 오류, port 충돌, 의존성 누락을 UI에 구체 오류로 표시한다. 모르는 프로세스를 죽여 포트를 확보하지 않는다.
5. 과거 run/recording의 비정상 종료를 검사한다. 잔존 작업 소유권과 종료 여부가 해결되기 전 새로운 기기 작업을 금지한다.

서비스 상태: `stopped → starting → healthy`; 실패 시 `failed`, 종료 요청 시 `stopping → stopped`. 프로세스 생존과 서비스 readiness를 구별한다. API unavailable일 때 마지막 상태를 정상 live처럼 표시하지 않고 stale 표시한다.

UI 재연결은 마지막 event cursor 이후 재수신하되 cursor gap이면 현재 snapshot을 재조회한다. 중복 event_id를 중복 적용하지 않는다. 조회 응답에는 project_id/run_id/revision을 포함해 이전 프로젝트 요청의 늦은 응답이 새 화면을 덮어쓰지 못하게 한다.

## 프로젝트 전환 및 종료

- idle 상태: 전환 가능. 새 프로젝트의 device/target/recording 선택을 로드하고 이전 결과를 새 프로젝트에 섞지 않는다.
- recording/check 실행/cleanup 중: 프로젝트 변경은 적용하지 않고 현재 작업을 먼저 STOP/중지하라는 이유를 보여준다. 작업을 몰래 취소하지 않는다.
- 결과 이력 조회는 기기가 없거나 프록시가 OFF여도 가능하다.
- 앱 닫기 요청 시 active 작업이 있으면 '중지하고 종료 / 닫기 취소' 선택을 제공한다. 중지 선택은 cancel→tool 종료 확인→정리→DB flush→relay 종료→API 종료 순서다.
- 정리 실패 시 종료 성공으로 표현하지 않는다. 강제 종료가 발생해도 다음 시작에서 recovery_required로 드러난다. 종료 후 무조건 자동 재실행하지 않는다.
- 초기 버전은 background tray 실행을 지원하지 않는다. 창 닫기로 검사가 조용히 계속된다고 가정하지 않는다.

## 인수 기준

1. 빈 workspace에서 프로젝트 생성 후 재시작해 동일 ID/이름을 다시 연다.
2. 프로젝트 A/B의 recordings/runs/evidence를 서로 조회할 수 없고 늦은 A 응답이 B 화면을 덮어쓰지 않는다.
3. API health 전 status bar가 정상이라고 표시되지 않는다. proxy bind 실패는 실패 이유와 재시도 경로가 보인다.
4. 실행 중 프로젝트 전환·연속 앱 종료 요청으로 두 작업 또는 두 정리 루틴이 생성되지 않는다.
5. 재연결 시 이벤트 중복/누락을 감지하고 authoritative snapshot과 UI가 일치한다.
6. 저장 실패 시 완료/저장 성공을 표시하지 않는다. 과거 이력은 신규 실행 없이 열 수 있다.
7. 기기 분리/모델 미설정/프록시 OFF여도 결과 로그 조회가 동작한다.
8. API와 proxy가 서로 다른 bind 설정을 사용한다. 외부 IP에서 제어 API에 접근할 수 없는 기본 구성을 시험한다.

## 검증 미결

GPUI Kit 패키지/정확한 버전/Windows build 경로는 최소 창·select·table·가상화 목록·한글 입력 PoC에서 검증 후 pin한다. 해당 라이브러리의 실제 지원을 이미지로 입증했다고 주장하지 않는다. SQLite migration은 신규 DB와 직전 schema upgrade fixture를 먼저 검증하며 downgrade를 지원하지 않는 경우 읽기 전 오류를 낸다. UI/API 이벤트 프로토콜의 구체 라이브러리는 통합 구현 시 선택하되 snapshot/cursor/idempotency 계약은 유지한다.
