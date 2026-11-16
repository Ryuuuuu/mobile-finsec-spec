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

## 독립 PoC 구현

- [P1: Android 합성 테스트 앱 + PC 입력 기록/Appium 재생](pocs/p1-record-replay/README.md)
- 클라우드 자동 테스트 27/27 통과 및 APK 빌드 완료. Windows 실기기 인수시험은 별도 검증 대상이며 통과를 주장하지 않습니다.
- [P2: 독립 HTTP 릴레이 + RECORD/STOP 영속 기록·조회](pocs/p2-proxy-relay/README.md)
- P2 클라우드 합성 검증 38/38 통과 및 별도 CLI 20건 전달·저장 확인. 제한된 HTTP/1.1만 지원하며 Windows·실기기 routing·TLS는 미검증/미구현입니다.
- PoC 간 통합, AI 연동과 최종 GPUI 앱은 아직 구현 완료 범위가 아닙니다.
