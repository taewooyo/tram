<a id="top"></a>

<div align="center">



<h1>Tram</h1>

<p><strong>의도는 선명하게. 개발은 끝까지.</strong></p>
<p>AI 코딩 에이전트를 위한 오픈소스 개발 하네스<br><sub>Codex · Claude Code · 더 많은 에이전트 지원 예정</sub></p>

<p>
  <a href="https://github.com/taewooyo/tram/actions/workflows/build.yml"><img src="https://github.com/taewooyo/tram/actions/workflows/build.yml/badge.svg?branch=main" alt="CI 검사 상태"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-138B8B?labelColor=17252B" alt="Apache-2.0 라이선스"></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/version-0.0.1%20alpha-138B8B?labelColor=17252B" alt="0.0.1 alpha"></a>
</p>

<p>
  <a href="#install">설치</a> ·
  <a href="#start">시작하기</a> ·
  <a href="#flow">작업 흐름</a> ·
  <a href="docs/support.md">지원 조건</a> ·
  <a href="https://github.com/taewooyo/tram/issues">질문·피드백</a>
</p>

</div>

## 요청에서 검증된 변경까지

Tram은 AI 코딩 에이전트에 설치하는 개발 하네스 플러그인입니다. 만들고 싶은 것을 요청하면 프로젝트를 조사하고, 요구사항과 구현 계획을 함께 정한 뒤 구현·테스트·검증을 이어갑니다. 새 세션에서도 남겨 둔 기록으로 작업을 재개합니다.

**사용자는 무엇을 만들지, 어떻게 만들지 결정합니다.** 에이전트는 승인된 범위 안에서 작업하고, 실제로 확인한 결과와 남은 문제를 보고합니다.

<a id="install"></a>

## 설치와 업데이트

### Codex

공개 저장소의 패키지를 설치합니다. 사용자가 소스를 빌드할 필요는 없습니다. 아래 명령은 배포본이 공개 저장소에 반영된 뒤 사용할 수 있습니다.

```bash
codex plugin marketplace add taewooyo/tram
codex plugin add tram@tram
```

설치 후 새 세션에서 Tram을 사용하세요. Desktop에서는 Plugins Directory에서 **Tram**을 찾아 설치할 수도 있습니다. 필요한 Python 3.10+와 프로젝트의 빌드·테스트 도구를 준비합니다.

업데이트:

```bash
codex plugin marketplace upgrade tram
```

