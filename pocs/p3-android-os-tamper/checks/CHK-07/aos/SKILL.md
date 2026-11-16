# CHK-07 AOS Skill v1 — synthetic only

이 플랫폼 절차는 common/SKILL.md와 함께 읽는다. 공통 판정 규칙을 완화하지 않는다.
Android 우선 계약을 시험하는 synthetic_fixture 어댑터만 지원한다. 실제 Android
탐지 코드나 기기 제어 어댑터는 없다. ADB, Appium, 실제 기기, shell/subprocess,
네트워크와 실제 금융 앱을 호출하지 않는다.

```json
{"rule_contract":"CHK-07.synthetic.v1","synthetic":true,"schema_version":"1.0"}
```

## 관측 경로

입력 JSON의 observations만 순서대로 읽는다. device ID는 각 phase에 선언된
synthetic baseline/test ID에 대응한다. package는 dev.finsec.synthetic이며 build는
합성 SHA-256이다. 상태 stock/tampered/unknown과 fixture_attestation/missing을
서비스 outcome 및 oracle과 분리 보존한다. 실제 root 탐지 API를 흉내 내지 않는다.
service_checkpoint는 fixture가 선언한 보호 서비스 결과일 뿐 실제 UI나 서버 관측이
아니다. route/packet 참조는 빈 목록이며 P1/P2 산출물을 사용하지 않는다.

## 시간·취소·정리

관측 cost_ms와 manifest의 step/total 예산을 비교해 논리 timeout을 구현한다.
faults로 관측 전/후 cancel, timeout, tool_error와 cleanup completed/failed/unknown을
주입할 수 있다. CLI --cancel은 시작 전 합성 취소다. 기기 프로세스 중단이나 실제
단말 복구를 검증했다고 해석하지 않는다. cleanup은 합성 복원 결과만 남긴다.
모든 이벤트와 증적의 synthetic 출처를 유지하고 공통 Skill의 판정·정리 규칙을 적용한다.

실기기 연결은 P1 기기 사용 종료, 승인된 전용 QA 앱/build, 독립 변조 증명,
정상 baseline/보호 서비스 oracle, 복원 절차와 단일 기기 소유권 관리가 준비된 뒤
별도의 실제 어댑터 구현·검증 범위에서만 고려한다.
