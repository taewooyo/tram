# Claude Code 연결 규약

이 파일의 부모가 설치된 Tram 루트다. 프로젝트 루트는 별도로 확인한다.
사용자 진입은 `/tram:init`, `/tram:start`, `/tram:status`; 전문 스킬도 같은 namespace다.

- 스킬 실행: 호스트의 Skill 도구 또는 실제 제공된 스킬 실행 기능을 사용한다.
- 셸·편집: Bash·Read·Edit·Write 등 실제 제공된 도구를 사용한다. Codex 전용 도구명을 그대로 호출하지 않는다.
- 작업자 실행: 메인이 현재 host 도구 metadata에서 실제 생성·후속 배정·상태 조회·실행 참조 반환 기능을 확인해 사용한다. generic 작업자에게 공통 계약과 지정 단계·소유 파일·확정 명령·권한·반환 근거를 전달한다. 사용자 질문·승인/전이·Task 갱신·재위임을 금지하고, 종료·상태 확인 전 같은 파일에 중복 배정하지 않는다. 특정 도구명이나 지속 실행 기능이 항상 있다고 가정하지 않는다.
- 지원 제한: 필요한 생성·후속 배정·상태 확인 또는 실행 참조 기능이 없으면 지원 불가·부분 결과를 메인에 보고하고 해당 실행·완료를 보류한다. 작은 순차 저위험 작업·light 검증의 메인 직접 수행 및 full 독립 검증 경계는 설치 root의 `context/start-experience.md` 단일 오케스트레이션 계약을 따른다. 공통 스킬에는 host 도구명을 고정하지 않는다.
- 독립 검토: 메인이 매 라운드 `agents/reviewer.md`의 fresh reviewer를 실제 Agent/Task 기능으로 직접 생성하고 기준·대상·컨텍스트 카드를 명시한다. PRD·문서·자료 독립 검토는 지정 기준을 대조해 결과를 반환한다. runtime full 검증 라운드에서만 reviewer가 직접 `verify-run`·검사·판정을 수행하고 메인은 검산·등록한다. 검토자가 구현에 참여했으면 재사용하지 않는다.
- 훅은 `CLAUDE_PLUGIN_ROOT`의 네이티브 플러그인 등록만 사용한다. 전역 설정을 직접 수정하지 않는다.
- 설치/업데이트/제거는 Claude의 플러그인 관리 명령을 쓴다. 플러그인 제거와 프로젝트 `unlink`는 별개다. `.tram`과 작업 문서는 제거하지 않는다.

실행 예: `python3 "<Tram 루트>/runtime/tram.py" status --project "<프로젝트>"`.
스킬 파일 위치로부터 루트를 계산하며 Markdown 안의 환경변수 자동 치환을 가정하지 않는다.

공식 근거: [플러그인 규약](https://code.claude.com/docs/en/plugins-reference).