marketplace를 갱신한 뒤 새 세션에서 설치본 반영을 확인합니다. 이전 `tram-local` 설치를 사용했다면 [전환 안내](docs/setup.md#기존-tram-local에서-전환)를 따릅니다.

### Claude Code

Claude Code 세션에서 설치합니다.

```text
/plugin marketplace add taewooyo/tram
/plugin install tram@tram
```

업데이트:

```text
/plugin marketplace update tram
/plugin update tram@tram
```

설치·업데이트 후 새 세션에서 사용하세요. Codex와 Claude Code는 같은 기능의 호스트별 패키지를 제공합니다. 실제 확인을 마친 범위는 [지원 조건](docs/support.md)에서 구분합니다.

현재 `0.0.1`은 공개 준비 단계입니다. 지원 범위와 실제 확인한 결과는 [지원 조건](docs/support.md)·[검증 기록](docs/release-validation.md)을 참조하세요.

<a id="start"></a>

## 첫 작업 시작하기

프로젝트를 열고 에이전트에게 요청하세요. 아래는 터미널 명령이 아닌 대화 예시입니다.

**1. 프로젝트를 연결합니다.** 프로젝트마다 처음 한 번 실행하고, 환경이 달라지면 다시 확인합니다.

```text
Tram의 init 스킬로 현재 프로젝트를 연결해 주세요.
```

Claude Code에서는 `/tram:init`으로 연결합니다.

**2. 만들고 싶은 것을 요청합니다.**

```text
Tram의 start 스킬로 로그인 화면에 비밀번호 표시 기능을 추가해 주세요.
```

Claude Code에서는 `/tram:start 로그인 화면에 비밀번호 표시 기능을 추가해 주세요.`로 요청합니다.

에이전트가 코드·테스트·문서를 먼저 살펴보고 필요한 결정만 질문합니다. 요구사항(PRD)을 확정하고 구현 계획(Plan)을 승인하면 구현과 검증을 이어갑니다. 두 승인 단계에서 목적·범위와 변경 방향을 확인하세요.

**3. 결과를 확인합니다.** 변경 내용, 실제 실행한 검사, 관련 문서 반영, 남은 제한을 보고받습니다. 커밋·푸시·PR은 원하는 마무리 방법을 요청하면 별도로 진행합니다.

작업을 이어가려면 새 세션에서 같은 프로젝트를 열고 요청하세요.

```text
Tram의 start 스킬로 이전 작업을 이어서 진행해 주세요.
```

상태만 보고 싶다면:

```text
Tram의 status 스킬로 현재 작업과 다음 행동을 확인해 주세요.
```

Claude Code에서도 `/tram:start`로 재개하고 `/tram:status`로 조회합니다. 작업이 여러 개라면 대상을 선택합니다. `status`는 기록을 바꾸지 않습니다.

<a id="flow"></a>

## 사람이 결정하고, 에이전트가 이어갑니다



- **결정 전에 조사합니다.** 프로젝트 자료로 확인할 수 있는 사실부터 살펴보고, 사용자가 정해야 할 내용을 질문합니다.
- **승인한 범위를 유지합니다.** 요구사항·계획을 바꿔야 하면 다시 검토합니다.
- **실행 근거를 남깁니다.** 검사하지 못한 항목을 통과로 보고하지 않습니다. full 검증에는 새 독립 reviewer의 검사·검토가 필요합니다.
- **기존 작업을 보존합니다.** 작업 전 변경 상태를 확인하고 기존 파일·설정과 충돌하는 부분을 알립니다. 별도 작업 공간이 필요하면 선택형 Git worktree를 요청할 수 있습니다.

## 프로젝트에 남는 것

| 위치 | 내용 |
| --- | --- |
| `docs/prd/`·`docs/plan/` | 작업별 요구사항·계획과 승인 스냅샷 |
| 기존 프로젝트 문서, 필요 시 `docs/domain/`·`docs/knowledge/` | 확인된 프로젝트 지식과 결정 이유 |
| `.tram/` | 프로젝트 설정·단계·승인·검증 기록 |
| `.tram/local/` | Git에서 제외하는 실행 메모·로컬 운영 자료 |

다음 작업에서는 기존 지식을 참고합니다. 플러그인을 제거해도 프로젝트 문서와 기록은 보존합니다. 연결 해제와 제거 방법은 [설치 안내](docs/setup.md#연결-해제와-제거)를 참조하세요.

## 필요할 때 사용하는 기능

일상적인 작업은 `init`·`start`·`status`로 시작할 수 있습니다. 전문 스킬도 같은 Tram 플러그인에 포함됩니다.

| 목적 | 스킬 |
| --- | --- |
| 작고 명확한 저위험 변경 | `quick` |
| 테스트 커버리지 개선 | `coverage` |
| 동작을 보존하는 성능 개선 | `perf-loop` |
| 도메인 지식 정리·세션 회고 | `domain`·`retro` |
| 설명 도식·사용 통계 | `diagram`·`skill-stat` |
| 변경 저장·원격 반영·리뷰 요청 | `commit`·`push`·`pr` |

스킬별 도구·설정 조건은 [지원 조건](docs/support.md)을 따릅니다.

<a id="docs"></a>

## 문서와 피드백

| 알고 싶은 내용 | 안내 |
| --- | --- |
| 설치·업데이트·기존 설치 전환·제거 | [설치 안내](docs/setup.md) |
| 지원 환경과 기능별 조건 | [지원 조건](docs/support.md) |
| 막힌 이유·진단·복구 | [운영 안내](docs/operations.md) |
| 실제 검증 결과와 남은 확인 | [검증 기록](docs/release-validation.md) |
| 사용 흐름을 그림으로 보기 | [문서 색인](https://github.com/taewooyo/tram/tree/main/docs) |

질문·사용 피드백·버그 제보는 [GitHub Issues](https://github.com/taewooyo/tram/issues)에 남겨 주세요. 보안 문제는 [보안 제보 안내](SECURITY.md)를 따릅니다.

개발에 참여하려면 [기여 안내](CONTRIBUTING.md)를 확인하세요. 내부 흐름과 설계는 [OS.md](OS.md)에서 설명합니다.

## 라이선스

[Apache License 2.0](LICENSE).

<div align="center">

<br><sub>요구사항을 정하고. 계획을 승인하고. 검증된 변경까지.</sub><br><a href="#top">맨 위로 ↑</a>
</div>
