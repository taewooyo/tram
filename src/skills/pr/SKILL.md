---
name: pr
description: 현재 브랜치의 커밋들을 분석해 "무엇이 왜 바뀌었는지"를 LLM이 종합한 PR 제목·본문을 만들고, 사람 확인 후 gh로 PR을 연다. OS.md 흐름의 ④ 마무리(/commit·/push 다음). 본문은 .github/pull_request_template.md 틀을 따른다(PreToolUse 훅이 강제). 사용자가 "PR 올려줘", "PR 만들어줘", "리뷰 요청", "/pr"이라고 할 때 사용한다.
user-invocable: true
---


실행 주체는 [단일 오케스트레이션 계약](../../context/start-experience.md)의 직접 수행·위임 기준을 따른다. 아래 작업자 절차는 위임 시 적용하며 각 경로의 독립 검토·안전판은 유지한다.

## 실행 경계

현재 스킬 파일의 `../..`를 plugin root로 해석하고 `<plugin-root>/adapter.md`와 [공통 실행 계약](../../context/runtime-contract.md)을 먼저 읽는다. 대상 프로젝트는 사용자 지정 경로로 명시하며 plugin root와 혼동하지 않는다. 문서·명령의 상대 경로와 셸 cwd는 대상 프로젝트 기준이다. `<plugin-root>` 표기는 해석한 실제 경로로 치환하고 셸 경로는 인용한다. Native 도구·독립 검토 호출은 adapter를 따른다.


## 실행 역할

[단일 오케스트레이션 계약](../../context/start-experience.md)을 따른다. 메인은 이 스킬 전체 흐름을 읽고 직접 수행 또는 단계 배정을 선택하며 작업자는 사용자 질문·승인/전이·Task 갱신·재위임을 하지 않는다. 작업자가 전체 커밋·diff 분석과 템플릿 제목·본문을 준비하고 메인이 repo·HEAD·head/base·중복 여부·사람 게이트를 확인한다. 작업자는 확정 repo·인자와 --body-file 및 사전 검사를 사용해 허용된 gh 실행만 수행한다. 위임은 새 외부 권한을 주거나 샌드박스를 우회하지 않는다.

# /pr — 커밋 분석 → PR 생성 (④ 마무리)

푸시된 브랜치의 **커밋들을 모아 LLM이 PR 제목·본문을 종합 생성**하고, **사람 확인 후** `gh`로 PR을 연다.
본문은 대상 프로젝트의 `.github/pull_request_template.md`, 없으면 [제공 기본 템플릿](../../templates/pull_request_template.md)의 틀을 따른다
(`## 요약` / `## 개발 흐름` / `## 변경 내용` / `## 테스트` / `## 관련`). 이 틀은 **PreToolUse 훅이 강제**하므로,
섹션이 빠지면 `gh pr create`가 차단된다.

> 외부 공개 작업이다. 되돌리기 어려우니 **사람 확인 전에는 PR을 만들지 않는다.**

전달된 인자: `$pr` 뒤의 사용자 메시지.
- 있으면 → PR 제목 힌트/강조점으로 사용. 없으면 커밋들에서 알아서 종합.

---

## 진행 순서

### [준비] 사전 점검 (하나라도 막히면 멈추고 안내)

작업자가 아래 repo·base·branch·HEAD·원격·인증·중복 정보를 조사해 메인에 반환하고 메인이 대상을 확정한다.

```bash
# 대상 저장소: 내 fork(origin). gh는 remote가 여럿이면 upstream을 고르므로 --repo 로 강제한다.
repo=$(git remote get-url origin | sed -E 's#\.git$##; s#^.*[:/]([^/]+/[^/]+)$#\1#')
# base 브랜치: 설정값(nextstep.prbase) 우선 → origin 기본 브랜치 → main
base=$(git config --get nextstep.prbase 2>/dev/null || true)
[ -z "$base" ] && base=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's#.*/##')
base=${base:-main}
br=$(git branch --show-current)
```

> **fork·base 설정** — PR을 보낼 저장소·브랜치는 위처럼 결정한다. base 브랜치를 바꾸려면
> `git config nextstep.prbase <브랜치>` (예: 내 id 브랜치 `jshans40`). 대상 저장소는 항상 `origin`(내 fork)이며
> `--repo "$repo"` 로 박아 upstream으로 새지 않게 한다.

- **현재 브랜치가 base면** → "PR은 기능 브랜치에서 올리세요"라고 안내하고 멈춘다.
- **앞선 커밋이 없으면**(`git log "$base..HEAD" --oneline` 비어 있음) → "올릴 커밋이 없습니다" 멈춤.
- **원격에 안 올라갔거나 뒤처져 있으면**(로컬 HEAD가 `origin/$br`에 없음) → "먼저 `/push` 하세요" 안내.
- **gh 인증 안 됨**(`gh auth status` 실패) → 인증 안내하고 멈춤.
- **이미 열린 PR이 있으면**(`gh pr view --repo "$repo" "$br" --json url -q .url` 성공) → 그 URL 알리고 **새로 안 만든다**(중복 금지).

