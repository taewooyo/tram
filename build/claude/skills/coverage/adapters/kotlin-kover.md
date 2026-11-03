# Android / KMP JVM / Kover 어댑터

이 어댑터는 명시적으로 선택된 Android 로컬 JVM 단위 테스트와 KMP JVM 타깃만 측정한다. Android 기기 계측 테스트, KMP iOS·JS·Native 타깃은 지원 범위가 아니다. [Kover 공식 문서](https://kotlin.github.io/kotlinx-kover/gradle-plugin/)도 KMP의 JVM 타깃만 측정하고, Android 기기 계측 테스트는 수집하지 않는다고 명시한다.

## 프로젝트 설정

`.tram/project.json`의 기존 schema·revision·프로젝트 매핑을 유지하고 명시적 `coverage`를 설정한다. legacy `.codex/project-profile.json` 예시는 `version`과 `contextMappings`를 보존한다. 다음은 coverage 구조 예시이며 전체 신규 프로필을 대체하지 않는다.

```json
{
  "version": 1,
  "contextMappings": [],
  "coverage": {
    "adapter": "kotlin-kover",
    "target": 85,
    "modules": [":shared"],
    "testPaths": ["shared/src/commonTest", "shared/src/jvmTest"],
    "gradle": {
      "wrapper": "gradlew",
      "tasks": [
        {
          "scope": "jvm",
          "task": ":shared:koverXmlReportJvm",
          "report": "shared/build/reports/kover/report.xml"
        }
      ]
    },
    "kmp": {
      "jvmTargets": ["jvm"],
      "nonJvmTargets": "unsupported"
    }
  }
}
```

이 값들은 구조 예시다. 실제 모듈, variant, JVM 타깃, Kover task 및 XML 경로를 프로젝트의 Gradle 설정과 `./gradlew tasks --all` 결과로 확인해 바꾼다. Kotlin 목표는 필수 설정이며 Python의 `85%`/`app/` 기본값을 자동 적용하지 않는다. `testPaths`는 테스트만 편집·체크포인트·롤백할 수 있게 허용하는 프로젝트 상대 경로 allowlist다.

`tasks`에는 `:module:koverXmlReportJvm`, `:app:koverXmlReportDebug` 같은 Kover XML report task와 `jvm` 또는 `androidDebug` 형식의 scope만 넣는다. 셸 인자나 임의 명령을 넣지 않는다. 프로필 검증은 Kover XML task 형식 및 알려진 non-JVM·연결 기기·계측 task 표식을 거부한다. task를 profile에 등록하기 전에 Gradle task graph/dependency를 확인해 Android local unit test만 실행되는지 검증한다. 프로젝트 wrapper는 Gradle 빌드 스크립트를 실행하므로 신뢰하는 프로젝트에서만 실행한다.

## 입력·환경 및 실행 정보

1. 입력은 `/coverage [목표%]`이다. 목표 생략 시 프로필의 `coverage.target`을 사용하고, 명시한 목표는 이번 실행에만 적용한다. 목표는 1~100의 정수다. 측정 모듈·task/report·테스트 수정 경로는 프로필에서 가져온다. Python의 기본 대상이나 경로 인자를 적용하지 않으며, 추가 대상 인자가 있으면 지원하지 않는 형식을 보고한다. 실행 중 프로필을 바꾸거나 task를 임의로 필터링하지 않는다.
2. 프로필을 실제 검사한다: `bash -c 'source "$1/scripts/lib/coverage-profile.sh" && coverage_profile_validate "$2"' _ "<plugin-root>" "<target>"`. 누락·오류는 보고하고 멈춘다. `coverage.adapter`가 `kotlin-kover`인지 확인하고 다른 어댑터로 자동 전환하지 않는다.
3. `bash "<plugin-root>/scripts/check-environment.sh" coverage-kotlin --project "<target>"`으로 환경을 검사한다. 프로젝트의 `coverage.gradle.wrapper`를 사용한다. JVM 검사 및 XML 해석을 위한 OS 런타임 도구를 확인하되 pytest·pytest-cov·Python 가상환경 설치는 요구하지 않는다.
4. 공통 실행 정보를 확정한다: 목표 = 인자 또는 `coverage.target`, 측정 대상 = `coverage.modules`, 테스트 수정 허용 경로 = `coverage.testPaths`, 실행 명령 = 지정 wrapper와 `coverage.gradle.tasks[*].task`, 보고서 = 각 원소의 `scope`와 `report`. 모듈·경로·scope·보고서 목록을 사용자에게 요약한다.
5. 지정 task들의 `--dry-run` 그래프로 테스트가 있는 대상 모듈의 JVM/Android local unit test 작업이 포함되는지 확인한다. 기기 계측·연결 기기·non-JVM 테스트가 섞이거나 기존 대상 테스트가 누락되면 멈춘다. 실제 테스트 범위를 이 그래프로 기록한다. 루트 집계 task는 의존 모듈과 포함 variant까지 확인한다. 테스트가 없는 모듈도 측정 대상 코드에 포함할 수 있으며, 해당 모듈의 `NO-SOURCE` 결과는 테스트 실패가 아니다.

이후 [상위 SKILL.md의 공통 루프](../SKILL.md#진행)를 진행한다. 깨끗한 비기본 브랜치와 시작 HEAD를 확인하고, 기준선과 각 라운드를 아래 같은 방식으로 측정한다.

## 기준선 및 각 라운드의 측정

1. 실행 시작 시각과 기존 XML의 상태를 기록한다. 지정 wrapper를 프로젝트 루트에서 실행하며 **등록된 task들을 각각 별도 인자로 전달**한다. `--rerun-tasks --console=plain`을 붙여 대상 테스트와 XML 생성 작업을 다시 실행한다. 실행 명령을 셸 문자열로 합성하거나 `test`, `connectedAndroidTest` 등 설정 밖의 task를 추가하지 않는다.
2. Gradle 종료 코드와 대상 테스트 결과를 확인한다. 등록된 XML이 모두 이번 실행에서 다시 생성됐는지 확인한다. 실패, 누락, 오래된 파일, 기존 테스트가 있는 작업의 예상치 못한 실행 생략이 있으면 기준선·라운드를 인정하지 않는다. 테스트 소스가 없는 작업의 `NO-SOURCE`는 별도로 기록한다.
3. 기존 [kover-report.py](../../../scripts/lib/kover-report.py)를 재사용한다. 각 task/report에 `--report 'scope@task=프로젝트상대XML경로'` 인자를 별도로 넘긴다. 같은 scope를 여러 task가 사용하는 경우도 task를 포함한 고유 식별자로 구분한다. 단일 보고서 예:

   ```bash
   python3 "<plugin-root>/scripts/lib/kover-report.py" --report 'jvm@:koverXmlReport=build/reports/kover/report.xml'
   ```

4. 반환 JSON의 `combined.covered`, `combined.missed`, `combined.total`을 비교 지표로 기록한다. 목표 도달은 원본 라인 수로 비교하고, `combined.percent`는 표시용으로 쓴다. 패키지·소스 파일명·라인 번호를 기준으로 여러 클래스와 보고서의 line hit를 합집합 처리해 중복 라인을 한 번만 센다. 같은 클래스가 서로 다른 소스 파일에 귀속되면 오류로 처리한다. 서로 다른 모듈의 동일 패키지·파일명은 XML만으로 구별할 수 없으므로 같은 소스 범위의 보고서만 합산한다. 파서 실패·빈 데이터·모호한 소스 귀속이면 수치를 추정하지 않고 중단한다. 미실행 위치는 해당 XML의 sourcefile/line 정보를 기존 소스와 대조해 선택한다.
5. 같은 모듈·task/report·설정·소스 범위로 직전 승인 라운드와 비교한다. 테스트만 바뀌었는데 집계 대상 또는 총 라인 수가 달라지면 원인을 확인하고, 비교 가능성을 확보하지 못하면 라운드를 인정하지 않는다.

## 변경·체크포인트·종료 연결

- 라운드의 테스트 추가·갱신, diff 검사, 스테이징, 롤백 모두 `coverage.testPaths` 안의 개별 테스트 파일로 제한한다. 제품 코드·Gradle·프로필 변경은 루프 범위 밖이다.
- 공통 루프의 독립 리뷰·안전 예산·승인된 라운드 체크포인트를 그대로 적용한다. 테스트 실패·커버리지 후퇴·리뷰 지적이면 이번 라운드의 허용 파일만 되돌린다. 경계가 불명확하면 변경을 보존하고 중단한다.
- 최종 보고와 `docs/coverage-health.md`에는 어댑터, 모듈, task/report, 실제 테스트 범위, 보고서별·합산 라인 수와 커버리지를 포함한다. 루트 집계 보고서는 포함된 Android variant와 JVM 모듈을 설명한다. Android local JVM only, KMP JVM/common-from-JVM-tests only 및 제외된 플랫폼을 명시하며, 설정 밖의 테스트나 전체 KMP·기기 계측 coverage처럼 표현하지 않는다.
