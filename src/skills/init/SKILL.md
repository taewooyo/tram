---
name: init
description: Tram을 명시한 프로젝트에 연결하고 스택·검증 후보·컨벤션을 조사한다. 본체 설치는 native plugin manager를 사용한다.
---

실행 주체는 [단일 오케스트레이션 계약](../../context/start-experience.md)의 직접 수행·위임 기준을 따른다. 아래 작업자 절차는 위임 시 적용하며 각 경로의 독립 검토·안전판은 유지한다.


# 프로젝트 연결

현재 스킬 파일의 `../..`를 plugin root로 해석하고 `<plugin-root>/adapter.md`, [공통 실행 계약](../../context/runtime-contract.md), [단일 오케스트레이션 계약](../../context/start-experience.md), [프로젝트 경험 규칙](../../context/project-experience.md)을 읽는다. 메인이 대상 프로젝트의 실제 경로를 확인하고 조사 작업자를 배정한다. 작업자는 가능하면 `python3 "<plugin-root>/scripts/project-context.py" workspace --project "<target>"`로 Git·dirty·unborn 상태를 확인한다. init은 프로젝트 파일을 변경할 수 있으므로 기존 설정과 충돌하는 변경을 보존한다.

메인이 `python3 "<plugin-root>/runtime/tram.py" init --project "<target>"`을 실행한다. 조사 작업자는 스택·검증 후보·컨벤션을 실제 소스와 설정에 대조해 후보 델타와 근거를 반환한다. 메인이 프로필을 선택하고 근거로 확정할 수 없는 선택만 질문한다. 후보 발견을 명령 실행 권한으로 간주하지 않는다. 기존 사용자 설정과 관리 block 충돌은 보존하고 해결 사항을 보고한다.

프로필의 `schema_version`·revision은 runtime이 관리한다. 작업자가 발견한 명령 후보를 프로젝트 파일·기존 설정과 대조하고 메인이 현재 사용자 요청의 실행 범위에서 확정한다. 선택한 명령은 `id`, `argv`, 프로젝트 상대 `cwd`, `confirmed: true`, `required`를 가진다. 실제 소스·테스트·빌드·의존성 파일은 `inputs`, 생성 출력은 `exclude`에 명시한다. 독립 reviewer를 실행할 수 있을 때만 `reviewer.configured: true`로 설정한다. 작업자는 후보만 반환하며 configure·사용자 질문을 수행하지 않는다. 메인이 확정한 델타 JSON을 대상 `.tram/local/`에 저장하고 `python3 "<plugin-root>/runtime/tram.py" configure --project "<target>" --file "<target>/.tram/local/profile-selection.json"`으로 적용한다. configure 델타에 `schema_version`·revision을 넣거나 프로젝트 JSON을 수동 덮어쓰지 않는다. 미확정 명령·reviewer는 완료 전 필요한 준비 사항으로 남긴다.

환경·검증 명령 연결 뒤 선택형 프로젝트 지식 조사를 안내한다. 생략하면 기존 연결 결과로 도입을 완료하며 다른 스킬의 필수 조건을 추가하지 않는다. 선택하면 [프로젝트 경험 규칙의 도입 조사](../../context/project-experience.md#선택형-프로젝트-도입-조사)를 적용해 기존 코드·문서·지침부터 조사하고 사실·정책·불확실성·사람 결정을 구분한다. 구체적인 대상 경로·내용·이유·근거를 사용자가 검토하기 전 문서를 쓰지 않는다. 조사 동의를 쓰기 승인으로 확대하지 않는다.

연결 결과와 미확정 설정·기능별 제한을 설명하고 작업 요청은 [start](../start/SKILL.md)로 이어간다. Git 초기화·원격 생성·전역 설정 변경은 하지 않는다.

연결·설정 결과 뒤 [준비 상태와 문제 해결 안내](../../context/start-experience.md#준비-상태와-문제-해결-안내)에 따라 doctor를 보조 조회하고 남은 문제와 다음 행동을 설명한다. 연결 실패 시 원래 오류를 보존하며 진단으로 자동 재시도·복구하지 않는다.

프로젝트 연결은 `init`, 새 작업·재개는 `start`, 현재 작업의 작고 저위험한 변경은 `quick`으로 안내한다. 선택형 Git worktree는 연결을 대체하지 않으며 `start`에서 선택할 수 있다.
