# Mobile FinSec Spec

모바일 전자금융 보안 점검 자동화 데스크톱 앱의 설계 저장소입니다.

- 상태: 설계 v0.1. 구현 완료를 뜻하지 않습니다.
- 적용 환경: 승인된 QA 환경만. 운영 환경은 범위 밖입니다.
- 플랫폼: Android(AOS) → iOS → 웹.
- 원칙: 구현 전에 요구사항과 판정 기준, 화면·데이터·실행 계약을 명세합니다.
- 기준일: 2026-11-16

## 문서

1. [제품 요구사항](docs/01-requirements.md)
2. [구조와 오케스트레이션](docs/02-architecture.md)
3. [화면 및 사용자 흐름](docs/03-ui-flow.md)
4. [데이터와 Skill 계약 초안](docs/04-contracts.md)
5. [Hawkeye 재사용 검토](docs/05-hawkeye-review.md)
6. [결정 및 미확정 사항](docs/06-decisions.md)
7. [분리형 PoC 계획](docs/07-poc-plan.md)
8. [승인된 UI 시안: 전체 화면 6장](docs/mockups/README.md)
9. [상세 스펙 인덱스 및 43개 기능 추적](docs/spec/00-index.md)
10. [2차 기능 도출 및 수렴 검토](docs/spec-review/03-feature-convergence.md)
11. [변경 이력](CHANGELOG.md)

사용자 확정 요구사항과 위임받아 채택한 상세 설계 기준선, 실험으로 확인해야 할 검증 게이트를 구분합니다. 상세 동작은 `docs/spec`을 우선 참조합니다. 원본 기준 적용성 및 실제 도구 호환성은 아직 검증되지 않았습니다.

원본 평가기준 엑셀, 평가기준 본문, 고객 앱·패킷·계정·인증서·키·실제 증적은 이 저장소에 포함하지 않습니다. 이 저장소는 자체 작성한 제품 설계와 합성 테스트용 PoC 소스를 관리합니다.

## 구현 PoC 현황

최신 상태는 [POC → 제품 설계 추적성과 시험 게이트](docs/08-poc-traceability.md)를 참조합니다. 43개 기능과 18개 점검 항목의 구현·모의/로컬·실기기·미검증 상태를 구분합니다.

- [P1](pocs/p1-record-replay/README.md): 선택 QA 앱의 PC 기록/재생과 연속 영상. 특정 native/Canvas 동선의 실기기 시험 통과이며 모든 앱 호환은 아닙니다.
- [P2](pocs/p2-proxy-relay/README.md): 협조 QA 앱의 HTTP/HTTPS/WS/WSS 및 제한된 OkHttp 경로 검증. 일반 앱 귀속·가로채기 지원은 아닙니다.
- [P1/P2 통합](pocs/p1-record-replay/docs/COMBINED-RECORDING.md): HTTP 기록과 HTTPS 기록/재생 성공. WSS GUI는 연결 소실로 중단됐고, reverse 소유권 수정 후 실기기 재검증이 남았습니다.
- [P3](pocs/p3-android-os-tamper/README.md): CHK-07 합성 판정 엔진과 별도 read-only Android probe. 실제 보안 판정 미검증입니다.
- [P4](pocs/p4-integration/README.md): fake provider와 로컬 P2/P3 실행·이력·취소/복구 경계. 실모델과 GPUI 제품 통합은 미구현/미검증입니다.

초기 문서의 시점별 검증 기록은 보존합니다. POC 성공은 제품 전체 기능 또는 공식 평가 통과를 뜻하지 않습니다.

- [S1 / CHK-15 첫 정적 POC](pocs/s1-apk-obfuscation/README.md): 실제 SDK의 DEX/smali 추출과 직접 만든 R8 비교 APK를 검증했습니다. 결과는 판단 불가능이며, 합성 판정 시험과 실제 보안 판정을 구분합니다.

- [S2 / CHK-11 모바일 정적 확장](pocs/s2-apk-plaintext/README.md): APK 합성 평문 marker의 위치·해시 탐지. 원래 실행 명령줄 점검은 미실행이며 보안 판정은 판단 불가능입니다.

현재 사용자 지시에 따라 점검 스킬 내용·사용 도구·취약점 판정 구현/시험은 중단하고 [모의 스킬 기반 구조 검증](pocs/p4-integration/docs/STRUCTURE-ONLY-SCOPE.md)만 진행합니다. 점검 스킬은 사용자가 skill-creator로 직접 작성합니다. 기존 항목별 결과는 과거 POC 기록입니다.
