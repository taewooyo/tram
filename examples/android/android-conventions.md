# Android 컨벤션 (Kotlin · Jetpack Compose)

> 이 카드는 이 저장소의 Android/Kotlin 코드를 작성·검토할 때 적용한다. `.codex/project-profile.json`은
> `app/`, `domain/`, `data/`, `navigator/`, `presentation/`, `build-logic/`, `buildconfig/`, `buildconfig-stub/`,
> `gradle/` 및 루트 Gradle 스크립트 편집에 이 카드를 연결한다.
> 규칙은 여기 한 곳에 둔다. 실제 프로젝트의 확정 Plan과 기존 구조를 먼저 확인한다.

## 모듈과 레이어 (책임 분리 — 위→아래로만 의존)

```
app → presentation → domain
                  ↘ data → domain
Compose 화면 → ViewModel → Repository 계약 ← Repository 구현 → 데이터 소스
```

- **모듈 구조**: Gradle 다중 모듈 구조를 유지한다. 기능 UI는 `presentation/<feature>/{api,impl}`, 공통 도메인은 `domain/`, 데이터 구현은 `data/`의 기존 하위 모듈에 둔다. 앱 조립과 진입점은 `app/`, 내비게이션 공통 구현은 `navigator/`, Gradle convention plugin은 `build-logic/` 책임이다. 새 모듈·경계를 만들기 전에 기존 모듈을 재사용한다.
- **의존 방향**: Presentation은 Domain 계약에 의존하고, Data는 Domain 계약을 구현한다. Domain은 Android UI·네트워크 구현에 의존하지 않는다. 앱 조립 계층에서 구현체를 연결하며 역방향 의존을 만들지 않는다.
- **Compose 화면**: UI 상태를 렌더링하고 사용자 이벤트를 ViewModel에 전달한다. DB·네트워크를 직접 호출하지 않는다.
- **ViewModel**: 프로젝트의 State·Intent·SideEffect 규칙과 기존 화면 패턴을 따른다. 로딩·성공·실패 상태를 관리하고 비동기 작업은 적절한 coroutine scope에서 수행한다.
- **Repository**: 계약은 Domain에 두고 구현은 Data에 둔다. 데이터 접근을 캡슐화하며 UI 렌더링이나 화면 이동을 담당하지 않는다.
- **데이터 모델·UI 상태**: 저장·전송 모델과 화면 상태의 책임을 구분한다. 기존 모델을 우선 재활용한다.
- **API 및 구현 모듈**: `api` 모듈은 기능 간 공개 계약을, `impl` 모듈은 구현을 담당한다. 공개 계약을 바꾸기 전에 기존 네비게이션·DI 연결과 사용처를 확인한다.

## 에러 처리 (반드시 지킬 것)

- 입력 검증 오류와 데이터 접근 실패를 UI 상태로 전달한다. 화면은 사용자에게 이해 가능한 메시지를 표시한다.
- 로딩 중에는 제출을 비활성화하고 중복 요청을 막는다.
- 로그인 실패는 계정 존재 여부를 노출하지 않는 동일한 메시지로 처리한다.
- 시크릿·토큰·개인정보를 코드나 로그에 남기지 않는다.

## 관례

- **한국어 KDoc** — 필요한 모듈·함수에 "무엇을/왜"를 설명한다.
- **이름**: 타입·Composable은 PascalCase, 함수·속성은 camelCase, 패키지는 소문자. 기존 코드 스타일을 따른다.
- **시각**: 저장·전송은 UTC를 기준으로 하고 사용자 표시는 로컬 시간대로 변환한다.
- **수명주기**: ViewModel은 화면 수명주기에 맞춰 관리하고, 상태 수집과 이벤트 처리는 수명주기를 고려한다.

## 테스트 (OS 원칙 — 구현의 일부)

- 각 Gradle 모듈의 JVM 테스트는 해당 모듈 `src/test/`에 둔다. `src/androidTest/`는 실제 Android 기기 동작이 필요한 경우에만 기존 모듈 설정을 확인해 사용한다.
- ViewModel·Domain·Repository·매퍼·네트워크 계약 테스트는 주변 코드의 테스트 프레임워크와 fixture를 재사용한다. 현재 테스트에는 Kotest와 JUnit 기반 테스트가 있으므로 새 프레임워크를 임의로 추가하지 않는다.
- Fake·Mock과 coroutine test 도구를 사용해 네트워크·시간·스케줄러를 격리한다. UI 테스트는 요구사항과 기존 테스트 인프라가 있을 때 추가한다.
- 입력 검증·상태 전이·성공/실패·중복 요청·화면 이벤트 등 관찰 가능한 동작을 검증한다. 실행하지 못한 기기 테스트는 통과로 보고하지 않는다.
- 커버리지 프로필은 Kover로 Android local JVM 및 JVM 모듈 테스트를 측정한다. 기기 계측 테스트 커버리지를 포함한다고 표현하지 않는다.

> 흐름·게이트 등 개발 전반 규칙은 저장소의 [공통 flow-rules](../../src/context/flow-rules.md)를 참조.
