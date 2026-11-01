# Tram 설치와 프로젝트 연결

Codex 또는 Claude Code에 Tram 플러그인을 설치하고 프로젝트에서 작업을 시작한다. 같은 저장소가 호스트별 패키지를 제공하며 스킬을 따로 설치할 필요는 없다. `0.0.1/schema 2` 공개 준비 단계로 실제 확인 범위는 [지원 조건](support.md)·[검증 기록](release-validation.md)을 따른다.

## Codex 설치

터미널에서 marketplace를 등록하고 플러그인을 설치한다. 공개 저장소에 배포본이 반영된 뒤 사용할 수 있다. 사용자가 Python 패키지를 빌드하거나 개발용 의존성을 설치할 필요는 없다.

```bash
codex plugin marketplace add taewooyo/tram
codex plugin add tram@tram
```

설치 후 새 세션을 연다. Desktop에서는 등록된 marketplace의 Tram을 Plugins Directory에서 설치할 수도 있다. 패키징과 UI는 [Codex 공식 안내](https://developers.openai.com/plugins/build/plugins), CLI 옵션은 [개발자 명령 안내](https://learn.chatgpt.com/docs/developer-commands#codex-plugin-marketplace)를 따른다.

업데이트:

```bash
codex plugin marketplace upgrade tram
```

이 명령은 Git marketplace를 갱신한다. 새 세션에서 설치된 스킬·버전·변경 내용이 반영됐는지 확인한다. 반영되지 않으면 플러그인을 제거·재설치하고 아래 동일성 비교로 확인한다. 자동 갱신의 주기나 실제 성공을 Tram이 보장하지 않는다.

## Claude Code 연결부

Claude Code 세션에서 다음 명령으로 같은 저장소의 Claude용 패키지를 설치한다. Codex 패키지를 함께 설치할 필요는 없다.

```text
/plugin marketplace add taewooyo/tram
/plugin install tram@tram
```

설치 범위를 선택하고 새 세션을 연다. 업데이트는 다음과 같다.

```text
/plugin marketplace update tram
/plugin update tram@tram
```

터미널에서도 `claude plugin marketplace add taewooyo/tram`, `claude plugin install tram@tram`을 사용할 수 있다. 설치 범위와 자동 업데이트 설정은 [Claude Code 공식 안내](https://code.claude.com/docs/en/discover-plugins)를 따른다. 제공하는 패키지와 실제 검증을 마친 범위는 [지원 조건](support.md)에서 구분한다.

## 연결·시작·조회

Python 3.10+와 대상 프로젝트의 빌드·테스트 도구가 필요하다. full 검증에는 독립 reviewer를 실제 실행할 수 있는 호스트 기능도 필요하다.

Codex에서는 설치된 Tram 스킬을 자연어로 요청한다. 아래는 터미널 명령이 아닌 대화 예시다.

```text
Tram의 init 스킬로 현재 프로젝트를 연결해 주세요.
Tram의 start 스킬로 로그인 화면에 비밀번호 표시 기능을 추가해 주세요.
Tram의 status 스킬로 현재 작업과 다음 행동을 확인해 주세요.
```

Claude Code에서는 다음과 같이 요청한다.

```text
/tram:init
/tram:start 로그인 화면에 비밀번호 표시 기능을 추가해 주세요.
/tram:status
```

`init`은 대상 프로젝트에 `.tram/` 설정과 `AGENTS.md`·`CLAUDE.md` 관리 block, 로컬 기록 제외 규칙을 연결하고 스택·컨벤션·검증 명령 후보를 조사한다. 기존 사용자 본문과 충돌하는 관리 block은 보존한다. 발견한 후보를 자동 실행하지 않고 프로젝트 자료·요청 범위와 대조해 확정한다.

`start`는 새 기능의 요구사항(PRD) 확정과 구현 계획(Plan) 승인을 거쳐 구현·검증으로 이어간다. 새 세션에서도 같은 프로젝트에서 `start`로 재개하며 여러 작업이 있으면 대상을 선택한다. 작은 저위험 변경에는 `quick`을 사용할 수 있다. 내부 runtime 명령을 사용자가 순서대로 실행할 필요는 없다.

`status`는 단계·승인·검증·다음 행동을 읽기만 한다. 막힌 이유가 불분명하면 “Tram 상태와 다음 행동을 확인해 주세요”라고 요청한다. 직접 진단과 해석은 [사용 준비 상태 확인](operations.md#사용-준비-상태-확인)을 참조한다.

### 선택형 도입 조사와 관련 문서 점검

`init`의 환경·검증 명령 연결만으로 도입을 마칠 수 있다. 원하면 코드·테스트·문서·지침의 프로젝트 지식 조사를 선택할 수 있다. 구체적인 문서 보완 제안을 검토한 뒤 반영하며 조사 선택만으로 쓰기가 승인되지는 않는다.

일반 작업 종료에는 변경과 관련된 문서만 점검한다. 승인 범위의 근거 있는 보완을 마치고 검증하며 보완 내용이나 변경 불필요 이유를 보고한다. 새 정책·범위 밖 보완은 제안으로 남기고 PRD·Plan은 승인 스냅샷으로 보존한다.

### worktree 마무리 조회와 재개

기존 작업 폴더가 기본이며 분리된 실험은 선택형 Git worktree를 요청할 수 있다. 선택한 commit의 tracked 파일만 포함되므로 미커밋·untracked·ignored 변경은 원본에 남는다. 새 세션은 해당 경로를 다시 열어야 한다.

구현·검증 후 source와 선택한 target 상태를 확인해 merge·PR·그대로 두기의 제한과 다음 행동을 안내한다. 선택만으로 push·PR·merge를 실행하지 않는다. dirty·untracked·ignored 파일을 버리거나 강제 제거하지 않는다. 새 세션의 `start`는 마무리 메모와 현재 Git 상태를 다시 대조한다. 자세한 계약은 [시작·재개 경험](../context/start-experience.md#worktree-마무리와-재개)을 따른다.

## 프로젝트 기록

| 위치 | 내용 |
| --- | --- |
| `.tram/project.json` | 스택·검증 명령·입력·컨벤션·전문 기능 설정 |
| `.tram/installation.json` | 설치 버전·adapter·관리 항목 |
| `.tram/tasks/<slug>.json` | 단계·승인·검증 기록 |
| `.tram/local/` | Git 제외 로컬 로그·backup·잠금·실행 메모 |
| `.tram/local/tasks/<slug>.md` | 실행 목록·근거·제한·마무리 및 재개 메모 |
| `docs/prd/`·`docs/plan/` | 작업별 요구사항·계획·승인 스냅샷 |
| `docs/domain/`·`docs/knowledge/` | 필요한 경우 기록하는 도메인·프로젝트 지식 |

대상 프로젝트의 기록이며 Tram 저장소의 과거 개발 문서 삭제와 관계없이 새 작업에서는 필요한 문서를 생성한다. runtime 기록과 실행 메모는 역할이 다르다. 프로젝트 기록을 다른 호스트에서 읽더라도 승인·검증 근거와 해당 호스트 기능을 다시 확인한다. 두 호스트가 같은 작업 파일을 동시에 수정하지 않도록 한다.

## 연결 해제와 제거

프로젝트 연결을 해제하려면 “Tram의 프로젝트 연결을 해제해 주세요”라고 요청한다. 에이전트는 설치본 runtime의 `unlink`로 일치하는 관리 block만 제거한다. `.tram/`·문서·로그 제외 규칙은 보존한다. 사용자 수정·손상·중복 block은 충돌로 보고하며 임의로 덮어쓰지 않는다.

연결 해제와 본체 제거는 별개다. 연결 해제를 원하면 플러그인을 제거하기 전에 수행한다. Codex 본체 제거:

```bash
codex plugin remove tram@tram
```

Claude Code 세션에서 본체 제거:

```text
/plugin uninstall tram@tram
```

본체 제거 후에도 프로젝트 문서와 기록은 남는다. marketplace도 지우려면 호스트의 marketplace 관리 명령에서 등록을 제거한다.

## 기존 tram-local에서 전환

개발용 marketplace 이름 `tram-local`은 공개 이름 `tram`으로 바뀌었다. 패키지 이름은 `tram`이다. 프로젝트 기록은 유지하고 기존 플러그인과 공개 플러그인을 중복 활성화하지 않는다.

Codex에서는 기존 설치를 사용 중인지 먼저 확인하고 해당할 때만 제거한다.

```bash
codex plugin list
codex plugin remove tram@tram-local
codex plugin marketplace remove tram-local
codex plugin marketplace add taewooyo/tram
codex plugin add tram@tram
```

Claude Code에서는 기존 `tram@tram-local`을 `/plugin uninstall`로 제거하고, `/plugin marketplace remove tram-local` 후 위 공개 설치 절차를 따른다. 다른 프로젝트에서 이전 설치를 참조하고 있다면 함께 확인한다. 원래 설치가 없는 경우 제거 명령은 생략한다.

업데이트 전 schema 호환과 backup을 확인한다. 개발용 schema 1→2와 2→1 복귀는 자동 실행하지 않으며 [운영 안내](operations.md)의 명시적 preview/apply·digest 절차를 따른다.

## 로컬 소스로 시험하기

기여자와 공개 전 검증용 경로다. 저장소 루트에서 패키지를 생성한다.

```bash
python3 scripts/build.py
```

Codex:

```bash
codex plugin marketplace add "/path/to/tram"
codex plugin add tram@tram
```

Claude Code 터미널:

```bash
claude plugin marketplace add "/path/to/tram"
claude plugin install tram@tram
```

`/path/to/tram`은 실제 경로로 바꾼다. 이미 같은 이름의 Git marketplace를 사용한다면 별도 테스트 설정에서 확인하거나 기존 등록을 먼저 관리한다. 설치 cache를 직접 고치지 않는다.

### 로컬 후보 갱신

로컬 경로로 등록했다면 저장소에서 다시 빌드한 뒤 호스트의 플러그인 갱신·재설치를 사용하고 새 세션에서 변경 내용을 확인한다. Codex의 `marketplace upgrade`는 Git 등록용이므로 로컬 등록에서는 `not configured as a Git marketplace` 오류가 날 수 있다.

manifest의 `source: local`·`./build/codex`와 Claude의 `./build/claude`는 marketplace 저장소 안의 패키지 위치다. GitHub에서 등록해도 상대 경로를 사용하며 사용자는 빌드하지 않는다.

현재 후보와 설치 cache를 읽기 전용으로 비교하려면 소스 저장소에서 실제 패키지 경로와 host를 지정한다.

```bash
python3 scripts/build.py --identity --host codex
python3 scripts/build.py --identity --host codex --compare-package "/path/to/installed/package"
python3 scripts/build.py --identity --host claude --compare-package "/path/to/installed/package"
```

버전·schema·tree hash와 상대 경로별 누락·변경·추가를 확인한다. 같은 버전만으로 파일 동일성·호스트 동작 성공을 주장하지 않는다. 훅 trust는 각 호스트 절차로 설정하고 작업용 `.codex` 훅과 설치본을 중복 활성화하지 않는다. 개발 환경은 [기여 안내](../CONTRIBUTING.md)를 참조한다.
