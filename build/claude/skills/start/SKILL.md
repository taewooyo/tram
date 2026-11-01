---
name: start
description: Tram 작업을 위험도에 맞게 시작하거나 재개하고 PRD·Plan 승인 정류장을 거쳐 구현·검증으로 연결한다.
---

실행 주체는 [단일 오케스트레이션 계약](../../context/start-experience.md)의 직접 수행·위임 기준을 따른다. 아래 작업자 절차는 위임 시 적용하며 각 경로의 독립 검토·안전판은 유지한다.


# 작업 시작·재개

현재 스킬 파일의 `../..`를 plugin root로 해석하고 `<plugin-root>/adapter.md`, [공통 실행 계약](../../context/runtime-contract.md), [작업 시작·재개의 사용자 경험](../../context/start-experience.md), [프로젝트 경험](../../context/project-experience.md)을 읽는다. 대상 프로젝트와 작업 slug를 식별한다. 여러 작업 중 최신 작업을 임의 선택하지 않는다.

1. 사용자 요청·현재 대화·기존 기록에서 project·slug를 먼저 확인한다. 인자가 없어도 확인한 사실을 재질문하지 않는다. 대상이 유일하지 않으면 후보와 상태를 보여주고 선택 전 실행하지 않는다. 메인은 대상 선택과 runtime 조회를 맡는다. 조사 작업자는 코드를 조사하거나 init/PRD 산출물을 쓰기 전에 `python3 "<plugin-root>/scripts/project-context.py" workspace --project "<target>"`로 현재 브랜치·HEAD와 기존 변경을 먼저 확인한다. 대상 경로가 정해졌으면 `--path`를 전달해 충돌 범위만 살펴본다. 조사 결과를 받은 메인은 runtime status로 `effective_phase`·`next_action`·`approvals_valid`·차단 이유와 현재 문서·기록을 대조한다. 미연결이면 [init](../init/SKILL.md)을 먼저 수행한다.

사용자가 기존 작업 디렉터리와 분리해 일하고 싶다고 하면 현재 작업공간을 기본으로 유지할지 선택형 Git worktree를 쓸지 먼저 확인한다. 기본값은 현재 작업공간이다. 격리는 `python3 "<plugin-root>/scripts/worktree.py" create --project "<원본 경로>" --path "<절대 worktree 경로>" --branch "<새 branch>"`를 사용한다. 유효한 branch와 committed HEAD가 필요하며 선택한 commit의 tracked 파일만 새 경로에 둔다. 원본의 dirty·untracked·ignored 변경은 그대로 원본에 남는다. `.tram`도 선택한 commit에 tracked된 파일은 자연스럽게 포함될 수 있고, 미커밋·untracked·ignored 데이터는 옮기지 않으며 별도 migration하지 않는다. 생성 결과의 `tram_state`에서 project config·task records·installation·local 경로 존재 여부를 확인한다. 결과를 받은 뒤 worktree 경로를 project root로 새 task를 시작하거나 명시 `init`을 선택한다. 승인된 PRD·Plan/task 기록을 새 경로에서 자동 재개한다고 약속하지 않는다.

