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

세션 생성 HTTP 요청은 helper 설치와 instrumentation 시작을 포함하므로 기본 통신 timeout을 **90초**로 분리했습니다. 일반 입력·조회·DELETE 요청은 **20초**, action의 postcondition timeout은 기존 **1~15초**를 유지합니다. 필요한 경우 `--session-create-timeout 120`처럼 **30~300초의 정수**를 지정할 수 있습니다. 이 값은 HTTP 통신 대기시간이며 전체 설치 과정의 완료를 보장하는 제한시간은 아닙니다. 기기/드라이버 내부의 설치·실행 timeout은 별도로 적용됩니다.

대기시간을 늘려도 설치 검증 실패, 사용자 확인 화면, 지원되지 않는 Android 버전은 해결되지 않습니다. 시간초과 시 서버에서 세션이 이미 생성됐을 수도 있으므로 자동 재시도하지 않으며 기존 `.active`/`.quarantine` 복구 절차를 따릅니다. 원인을 확인하기 전 반복해서 Connect를 누르지 마세요.

고정된 UiAutomator2 6.0.0은 초기화 중 Settings 및 서버 helper를 설치하고, hidden API 정책 완화와 helper의 mock-location 권한 설정을 시도할 수 있습니다. 연결 전에 필요한 변경 범위에 동의하고 원래 값을 기록한 뒤, 종료 후 복구를 확인해야 합니다. 드라이버의 기본값 복구가 사용자의 기존 값 복원과 같다고 가정하지 않습니다. 설치가 확인 화면이나 검증 실패로 막히면 그 상태를 확인하고 중단하며 전역 보안 기능을 끄지 않습니다.

`skipDeviceInitialization` 등 임시 옵션은 이 문제의 일반적인 해결책이 아닙니다. 해당 옵션으로도 hidden API 변경이나 mock-location 설정 시도가 남을 수 있고, `skipServerInstallation`은 설치 검사를 생략합니다. 이 수정에서는 이러한 옵션을 기본값으로 추가하지 않았습니다. 별도의 사전 설치 프로필은 helper 버전·해시·서명·설정 복구 검증이 갖춰진 뒤 검토해야 합니다.

이 보완의 회귀 검증은 Windows/Python 3.13에서 합성 unit·fake HTTP 테스트 **39/39 통과**와 CLI 인자 검증으로 제한됩니다. 새 테스트는 timeout 선택·범위, 불확실한 결과의 재시도 금지, 잠금 권한 거부와 handle 정리를 확인합니다. 권장 Python 3.12와는 버전 차이가 있으며, 변경 후 기기 재연결·GUI 시험은 수행하지 않았습니다. 따라서 기본 초기화의 실기기 성공이나 P1 전체 인수시험 통과를 의미하지 않습니다.

Windows npm 설치에서는 기존 lockfile의 Sharp 플랫폼 선택 의존성 누락 22개로 `npm ci`가 실패하는 경우를 재현했습니다. 기존 잠금 항목과 Appium/UiAutomator2 버전을 유지하고 공식 npm 레지스트리의 버전·tarball·SHA512와 일치하는 누락 항목만 추가한 뒤, `npm ci --ignore-scripts --no-audit --no-fund`와 Windows x64 Sharp 로드를 확인했습니다. 이 설치 검증도 Android 기기 호환성 검증을 대신하지 않습니다.

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

- 정상 닫기는 현재 유한 요청을 기다리고 DELETE session 성공 후 lease를 해제합니다. Appium 서버는 사용자가 시작한 것이므로 프로그램이 강제 종료하지 않습니다. 일반 요청의 통신 timeout은 20초이고, 세션 생성 중 닫으면 별도로 설정한 생성 timeout(기본 90초)의 영향도 받습니다.
- Windows에서 잠금 파일 접근 권한 오류가 나면 recorder를 **같은 Windows 사용자 계정**으로 실행하고 `%USERPROFILE%\.mobile-finsec-poc`의 접근 권한을 확인하세요. 다른 계정·격리 환경에서 같은 사용자 경로를 가리키면 접근이 거부될 수 있습니다. 프로그램은 대체 잠금 경로를 만들거나 ACL을 바꾸거나 기존 marker를 삭제해서 우회하지 않습니다. 파일 초기화 실패 시 열린 handle은 닫습니다.
- timeout/프로세스 crash에는 `%USERPROFILE%\.mobile-finsec-poc`에 `.active`/`.quarantine`이 남습니다. 이 상태는 자동 해제하지 않습니다. **Appium 서버를 종료하고 진행 중 기기 명령이 없음을 직접 확인한 후에만**, 해당 장치 해시의 marker를 수동 제거하고 서버/프로그램을 재시작하세요. 다른 실행이 살아 있는데 marker를 지우지 않습니다.
- 디스크 full/crash 때 마지막 journal 행이 잘릴 수 있습니다. `finished` 및 완료 route가 없는 journal은 incomplete입니다. 자동으로 완료 route로 복구하지 않습니다.
- 증거에는 앱 화면/UI tree/공개 QA 입력이 들어갑니다. 테스트 앱 외 foreground로 바뀌면 다음 작업을 중단하지만 순간적인 외부 전환의 모든 픽셀 노출을 차단하는 제품은 아닙니다. 이 테스트 동안 다른 앱을 사용하지 마세요.
- 실제 비밀번호/계좌를 입력하지 마세요. public fixture 4개 문자열 외의 text는 거부합니다.

