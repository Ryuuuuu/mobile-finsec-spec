# 기능 도출 2차 역검토

검토 대상: 기능 도출 F-01~F-43, 상세 설계 01~09, 승인 UI01~06 실제 이미지, 사용자 제공 18개 평가항목 및 수정 요구.

## 추적 대조

|기능|주 설계|보완 경계|
|---|---|---|
|F01~05 프로젝트/서비스/탭/설정|01|06 실행중 전환·취소, 07 backend, 08 이력|
|F06~11 기기/앱/미러링/설치|02|03 입력 경로, 05 eligibility, 06 lease|
|F12~18 RECORD/STOP/동선/coverage|03|04 수집 경계, 05 checkpoint 조건|
|F19~24 proxy/packet/query/replay|04|03 record boundary, 06 lifecycle, 07 gateway|
|F25~29 카탈로그/선택/Skill/수동|05,09|03 route semantics, 07 Skill/context, 08 수동 증적|
|F30~36 START/순차/로그/취소/복구|06|01 서비스, 02 기기, 05 preflight, 08 최종화|
|F37~38 backend/전송/audit|07|06 watchdog, 05 capability|
|F39~43 판정/이력/증적/저장|08|01 저장소, 05 scope aggregation, 06 terminal, 09 check rules|

## 2차에서 상세화되어야 했던 지점

새 독립 기능의 추가가 아니라 기존 F-ID 내부 계약의 누락을 보완했다.

1. F29/F39/F42: 수동 증적 등록/검토는 점검 탭, 제출·검토 출처/시각·scope 보존, awaiting_manual_evidence와 timeout/취소. 결과 탭은 최종 조회만.
2. F39: 확인된 취약 scope는 다른 scope 미완료보다 우선. 미선택 제외, 선택 미실행은 실행 상태 not_run+판단불가로 보존.
3. F40/F43: terminal과 finalized를 구별. finalization 실패는 복구 상태이고 정상 최종 이력에 게시하지 않음.
4. F42/F43: 사후 증적 손상은 원판정 덮어쓰기 대신 integrity 경고. run membership/path traversal/symlink/외부 resource 차단.
5. F43: disk-full은 오류 기록 자체도 못 남길 수 있음. 정상 완료 금지와 재시작 reconciliation을 명세.
6. F25: 사용자 18개 모두 CHK01~18에 매핑, 공식 적용범위 provisional. 각 항목 3판정의 최소 규칙과 미확정 fixture를 분리.
7. PoC P4의 fake runtime/backend/GPUI는 기존 P4 통합의 하위 단계로 유지. P0 baseline은 버전 변경 가능.

## 독립 기능 추가 여부

**현재 합의된 Android QA MVP와 승인 화면에 필요한 새 독립 기능은 더 이상 도출되지 않는다.**

- 보이는 각 동작은 F-ID 또는 명시적 장식/제외로 연결된다.
- 미연결→기록준비→기록→동선선택→점검→최종결과의 happy path뿐 아니라 재시도·중복요청·끊김·취소·종료·재시작·빈화면·저장 실패가 연결돼 있다.
- 18개 항목의 누락은 없다. HTS 전용·모바일 확장·수동 보완은 사유와 함께 남겨 기능이 사라지지 않았다.
- TLS/trust 설정, route checkpoint 입력, 수동 증적 검토는 기존 F20/F17/F29의 필수 상세이며 새 도메인을 만들어 기능을 팽창시키지 않았다.
- export/delete/report/scheduler/팀 협업/다중기기/별도 packet 공격 UI는 이번 요구에서 추가하지 않았다.

## 남은 계약 정합성 확인

05와 06에서 run 생성 시점이 달랐음: 05는 lease 내 재검증 후 run 생성, 06은 START run ID 이후 preflight 실패도 이력. 05와 06을 구조 validation → created run ID → lease/preflight → immutable plan 확정 순서로 통일했다. 형식 오류는 run 없이 거부하고, run 발급 후 lease busy 또는 preflight 실패는 not_run으로 최종화한다. 이는 F30 상세 정합성 수정이지 새 기능이 아니다.

기술 구현 검증 미결은 도출 누락과 별개다. GPUI Kit/호스트 빌드, Appium 입력/locator, 실제 proxy 프로토콜/TLS, CLI gateway 격리, 공식 원본 ID·플랫폼, 고객 QA fixture는 PoC 또는 원본 대조 게이트로 남는다. 기능 설계 수렴을 그 검증 완료로 보고해서는 안 된다.
