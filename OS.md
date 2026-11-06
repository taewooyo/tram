# Tram — 개발 OS 청사진

Tram은 여러 프로젝트와 개발 에이전트에서 같은 승인·구현·검증 흐름을 사용하는 개인 개발 하네스다. 실행 규칙은 [flow-rules](src/context/flow-rules.md), 문서 규칙은 [doc-conventions](src/context/doc-conventions.md)가 단일 출처다.

## 시작과 재개

`init`은 프로젝트를 조사·연결한다. `start <요청>`은 위험도에 맞춰 작업을 시작·재개하며 기존 feature의 라우팅 역할을 흡수한다. `status`는 단계·승인 유효성·검증·제한·다음 행동을 조회한다. 여러 작업이 있으면 slug를 선택한다. 조회는 로그·marker·잠금도 쓰지 않는다.

에이전트는 대화·조사·스킬 호출을, runtime은 상태 전이 검사와 검증 증거 수집을 맡는다. `start`는 질문 전에 프로젝트 코드·문서·기존 domain 지식과 작업 공간 상태를 조사하고, 확인할 수 없는 결정만 묻는다. 필요하면 질문은 남지만 조사와 질문이 반복되지 않도록 근거를 전달한다. 사용자 진입은 `init/start/status --project PATH [--slug SLUG]`, 내부 연결은 `approve/transition/verify-run/review`다. 실제 인자는 [설치 안내](docs/setup.md)를 따른다.

## 기능 개발 흐름

```text
init → start → 프로젝트·지식 조사 → 결정이 필요한 질문
             → ① PRD 작성·사람 확정 → ② Plan 설계·사람 승인
             → ③ 구현·지식 반영 ⇄ 검증 → ④ commit → push → PR → 리뷰 → merge
status: 단계·승인·증거 조회 / start: 선택한 작업 재개
```

명령을 세 개로 줄여도 두 사람 게이트는 유지한다. 승인 응답 뒤 다음 역할로 이어가되 다음 승인 정류장에서 멈춘다. 문서 존재는 승인 증거가 아니다. 승인 기록은 최종 문서 digest와 연결하며 PRD 변경은 Plan 승인·후속 검증을, Plan 변경은 구현 승인을 무효화한다. hash는 사용자 신원 인증이 아니다.

사용자가 단계 명령을 반복 입력할 필요 없이 start가 다음 역할로 연결한다. 문맥 전달·재개·full·quick·coverage·perf의 Task 구성·완료 보고는 [시작·재개 경험](src/context/start-experience.md)을, 질문 전 조사·domain 재사용·작업 공간 보존·지식 기록은 [프로젝트 경험 규칙](src/context/project-experience.md)을 따른다. Task는 실행 목록이며 별도 승인 단계나 runtime 상태 체계를 만들지 않는다. 전체 18개 스킬과 전문 스킬 직접 호출에서도 메인 하나가 사용자 대화·질문·승인·위험 판단·배정·결과 통합·runtime 제어·최종 보고를 맡고, 작은 순차 저위험 조사·수정·light 테스트는 메인이 직접 수행할 수 있다. 필요한 병렬·고위험 작업은 근거를 남겨 위임하며 작업자는 재위임하지 않는다. 위임·직렬/병렬 판단·실행 참조·기록·재개·직접 수행 기준은 같은 카드의 단일 오케스트레이션 절이 정본이다. status는 메인이 읽기만 하고 배정이나 기록을 만들지 않는다.

prd는 무엇·왜를 수집·정제하고 선택적 interview는 같은 PRD 경로에 수집 씨앗을 만든다. plan은 기존 코드 재활용 조사부터 설계한다. impl은 구현을 제어하고 verify는 통과·구현결함·설계문제를 판정한다. 구현결함은 구현으로, 설계문제는 PRD 또는 Plan 검토로 돌아간다. 직접 단계 호출도 같은 전이 검사를 거친다.

verify-run은 선택한 프로젝트 검증 명령을 직접 실행한다. 검증 뒤 코드·문서가 달라지면 낡은 증거로 완료할 수 없다. full은 독립 reviewer가 필요하며 자체 검토로 대체하지 않는다. 독립 재채점·min-gate·예산·막힘 가드의 상세는 [impl](src/skills/impl/SKILL.md)·[verify](src/skills/verify/SKILL.md)·[루브릭](src/context/review-rubric.md)을 따른다. complete는 구현·검증 완료이며 원격 마무리는 별도다.

프로젝트별 선택형 관찰 도구는 현재 요청과 변경 범위에 맞는 검사·정책 후보와 선언 결과의 한계를 설명한다. 기존 필수 검사·승인·독립 검토·완료 판정은 유지하며 플랫폼별 도구는 기존 프로젝트 명령에 연결한다. 시작·재개·조회 연결은 [작업별 검증과 정책 관찰](src/context/start-experience.md#작업별-검증과-정책-관찰), 정확한 입력과 읽기·쓰기 경계는 [관찰 계약](src/context/runtime-contract.md#선택형-하네스-관찰-계약)을 따른다.

## 전문 경로와 받침 도구

- quick: 작은 저위험 변경, 위험 감별·동작 변경 테스트·verify light. 커지면 풀 흐름으로 돌아간다.
- coverage: 테스트 전용 반복, 명시적 adapter·Git 조건·독립 검토·예산을 유지한다. 신규 프로젝트는 미설정이다.
- perf-loop: 동작 보존 성능 개선, 재현 측정·정확성·6차원 평가·되돌림·예산을 유지한다.
- domain·retro: 도메인 지식과 협업 개선. diagram·skill-stat: 설명 자산과 관측.
- commit·push·pr: 별도 마무리 역할. 실행은 사용자의 작업 범위와 권한을 따른다.

상세 계약은 [src/skills](src/skills)를 참조한다. 컨텍스트는 얇은 색인으로 연결하고 재활용을 우선한다. 구현과 함께 판단 근거를 설명한다.

## 정본·배포본·프로젝트 기록

| 경계 | 위치와 역할 |
|---|---|
| 공통 정본 | src/skills·src/context·src/agents/reviewer.md·runtime·hooks·scripts·templates |
| 에이전트 연결 | platform/{codex,claude}의 adapter·manifest·hooks |
| 생성 배포본 | build/{codex,claude}의 자체 완결 패키지; 직접 편집 금지 |
| 작업용 생성 뷰 | .codex/는 inventory에 기록된 경로를 동기화; 목록 밖 legacy 파일은 보존 |
| 대상 프로젝트 | .tram/project.json·installation.json·tasks/<slug>.json·선택형 harness.json·.tram/local/와 프로젝트 문서 |

plugin root와 project root는 분리한다. 프로젝트 기록에 cache 절대 경로를 저장하지 않는다. AGENTS.md·CLAUDE.md는 관리 block만 연결하며 사용자 본문·수정·손상 block을 보존한다. 설치·업데이트·본체 제거는 native plugin manager를 사용한다. 프로젝트 unlink 후 .tram/·문서·로컬 로그 제외 규칙을 보존한다.

Codex는 fresh generic spawn으로 공통 reviewer 지시를 전달하고 Claude는 plugin agents/에 연결한다. 훅 부재 시 카드 직접 읽기·사전 검사를 사용하며 자동 주입·차단과의 차이를 공개한다. Grok은 미래 확장 대상이며 작동 지원을 선언하지 않는다. [지원표](docs/support.md)와 [릴리스 검증 기록](docs/release-validation.md)에 조건과 실제 증거를 구분한다.
