# S2: APK 합성 평문 노출 위치 탐지

이 독립 S 확장 POC는 공개 가능한 고정 합성 문자열만 APK의 압축 해제된 entry 바이트에서 찾습니다. 실제 비밀정보 탐지기나 CHK-11 통과 판정기가 아닙니다. Python 표준 라이브러리와 형제 S1의 `apk_budget.py`만 사용하며 기기·SDK·네트워크를 호출하지 않습니다.

## 원래 기준과 모바일 적용 차이

원래 사용자 항목은 **프로그램 실행 명령줄 내 중요정보 평문 노출 방지**입니다. 저장소의 [CHK-11 명세](../../docs/spec/09-checks-poc.md)는 정의된 중요정보가 실제 실행 인자에 노출되면 취약, 허용된 실행 인자 관찰 범위가 충분하고 노출이 없으면 양호, 관찰 불가·유형/범위 불명확이면 판단 불가능으로 정합니다. CHK-11은 내부 식별자이며 공식 원문의 문서명·버전·대상 플랫폼 대응은 아직 확정하지 않았습니다. 이 설명을 공식 기준 원문의 인용으로 취급하지 않습니다.

APK에 문자열이 있다는 것은 패키지 내부의 정적 바이트 근거입니다. 그 문자열이 실행 인자로 전달되었거나 실제 비밀이라는 뜻이 아닙니다. 반대로 APK에 없어도 실행 중 생성·수신된 중요정보가 인자에 나타날 수 있습니다. Android 실행 인자, Intent/IPC, 로그, 런타임 메모리 등은 별도 허용 관찰 범위와 중요정보 유형 정의가 필요합니다. 여기서는 모두 미실행입니다.

모든 결과의 `verdict`는 `inconclusive`, `commandline_observation`은 `not_run`입니다. `literal_observation=found/not_observed`는 고정 카탈로그 바이트의 발견 여부에만 적용합니다. 미발견을 양호나 안전으로 승격하지 않습니다.

## 탐지 계약과 증거

- 카탈로그 v1: `demo_token` = `QA_PLAINTEXT_DEMO_TOKEN_001`, `qa_status` = `QA_INVALID`. 둘 다 공개 샘플이며 실제 계정·토큰·인증정보가 아닙니다. 사용자 임의 비밀값이나 정규식 입력은 지원하지 않습니다.
- APK SHA-256, entry 이름·SHA-256, marker ID, 길이, 압축 해제된 entry의 0 기반 바이트 offset을 기록합니다. 주변 내용·값 자체는 결과에 복사하지 않습니다. 카탈로그 길이·해시를 함께 기록합니다.
- ASCII/UTF-8 일치만 검사합니다. DEX 의미 분석, UTF-16/base64 해독, 암호문 복원, 중첩 아카이브 재귀, 실행 경로/도달 가능성 분석은 하지 않습니다. native나 WebView asset에서 발견되어도 단순 바이트 위치일 뿐입니다. DEX offset은 명령어 주소가 아닙니다.
- `complete`는 ZIP entry의 고정 바이트 검사 범위만 완료했다는 뜻이며 APK 유효성·서명 검증·앱 전체 보안 점검 완료가 아닙니다. ZIP 형태 합성 fixture도 수용합니다.
- 출력 폴더는 새 경로만 허용합니다. 원본 APK snapshot을 보관하므로 **결과 폴더 전체를 비공개**로 관리합니다. entry 이름도 민감할 수 있어 결과 JSON을 자동 공개하지 않습니다. 공개 검증 문서에는 합성 시험 집계만 싣습니다.

## 자원 한도와 실패

S1 [자원 예산](../s1-apk-obfuscation/docs/RESOURCE-BUDGETS.md)의 snapshot, 사전 central-directory 한도, entry 경로/중복 검사, CRC, 압축 비율, 누적 압축 해제량 및 디스크 여유 검사를 재사용합니다. 기본 입력 32 MiB, entry 8 MiB, 누적 64 MiB, 작업 디스크 128 MiB, 여유 64 MiB, 전체 120초입니다. 입력 한도를 높여도 나머지 한도를 독립 적용합니다. CLI는 `--apk-mib`, `--disk-mib`를 제공하며 API는 검증된 `Limits` 전체를 받습니다. JVM 전용 예산은 이 POC에서 사용하지 않습니다.

128 KiB 청크와 최장 marker 길이의 overlap으로 검사합니다. 결과 최대 100건(설정 범위 1~1000), 디렉터리 메타데이터와 결과 목록도 유한합니다. 시간 한도는 각 읽기 전 협력적 검사이며 OS 강제 메모리/CPU 격리가 아닙니다. 입력 inventory와 literal scan의 두 번 압축 해제가 총 시간 예산을 공유합니다. 제품 수준 대형 금융 APK 성능은 미검증입니다.

inventory 실패 시 `not_started`, 검사 도중 오류/시간 초과/검출 상한 시 `partial`입니다. 완료된 청크의 근거는 보존하며 상한을 초과한 현재 청크는 채택하지 않습니다. 따라서 partial의 빈 matches는 미발견의 증거가 아닙니다. 결과 파일은 임시 파일 후 rename하며 쓰기 실패에는 성공 결과를 반환하지 않습니다. 전원 장애 내구성을 보증하지 않습니다. CLI 0은 검사 완료만, 2는 오류/부분 검사입니다.

## 실행과 재현

Python 3.12, 이 디렉터리에서 실행합니다. 출력은 저장소 밖의 비공개 경로를 지정합니다.

```powershell
python -m unittest -v
python qa_fixture.py <직접_만든_S1_plain.apk> <비공개_새_qa.apk>
python scan.py <비공개_새_qa.apk> <비공개_새_결과폴더>
python scan.py <비공개_qa.apk> <또다른_결과폴더> --apk-mib 64 --disk-mib 128
```

QA 원본은 [S1 자체 APK 생성](../s1-apk-obfuscation/README.md) 절차를 사용합니다. fixture 작성기는 작은 자체 APK 전용이며 일반 비신뢰 APK 변환 도구가 아닙니다. unsigned APK에 합성 asset만 추가하고 설치하지 않습니다. [실행 결과](VALIDATION.md)를 참고하세요.