### 1. 변경 수집

작업자가 준비 단계에서 확정한 base·HEAD 기준 전체 커밋과 변경을 분석한다.

```bash
git log "$base..HEAD" --oneline          # 커밋 목록
git diff "$base...HEAD" --stat           # 파일별 변경 규모
```
필요하면 핵심 파일의 `git diff "$base...HEAD" -- <경로>`로 내용을 본다.
diff 규모와 관계없이 배정된 분석 작업자가 전체 변경 근거를 반환한다. 추가 표적 분석이 필요하면 메인이 직접 좁게 배정하며 작업자는 재위임하지 않는다.

### 2. 작업자의 PR 제목·본문 생성

- 작업자가 `.github/pull_request_template.md`를 읽어서 **그 틀에 맞춰** 채운다.
- **제목**: 핵심을 한 줄로(기존 커밋 접두사 스타일 참고: `feat :` 등).
- **본문**: 커밋 메시지·diffstat을 근거로 **"무엇이 왜 바뀌었나"를 종합**한다. *커밋 단순 나열 금지.*
  - `## 요약` 1~3줄 / `## 개발 흐름` **템플릿의 mermaid 블록을 그대로 유지(항상 포함, 훅이 강제 — GitHub가 다이어그램으로 렌더)** / `## 변경 내용` 주요 항목 / `## 테스트` 실제 검증 결과(예: pytest N/M, 모르면 "확인 필요") / `## 관련` 링크(선택).

### 3. 사람 확인 게이트 — ★멈춤★

메인이 생성한 **제목·본문 전체를 보여주고** PR을 만들지 확인한다. 이미 확보한 현재 repo·HEAD·base·본문에 대한 유효 권한은 다시 요청하지 않는다.

```
[PR 미리보기]
제목: ...
본문:
## 요약 ...
## 개발 흐름 ...
## 변경 내용 ...
## 테스트 ...
## 관련 ...

이대로 PR을 만들까요? (base: <base> ← <branch>) 고칠 점 있으면 알려주세요.
```

- 수정 요청하면 다듬어 다시 보여준다. **승인 전에는 `gh pr create`를 실행하지 않는다.**

### 4. PR 생성

메인이 승인과 repo·HEAD·head/base·중복을 최종 확인하면 작업자가 최종 본문을 대상 프로젝트의 `.tram/local/` 아래 파일에 쓰고 확정 인자와 `--body-file`로 전달한다. 실행 직전 HEAD·branch·대상·본문이 달라지면 중단해 메인에 반환한다. `.tram/local/` ignore가 보장되지 않으면 원문 기록 전에 충돌을 해결한다. 본문의 백틱·`$()`를 셸 문자열에 보간하지 않는다.

```bash
gh pr create --repo "$repo" --base "$base" --head "$br" --title "<제목>" --body-file "<target>/.tram/local/pr-body.md"
```

- 훅은 파일의 실제 본문을 선택한 프로젝트 템플릿(없으면 제공 기본 템플릿)과 대조한다. 훅 미지원 호출에서는 adapter의 명시적 사전 검사를 수행한다. 제공 기본 템플릿은 `## 요약`/`## 개발 흐름`/`## 변경 내용`/`## 테스트`와 mermaid 블록을 유지한다.
- 작업자가 실제 실행 결과·URL을 메인에 반환하고 메인이 생성된 **PR URL을 보고**한다.

---

## 수용 기준 (이 스킬이 제대로 동작하는지 검증)

- [ ] base가 아닌 기능 브랜치에서만, 푸시된 상태에서만 진행한다.
- [ ] 이미 열린 PR이 있으면 새로 만들지 않고 알린다.
- [ ] 커밋들을 근거로 **종합한** 제목·본문을 만든다(단순 나열 아님).
- [ ] 본문이 템플릿 틀(## 요약/## 개발 흐름[mermaid]/## 변경 내용/## 테스트)을 따른다.
- [ ] 사람 확인 게이트에서 멈추고, 승인 없이 PR을 만들지 않는다.
- [ ] 생성 후 PR URL을 보고한다.

---

## 안전 규칙

- **외부 공개 작업** — 사람 확인 없이 PR을 만들지 않는다.
- **base→base PR 금지, 중복 PR 금지.**
- 본문은 **반드시 템플릿 틀**을 따른다(훅이 강제).
- diff에 **비밀·토큰·`.env` 같은 민감정보**가 보이면 멈추고 알린다.
- `--force`나 PR close/merge 같은 동작은 이 스킬이 하지 않는다.
