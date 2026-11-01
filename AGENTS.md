Tram 개발 OS 청사진은 OS.md다. OS 구성 요소를 추가·수정하기 전에 읽고 실행 규칙은 src/context/flow-rules.md, 문서 규칙은 src/context/doc-conventions.md를 따른다.

공통 정본은 src/skills·src/context·src/runtime 등 src/ 아래다. platform/은 연결부이며 build/{codex,claude}는 생성 배포본이므로 직접 고치지 않는다. .codex/는 승인된 동기화를 마친 생성 작업용 뷰다. 정본 수정 후 scripts/build.py --local로 inventory에 기록된 생성 파일만 동기화하며, 목록 밖 legacy 파일은 보존한다. 프로젝트별 기록은 해당 프로젝트 .tram/에 둔다. 모든 작업 산출물은 저장소 안에 만든다.

새 기능·고위험·설계 작업은 PRD 확정·Plan 승인 후 구현한다. start가 단계를 연결하고 status는 읽기만 한다. 직접 단계 호출에도 승인 검사를 적용한다. 동작 변경에는 테스트를 함께 추가·갱신하고 기존 코드 재활용을 우선한다. PRD·Plan은 결정 스냅샷이므로 구현에 맞춰 본문을 덮어쓰지 않는다.

동시 작업에서는 맡은 파일만 수정하고 다른 작업자의 변경을 되돌리지 않는다. 설명 자산 변경은 실제 HTML 렌더와 PNG 직접 확인을 포함한다. 미실행 검증을 통과로 보고하지 않는다. AI와 협업하는 과정에서 판단 근거와 검증의 한계를 설명한다.
<!-- tram:begin -->
이 프로젝트는 설치된 Tram 플러그인의 개발 흐름을 사용합니다.
에이전트의 설치된 스킬 목록에서 Tram start/status 스킬을 찾아 SKILL.md를 읽으세요.
Claude Code에서는 /tram:start·/tram:status, Codex에서는 설치된 Tram start/status 스킬을 사용합니다.
스킬 파일 위치로 플러그인 root를 찾고 adapter.md·OS.md·context/flow-rules.md를 읽으세요.
프로젝트별 설정은 .tram/project.json, 작업 기록은 .tram/tasks/에 있습니다.
새 기능·고위험·설계 변경은 PRD 확정과 Plan 승인 후 구현하고, 동작 변경은 테스트와 함께 검증합니다.
<!-- tram:end -->
