# Controlled synthetic fixtures

이 폴더의 JSON은 실제 기기·앱·계정·거래 관측이 아니다. device ID, package,
build hash, 서비스, checkpoint 및 timestamp는 공개 테스트용 합성 값이다.
fixture에 기대 verdict를 넣지 않으며 도구가 관측에서 판정을 계산한다.

|입력|통제된 관측|기대 판정|
|---|---|---|
|pass.json|순정 baseline 서비스 허용 + 변조 상태 증명 + 같은 보호 서비스의 OS 변조 원인 차단|pass|
|fail.json|순정 baseline 서비스 허용 + 변조 상태 증명 + 같은 보호 서비스 이용 허용|fail|
|inconclusive.json|순정 baseline은 유효하나 test 상태 unknown, 증명 없음, launch-only, oracle 없음|inconclusive|

`fixture_attestation`은 합성 상태 선언이며 실기기 root/변조 증명이 아니다.
`cost_ms`는 실제 지연 측정이 아닌 논리 시뮬레이션 비용이다. faults는 동일 입력에서
재현 가능한 중단·정리 시나리오를 주입한다. 실제 개인·기기 식별자나 증거를 이 폴더에
추가하지 않는다. 실행 결과 경로는 매번 새 디렉터리를 사용한다.
