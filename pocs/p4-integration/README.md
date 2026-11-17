# P4 최소 통합 PoC — synthetic / fake only

현재 단계: 구현 전 실행 명세. [계약과 합격 조건](docs/EXECUTION-SPEC.md)을 먼저 커밋한다.

변경은 이 폴더에만 둔다. 실제 P2 loopback relay와 P3 synthetic CHK-07 평가기를
얇은 adapter로 연결하고 Python supervisor/fake main·item provider를 검증할 계획이다.

**P1, GPUI/gpui-kit, 실제 모델, 실기기 통합은 미검증**이다. P1의 별도 Android CLI
3회 성공은 GUI 기록 검증이나 P4 성공을 뜻하지 않는다. P2 38개/P3 58개 기존 테스트도
제한된 synthetic 검증이다. 사용자 PC·GUI·실기기를 사용하지 않는다.