## 다시 빌드할 때의 주의사항

위 APK 준비 A 절차를 **PoC 루트**에서 다시 실행합니다. `Push-Location`/`Pop-Location`으로 빌드 후에도 PoC 루트를 유지합니다.

Gradle **8.9**, Android Gradle Plugin **8.7.3**, SDK **35**, Build-Tools **35.0.0**. PoC 루트 기준 `android\app\build\outputs\apk\debug\app-debug.apk`가 생성됩니다. debug 키는 본인 환경에서 생성됩니다. 배포 ZIP에는 개인 키를 포함하지 않습니다. 새 빌드는 서명/해시가 달라 기존 route와 호환되지 않을 수 있으므로 새 기록을 만듭니다. `targetSdk=28`은 이 격리 fixture의 인셋을 단순화하기 위한 선택이며 최신 Android 제품 보안 기준 준수 주장이 아닙니다.

## 미리보기 갱신과 검은 화면 구분

화면 조회 중의 입력은 한 개만 대기하며 조회가 성공한 뒤 실행합니다. 이미 대기 중인 입력이 있거나 실제 입력 작업이 진행 중이면 추가 입력을 거절합니다. 조회 실패·연결 불확실성·창 종료 시 대기 입력은 전송하지 않습니다. 프레임 확인 체크는 진행 중이던 조회가 돌아와도 현재 표시를 유지하며, 입력 완료 후 자동 해제되어 새 화면을 받습니다.

녹화 종료는 마지막 단계의 `Recorded step` 완료를 확인한 다음 수행합니다. 폴링과 STOP이 겹치지 않도록 보이는 프레임의 확인 체크를 선택하고 `Preview held`가 표시된 뒤 STOP을 누르면 완료 route를 저장할 수 있습니다. 입력 진행 중 STOP의 보수적인 incomplete 처리는 그대로 유지됩니다.

`Connect (no reset)`은 기존 앱 데이터를 초기화하지 않습니다. 이미 실행 중인 앱이 백그라운드에 있으면 자동으로 전면화되지 않을 수 있으므로 `dev.finsec.poc`를 직접 엽니다. P1은 해당 합성 앱이 전면인 동안에만 약 900ms 간격으로 캡처를 요청합니다. 실제 갱신 간격은 Appium 응답 시간에 따라 달라집니다.

- 홈/다른 앱으로 전환: 이전 프레임과 클릭 매핑을 제거하고 `Preview paused: target app is not foreground`를 표시합니다. 일반 앱을 기록하거나 우회 캡처하지 않습니다.
- 대상 앱으로 복귀: 다음 정상 조회에서 새 프레임과 수신 시각을 표시합니다.
- 캡처/연결 실패: 이전 이미지를 유지하지 않고 실패 사유를 표시합니다. transport 결과가 불확실하면 기존 복구 절차를 따릅니다.
- `secure:on`: 합성 앱 UI 계층에서 확인한 FLAG_SECURE 상태입니다. 캡처 API가 PNG를 반환해도 앱 영역은 검게 나올 수 있습니다. 검은 픽셀만으로 원인을 판정하지 않습니다.
- 좌표 입력용 화면 확인 체크: 의도적으로 프레임 갱신을 멈추며 `Preview held`를 표시합니다. 체크를 해제하면 갱신을 재개합니다.

진단 시에는 동일 시점의 ADB 원본, Appium 원본, P1 수신 시각을 비교합니다. 실기기 식별자·홈 화면·UI XML·로그·APK 해시는 로컬에만 보관합니다.
