# Mobile Finsec P1 — independent synthetic PoC

Android 합성 로그인 → 메뉴 → 모의 이체 → 확인 앱과 **PC UI에서 받은 입력만** 기록하고 Appium으로 재생하는 독립 프로그램입니다. 실제 금융 서버/계정/거래, proxy, AI, 보안 판정을 포함하지 않습니다. 실제 단말의 손터치 자동 녹화가 아닙니다.

- 먼저 [한 장 실행 명세](docs/EXECUTION-SPEC.md)
- 설치·10단계 기록·3회 실기기 재생 절차: [Windows 안내](docs/WINDOWS.md)
- 실행한 검증과 미검증 경계: [검증 보고서](docs/VALIDATION.md)
- JSON 계약·구현 한계: [계약](docs/CONTRACT.md)
- 공식 도구 출처: [의존성](docs/DEPENDENCIES.md)

```text
android/     네트워크 권한 없는 native Java 테스트 앱
pc/          표준 라이브러리 Python/Tk UI, strict DSL, Appium HTTP 어댑터, journal/lease
tests/      단위 및 fake HTTP 통합 테스트 (실기기 대체 아님)
artifacts/   로컬 빌드 산출물 (Git 제외)
```

```sh
python -m unittest discover -s tests -v
python -m pc.ui --help
```

설계 근거는 이 저장소의 `docs/spec` 및 분리형 PoC 계획입니다. P1만 구현된 독립 실험이며 proxy/AI/보안 판정 및 GPUI 통합은 아직 포함하지 않습니다. 소스에는 도구 설치 캐시, node_modules, 사용자 데이터, 개인 signing key를 넣지 않습니다. APK는 Windows 안내에 따라 직접 빌드할 수 있습니다.