기존 linked worktree는 `list`로 확인하고 새 세션에서는 사용자가 해당 경로를 다시 열거나 `--project`로 지정해야 한다. 경로 연결은 세션 간 저장하지 않는다. 현재 worktree에서 원본으로 돌아가는 경로는 `disconnect --project "<현재 경로>" --to "<사용자가 선택한 원본 경로>"`처럼 사용자가 지정한다. 이 전환은 삭제가 아니다. 통합은 작업 종료 후 사용자가 방법을 고르게 한다. `suggest-merge --project "<원본 경로>" --source "<worktree 경로>" --expected-branch "<현재 branch>" --expected-head "<현재 HEAD>"`는 원본의 tracked/untracked 변경·충돌·ignored 경로를 검사한 뒤 clean 상태에서만 로컬 merge 명령을 제안하며 실행하지 않는다. expected 값은 직전 workspace 관측에서 가져온다. 검사는 동시 편집을 차단하지 않으므로 사용자가 실제 실행 직전에 상태를 재확인해야 한다. `remove`는 명시 요청에만 사용하며 변경·untracked·ignored 파일이 있으면 삭제하지 않는다. stash/reset/checkout/force-remove, 자동 복사·merge·push를 하지 않는다. non-Git·unborn·detached HEAD·branch/경로 충돌·Git 오류에서는 격리를 제공하지 않고 현재 경로를 유지한다.
2. 새 작업은 메인이 조사 근거를 통합해 위험 감별 후 `start --project "<target>" --slug "<slug>" --route full|quick|coverage|perf`로 시작한다. 새 기능·고위험·설계 필요·불명확한 작업은 full, 작고 저위험한 변경은 quick, 테스트 전용 개선은 coverage, 동작 보존 성능 개선은 perf다.
3. 재개 작업도 명시한 동일 slug로 `start`를 실행하여 기존 runtime의 정합화 결과를 확인한다. 승인·완료 이력을 보존하며 공통 사용자 경험 카드의 phase/next_action 표에 따라 현재 역할을 실행한다. 요청 경로의 domain 후보는 조사 작업자가 `project-context.py knowledge --project "<target>" --path "<관련 경로>"`로 확인하고 필요한 코드·문서와 업무 지침을 읽어 근거·질문 후보를 메인에 반환한다. 조사 작업자는 HEAD가 없고 수정 전 구분이 필요하면 승인된 Plan의 변경 경로만 `capture --project "<target>" --slug "<slug>" --path "<file>"`로 기준선을 남긴다. 기록 저장이 불가능하면 한계를 말하고 기존 기록을 덮어쓰지 않는다. 메인이 full의 [prd](../prd/SKILL.md) → [plan](../plan/SKILL.md) → [impl](../impl/SKILL.md) → [verify](../verify/SKILL.md) 지침을 읽어 단계별로 배정한다. 전문 스킬에 project·slug·요청·route·읽은 기록과 runtime 상태, start에서 진입한 흐름임을 전달한다. 예외는 [quick](../quick/SKILL.md)·[coverage](../coverage/SKILL.md)·[perf-loop](../perf-loop/SKILL.md)의 진입 조건을 따른다.

전체 단계와 전문 경로는 공통 사용자 경험 카드의 단일 오케스트레이션 절을 따른다. 메인이 각 스킬의 전체 흐름을 읽고 조사·작성·구현·검증 단계를 직접 배정하며 작업자에게 스킬 전체의 진행 제어를 넘기지 않는다. full·quick·coverage·perf의 기존 Task와 실제 실행 상태를 대조해 재개하고 사람 게이트·전문 안전판을 유지한다. 별도 단계 명령 없이 메인이 다음 역할로 연결한다.

각 역할 전환은 runtime의 `transition --action` 검사를 통과해야 한다. PRD 확정·Plan 승인 때는 사람이 문서를 검토하도록 멈추며 명시적 응답 후 `approve --scope prd|plan --quote TEXT --session REF`를 기록한다. 저장 성공과 새 status를 확인한 뒤 PRD 승인은 plan 스킬, Plan 승인은 impl 스킬을 읽고 실행한다. 별도 단계 명령을 요구하지 않는다. 승인 기록이 없거나 digest가 달라지면 필요한 검토로 돌아가며 해당 구현을 보류한다. 구현결함은 구현으로, 설계문제는 PRD/Plan 검토로 돌아가며 기존 예산·막힘 안전판을 유지한다.

`effective_phase=complete`·`next_action=finishing`이면 [worktree 마무리와 재개](../../context/start-experience.md#worktree-마무리와-재개)를 적용한다. 지정된 project·slug의 Task 마무리 메모를 읽고 `finish-status --project "<source 경로>"`에 확인된 target만 `--target`으로 전달해 현재 상태를 재관측한다. merge·PR·그대로 두기의 상태·이유·다음 행동을 제시하고 기존 commit/push/pr·worktree 절차로 연결한다. 과거 메모나 선택은 현재 상태·실행 권한이 아니며 status 조회에서는 메모를 쓰지 않는다. 기록 불가이면 재개 경로와 남은 행동을 대화에 남긴다.

완료는 유효한 테스트·필수 독립 검토 증거가 있을 때만 기록한다. 커밋·push·PR은 별도 마무리 요청과 각 스킬 계약에 따른다. 상태와 미검증 항목·다음 행동을 보고한다.

기존 전이 검사에서 막혔을 때는 [준비 상태와 문제 해결 안내](../../context/start-experience.md#준비-상태와-문제-해결-안내)에 따라 doctor를 보조 조회한다. 원래 차단 이유를 보존하고 관련 문제와 먼저 할 행동을 설명한다. 정상 흐름에 필수 진단 게이트를 추가하지 않으며 작업별 승인·검증 차단은 status가 정본이다.
