# 도구·패키지 출처와 고정

2026-11-16 UTC에 공식 소스 접근 및 설치를 확인했습니다. 최신 버전 추천이 아니라 이 PoC에서 선택한 재현용 버전입니다.

| 구성 | 고정 / 확인 | 공식 출처 |
|---|---|---|
| Appium | 3.1.0 + npm lockfile | https://registry.npmjs.org/appium/3.1.0 |
| UiAutomator2 driver | 6.0.0 + npm lockfile | https://registry.npmjs.org/appium-uiautomator2-driver/6.0.0 |
| Python | 클라우드 3.12.14, 외부 Python 패키지 없음 | https://www.python.org/downloads/ |
| Gradle | 8.9, distribution SHA256=d725d707bfabd4dfdc958c624003b3c80accc03f7037b5122c4b1d0ef15cecab | https://services.gradle.org/distributions/gradle-8.9-bin.zip.sha256 |
| Android Gradle Plugin | 8.7.3 | https://developer.android.com/build/releases/agp-8-7-0-release-notes |
| Android SDK | platform android-35 / build-tools 35.0.0 | https://developer.android.com/tools/sdkmanager |
| command-line tools | 11076708; SHA256=2d2d50857e4eb553af5a6dc3ad507a17adf43d115264b1afc116f95c92e5e258 | https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip |
| JDK | Debian OpenJDK 21.0.12.1+1-1~deb13u1, 원본 배포 묶음의 artifacts/jdk-source.json에 source/hash 기록 | https://deb.debian.org/debian/dists/trixie/main/binary-amd64/Packages.xz |

AGP 8.7 공식 문서는 Gradle 8.9, JDK17, API35를 안내합니다. Appium driver 공식 호환성 표는 UiAutomator2 6.0.0에 Android API26 이상, Appium3을 요구합니다. npm registry에서도 두 패키지의 node/npm engines 및 driver peer dependency를 확인했습니다. 전이 npm 패키지는 `package-lock.json` integrity로 고정합니다. SDK 플랫폼/Platform-Tools 배포 revision과 JDK 패치 버전은 검증 환경 보고에 남기며 모든 OS 도구까지 완전한 비트 단위 재현 환경이라고 주장하지 않습니다.

추가 확인한 공식 문서:
- https://appium.github.io/appium-uiautomator2-driver/latest/getting-started/
- https://appium.github.io/appium-uiautomator2-driver/latest/reference/capabilities/
- https://appium.io/docs/en/3.1/guides/managing-exts/ (npm 프로젝트 의존성 방식)
- https://developer.android.com/security/fraud-prevention/activities (FLAG_SECURE)
- https://developer.android.com/reference/android/view/WindowManager.LayoutParams

Appium 서버는 `--address 127.0.0.1`로 시작하고 insecure 기능을 켜지 않습니다. HTTP 어댑터는 Appium endpoint를 고정하며 route-provided execute/script를 받지 않습니다. 자동 테스트는 fake server이므로 이 endpoint들의 실제 기기 동작은 별도 검증 대상입니다.
