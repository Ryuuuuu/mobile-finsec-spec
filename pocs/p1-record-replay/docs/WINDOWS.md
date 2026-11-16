# Windows 실행 안내

이 안내는 Git 저장소 또는 소스 ZIP으로 받은 독립 P1 PoC에 적용됩니다. 자동으로 사용자 PC나 기기에 연결되지 않습니다. 지금 제공된 자동 테스트 결과는 Linux 클라우드 결과이며 Windows/실기기 결과가 아닙니다. 실제 금융 앱은 지원하지 않고 `dev.finsec.poc`만 허용합니다.

## 준비

- Windows 10/11, Python **3.12.x** (python.org 설치 시 Tcl/Tk 포함), Node **22.12.0 이상 22.x** 또는 **24.x**, npm >=10, JDK 17 또는 21.
- Android Studio SDK Manager에서 Android SDK Platform **35**, Build-Tools **35.0.0**, Android SDK Platform-Tools 설치. 앱 최소 Android 8/API26. Platform-Tools는 SDK Manager 최신 배포를 사용하되 `adb version`을 실기기 보고에 기록합니다.
- `JAVA_HOME`은 JDK, `ANDROID_HOME`은 Android SDK 폴더. `%ANDROID_HOME%\platform-tools`를 PATH에 추가. 다른 장치 작업·Appium 세션을 종료합니다.
- Git clone을 사용한다면 저장소의 `pocs\p1-record-replay`로 이동합니다. 소스 ZIP은 짧은 경로(예: `C:\work\mobile-finsec-poc`)에 압축 해제하고 `package.json`, `pc`, `android`가 있는 폴더로 이동합니다. 이후 명령의 기준 디렉터리를 **PoC 루트**라고 부릅니다. Node 의존성과 빌드된 APK는 Git 소스에 포함하지 않습니다.

PowerShell, PoC 루트에서:

```powershell
py -3.12 -m unittest discover -s tests -v
npm ci --ignore-scripts --no-audit --no-fund
npx --no-install appium --version
npx --no-install appium driver list --installed
npx --no-install appium driver doctor uiautomator2
```

`package-lock.json`은 Appium **3.1.0**, UiAutomator2 **6.0.0** 및 전이 의존성의 정확한 npm 버전/무결성을 고정합니다. 프로젝트 폴더에서 실행해야 npm 방식 드라이버 발견이 작동합니다. 별도 전역 `driver install latest`로 바꾸지 않습니다. npm postinstall은 실행하지 않으며 필요한 UiAutomator2 server APK는 패키지에 포함되어 있습니다. 새 Android 버전 호환성은 실기기에서 확인해야 합니다.

## APK 준비: 두 가지 배포 형태

**A. Git clone / 소스 ZIP만 받은 경우 (기본 경로)**

빌드된 APK가 없으므로 PoC 루트에서 먼저 빌드합니다.

```powershell
Push-Location android
try {
    .\gradlew.bat --no-daemon assembleDebug
    if ($LASTEXITCODE -ne 0) { throw "APK build failed" }
} finally {
    Pop-Location
}
$ApkPath = (Resolve-Path .\android\app\build\outputs\apk\debug\app-debug.apk -ErrorAction Stop).Path
```

**B. 별도로 제공된 사전 빌드 APK를 받은 경우**

실제 받은 `finsec-poc-debug.apk`를 PoC 루트의 `artifacts` 폴더에 복사한 경우에만 아래 경로를 사용합니다. `artifacts`와 APK는 Git에서 제외되어 있으므로 clone만으로 이 파일이 생기지 않습니다. 소스 ZIP에도 APK가 포함되었다고 가정하지 마세요.

```powershell
$ApkPath = (Resolve-Path .\artifacts\finsec-poc-debug.apk -ErrorAction Stop).Path
```

두 경로는 동일 테스트 앱의 서로 다른 배포 방식입니다. 직접 빌드한 APK는 빌드 환경/서명 키에 따라 제공 APK와 해시가 달라질 수 있습니다. APK를 준비한 PowerShell을 유지하고 아래 설치를 진행합니다.

## 설치와 연결 (사용자가 집에서 명시적으로 수행)

