# Tram 지원 조건

`0.0.1/schema 2` 후보의 실행 조건과 확인 범위를 안내한다. Codex·Claude Code용 공개 alpha를 준비 중이며 공개 릴리스는 아직 하지 않았다. 실제 증거는 [검증 기록](release-validation.md)을 따른다.

## 호스트별 확인 범위

| 대상 | 확인한 범위 | 남은 확인 |
|---|---|---|
| Codex | 실제 CLI 0.166.0의 격리 로컬 marketplace 등록·설치·제거·재설치와 파일별 동일성 확인; 이전 CLI 일부 대화·자동 패키지 회귀 | 공개 Git 설치·Desktop UI·전체 작업 및 재개 lifecycle |
| Claude Code | 실제 CLI 2.1.92의 manifest 검사·격리 로컬 marketplace 등록·설치·제거·재설치와 파일별 동일성 확인; 패키지·fixture 검사 | 로그인된 실제 작업·승인·재개와 공개 Git 설치·업데이트 |
| Linux | 자동 검사 대상 | 실제 native 호스트 결과 |
| Windows/WSL·Grok | 지원 검증 없음 | 이번 alpha 범위 밖 |

사용자의 Android 프로젝트 연결·Gradle 성공 보고는 해당 관찰에 한정한다. Android 전체 기능 흐름·Kover·훅 검증으로 확대하지 않는다. 같은 버전 표시만으로 설치된 파일이 현재 후보와 같다고 판단하지 않는다. `release.json`의 `validationTargets`는 목표이며 `validatedHosts`만 수집한 호스트 증거 목록이다.

Codex에서는 설치된 Tram의 `init`·`start`·`status` 스킬을 명시해 요청한다. Claude Code 연결부의 호출 표기는 `/tram:init`, `/tram:start`, `/tram:status`다. 단축 입력 구문은 호스트에서 확인해야 한다. 설치와 갱신은 [설치 안내](setup.md)를 따른다.

실제 CLI 기록 형식과 검증 도구의 지원 형식은 별개다. 현재 native lifecycle 검증기는 `collab_tool_call`의 부모·자식 UUID spawn/wait와 연결된 reviewer 명령 이벤트 스트림을 요구한다. 작업 이름만 반환하는 spawn 결과 및 `session_meta`·`response_item` rollout 기록은 해당 증거 어댑터에서 미지원으로 진단한다. 로컬 기록에 부모 메타데이터나 runtime 리뷰가 있어도 이 연결 검사를 대신하지 않으며, 전체 native lifecycle 통과로 확대하지 않는다.

## 기능별 실행 조건

| 기능 | 조건과 제한 |
|---|---|
| runtime/core | Python 3.10+ 표준 라이브러리; Git·Bash·jq는 core 필수가 아님 |
| 하네스 관찰 | Python 3.10+ 표준 라이브러리; 기존 command ID를 참조하는 선택형 observe 설정. 추천·정책 후보·caller_reported 결과 해석이며 기존 필수 검사·완료 판정을 변경하지 않음 |
| full 검증 | 매 라운드 새 독립 reviewer의 실제 검증과 대조; 독립 실행이 없으면 완료 보류 |
| 자동 컨텍스트 주입·차단 | Bash·jq·호스트 훅·trust 필요; 없으면 카드 직접 읽기·사전 검사로 차이를 설명 |
| quick | 작은 저위험 변경·위험 감별·동작 변경 테스트·light 검증 |
| coverage | Git·깨끗한 비기본 브랜치·명시적 adapter·독립 검토·예산 |
| Python coverage | 선택한 Python의 pytest·pytest-cov; 신규 프로젝트는 미설정 |
| Kover | Java·Gradle wrapper·JVM task·XML·testPaths; 기기 계측·iOS/JS/Native 제외 |
| perf-loop | 재현 벤치마크·출력 동일성·평가·되돌림·예산 |
| commit/push/pr | Git·필요 시 gh 인증과 프로젝트 PR 템플릿 |
| diagram | Bash·Chrome/Chromium; Mermaid는 Node/npx 추가 |

현재 Codex·Claude 등록 파일의 도구 matcher는 PR·push 검사에 `Bash`, 스킬 통계에 `Skill`, 편집 주입에 `Edit|Write|MultiEdit`를 사용한다. 훅 스크립트가 patch 입력을 해석할 수 있어도 등록 matcher와 실제 호스트 이벤트가 연결되어야 자동 실행된다. Codex의 `exec_command`·`apply_patch`나 자연어 스킬 요청에서 자동 주입·차단·통계 기록을 보장하지 않는다. 훅이 실행되지 않으면 에이전트가 카드를 직접 읽고 PR·push 사전 검사를 수행한다.

사용 통계는 관측된 `Skill` 이벤트와 `/명령`·`$명령`으로 시작하는 입력만 집계한다. 자연어 요청을 포함한 전체 사용 횟수가 아니다.

훅의 PR·push 검사는 지원한 호출 형태에 적용되며 모든 shell 표현을 포괄하지 않는다. 전문 스킬의 승인·위험·예산 조건은 직접 호출에도 유지한다. 프로젝트 정책은 `.tram/project.json`에 연결한다.

## 운영 중 막힐 때

하네스 관찰은 Android·웹·서버 등 플랫폼별 도구를 내장하지 않고 프로젝트에 등록한 검사에 연결한다. `.tram/harness.json` 부재는 기존 작업의 차단 사유가 아니며 read-only 조회도 계속 사용할 수 있다. 키워드 검색은 형태소·의미 검색이나 정책의 현재 유효성을 보장하지 않는다. 선언된 검사 범위와 reported_pass는 실제 실행 증거와 별도로 표시한다. 설정·기록·오류 해석은 [관찰 운영 안내](operations.md#작업별-검사정책-관찰)를 따른다. CLI·fixture·정적 계약 통과와 실제 호스트 전체 흐름 검증은 구분한다.

프로세스 관찰 권한이 부족하면 `PROCESS_OBSERVATION_FAILED`, 종료 확인이 불가능하면 `PROCESS_CLEANUP_FAILED`로 검증·완료를 보류한다. 테스트 assertion 실패와 실행 환경의 제약을 구분하고, 승인된 실행 환경에서 다시 검증한다. 무관한 잠금·프로세스 삭제나 자동 권한 상승으로 우회하지 않는다.

프로젝트 schema와 설치 패키지 버전은 별개다. schema 1은 명시적 migration 전 일반 쓰기가 차단된다. [운영·복구 안내](operations.md)에서 진단·backup·복귀 절차를 확인한다. 라이선스는 Apache-2.0이며 보안 문제는 GitHub 비공개 취약점 제보를 사용한다. 실제 호스트 검증과 공개 게시 상태는 별도 확인한다. 제보 시 [기여 안내](../CONTRIBUTING.md)와 [보안 안내](../SECURITY.md)를 따른다.