1. Android 개발자 옵션/USB debugging을 켜고 본인이 승인한 PC의 RSA 프롬프트를 기기에서 확인합니다. 자동 승인/우회는 하지 않습니다.
2. `adb devices -l`에서 serial을 **직접 선택**합니다. unauthorized/offline이면 먼저 해결하고 진행합니다.
3. 아래 `YOUR_SERIAL`을 실제 serial로 교체합니다. 설치는 선택한 테스트 앱을 변경합니다. 기존 테스트 데이터가 필요하면 먼저 보존하세요. 프로그램은 자동 설치/삭제/clear-data하지 않습니다.

```powershell
adb -s YOUR_SERIAL install "$ApkPath"
npm run appium
```

Appium은 localhost:4723에만 수신합니다. `--relaxed-security`를 추가하지 마세요. Appium은 연결 시 자체 UiAutomator2 도우미를 설치할 수 있습니다. 별도 PowerShell을 같은 폴더에서 엽니다.

```powershell
py -3.12 -m pc.ui --device YOUR_SERIAL --package dev.finsec.poc
```

`Connect / launch`는 지정 패키지만 시작하며, 앱 상태를 자동 reset하지 않습니다. 설치 APK 경로를 ADB로 읽어 SHA256을 비교하므로 이 조회가 불가능한 기기에서는 중단합니다. 서명 동일성까지 증명하는 제품 구현은 아닙니다. 다른 기기에 route를 자동 이식하지 않습니다.

## 첫 10단계 동선 (FLAG_SECURE OFF)

`RESET fixture`를 누르고 `secure:off`, `login`, 빈 username/password를 확인한 후 RECORD를 누릅니다. 각 입력 이후 완료 표시를 기다립니다. PC 화면 자체를 클릭합니다. 기기 손터치는 기록되지 않습니다.

| 단계 | PC 입력 | 기대조건 |
|---|---|---|
|1|Text target=username, value=qa-user → Send|username exact qa-user (자동 설정)|
|2|Text target=password, value=qa-pass → Send|password exact qa-pass (자동 설정)|
|3|스크린샷의 Synthetic login 클릭|screen_state = menu|
|4|Mock transfer 클릭|screen_state = transfer|
|5|Text recipient=DEMO-001|recipient exact DEMO-001|
|6|Text amount=1000|amount exact 1000|
|7|Review synthetic input 클릭|screen_state = review|
|8|Back 버튼|screen_state = transfer|
|9|Review synthetic input 클릭|screen_state = review|
|10|Confirm simulation 클릭|receipt = SIMULATED:1:DEMO-001:1000|

tap/back 전 우측 postcondition ID/텍스트를 표대로 설정해야 합니다. 텍스트 전송은 대상 필드 exact text를 자동 검사합니다. 클릭 위치에서 resource ID를 찾고 실제 dispatch 직전에 고유 일치 여부를 다시 검사합니다. UI는 키보드 raw 이벤트를 수집하지 않습니다. 텍스트 1회 전송을 1 action으로 저장합니다. 외부 키보드/손터치를 사용하면 이 보장이 깨집니다.

STOP은 입력을 닫고 완료 route를 저장합니다. 실행 도중 STOP/Cancel을 누르면 현재 동작이 실행됐을 수도 있으므로 보수적으로 incomplete로 남깁니다. 완료 route는 `outputs/<recording_id>/route.json`입니다. 0단계 기록은 incomplete입니다.

기록이 완료되면 RESET을 **직접** 누르고 Replay JSON으로 같은 route를 선택합니다. 결과를 확인하고 다시 RESET하여 총 3회 실행합니다. 초기 상태/secure mode/device/build가 다르면 입력 전에 차단됩니다. 각 run의 `result.json`, `events.jsonl`, `evidence/`를 보존합니다. 실패 후에는 남은 단계가 `not_run`인지 확인하고 창을 닫아 세션 정리를 마친 후 다시 시작합니다.

## 스와이프 및 좌표 fallback

기본적으로 좌표 action은 비활성입니다. 별도 실험 때만 `--allow-coordinates`로 실행하고 화면이 실제로 보이는지 확인하여 `I can see this frame clearly`를 체크합니다. 확인 중 폴링이 멈추므로 안정된 프레임에서 드래그합니다. tap locator가 없는 경우와 swipe는 exact geometry/rotation 및 실행당 최대 3개 제한이 적용됩니다. 재생 때도 플래그가 필요합니다. 가능한 tap은 항상 resource ID를 사용합니다. 다중 일치는 좌표로 우회하지 않습니다. 화면 크기/방향 불일치, 캡처 불가 시 좌표 입력을 중단합니다.

앱의 일반 화면은 스크롤이 필요 없을 수 있습니다. 스와이프는 `screen_state` 존재/동일값처럼 관찰 범위가 약한 postcondition만으로 성공이 표시될 수 있으므로, 이것이 원하는 스크롤 이동량 검증을 뜻하지는 않습니다. 드래그 시 실제 변화와 UI tree를 별도 비교하세요. secure 검은 화면에는 좌표 fallback을 사용하지 마세요. 픽셀 자체는 자동 판독하지 않습니다.

## FLAG_SECURE 비교

기록 밖에서 Toggle FLAG_SECURE를 사용합니다. reset은 secure 설정을 유지합니다. OFF와 ON 각각 별도 기록을 만듭니다. ON에서 미러링이 막히면 resource ID를 이용한 Text 및 Wait로 최소 입력/계층 가용성을 확인할 수 있습니다. 전체 tap 동선 기록이 불가능하면 그 사실을 incomplete/미실행으로 보고하세요. 이전 OFF route를 ON에서 실행하면 secure mismatch로 차단됩니다.

보고 표에는 (1) 이미지 API/실제 픽셀 가시성 (2) UI hierarchy 조회 및 기대 요소 (3) input dispatch+postcondition 관찰을 각각 적습니다. screenshot 파일 생성 성공은 화면 내용이 보인다는 의미가 아닙니다. 검은 화면 원인을 FLAG_SECURE로 단정하지 않고 앱 설정·Android 버전·Appium 로그를 함께 남깁니다. 우회 기능은 없습니다.

## 중단·복구·파일

- 정상 닫기는 현재 유한 요청을 기다리고 DELETE session 성공 후 lease를 해제합니다. Appium 서버는 사용자가 시작한 것이므로 프로그램이 강제 종료하지 않습니다. 종료 대기에는 요청당 최대 20초가 걸릴 수 있습니다.
- timeout/프로세스 crash에는 `%USERPROFILE%\.mobile-finsec-poc`에 `.active`/`.quarantine`이 남습니다. 이 상태는 자동 해제하지 않습니다. **Appium 서버를 종료하고 진행 중 기기 명령이 없음을 직접 확인한 후에만**, 해당 장치 해시의 marker를 수동 제거하고 서버/프로그램을 재시작하세요. 다른 실행이 살아 있는데 marker를 지우지 않습니다.
- 디스크 full/crash 때 마지막 journal 행이 잘릴 수 있습니다. `finished` 및 완료 route가 없는 journal은 incomplete입니다. 자동으로 완료 route로 복구하지 않습니다.
- 증거에는 앱 화면/UI tree/공개 QA 입력이 들어갑니다. 테스트 앱 외 foreground로 바뀌면 다음 작업을 중단하지만 순간적인 외부 전환의 모든 픽셀 노출을 차단하는 제품은 아닙니다. 이 테스트 동안 다른 앱을 사용하지 마세요.
- 실제 비밀번호/계좌를 입력하지 마세요. public fixture 4개 문자열 외의 text는 거부합니다.

## 다시 빌드할 때의 주의사항

위 APK 준비 A 절차를 **PoC 루트**에서 다시 실행합니다. `Push-Location`/`Pop-Location`으로 빌드 후에도 PoC 루트를 유지합니다.

Gradle **8.9**, Android Gradle Plugin **8.7.3**, SDK **35**, Build-Tools **35.0.0**. PoC 루트 기준 `android\app\build\outputs\apk\debug\app-debug.apk`가 생성됩니다. debug 키는 본인 환경에서 생성됩니다. 배포 ZIP에는 개인 키를 포함하지 않습니다. 새 빌드는 서명/해시가 달라 기존 route와 호환되지 않을 수 있으므로 새 기록을 만듭니다. `targetSdk=28`은 이 격리 fixture의 인셋을 단순화하기 위한 선택이며 최신 Android 제품 보안 기준 준수 주장이 아닙니다.
