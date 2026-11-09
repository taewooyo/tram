# Tram 문서

처음 사용하는 경우 설치 안내에서 프로젝트 연결을 마친 뒤 start로 작업을 요청합니다. 최초 공개 후보는 기존 구현 기능을 포함한 `0.0.1/schema 2`이며, 과거 개발용 PRD·Plan과 CHANGELOG 이력만 초기화했습니다. 기능의 기준은 코드·테스트와 설치된 스킬입니다.

| 목적 | 문서 |
| --- | --- |
| 설치·프로젝트 연결·업데이트 | [설치 안내](setup.md) |
| 현재 지원 환경과 제한 | [지원 조건](support.md) |
| 막힌 이유 확인·진단·복구 | [운영 안내](operations.md) |
| 실제로 확인한 결과 | [검증 현황](release-validation.md) |
| 기능 흐름·설계 원칙 | [개발 흐름](../OS.md) |
| README·웹·향후 앱의 브랜드 아이콘 | [브랜드 자산](../src/brand/README.md) |

## 그림으로 보기

| 내용 | HTML | PNG |
| --- | --- | --- |
| 전체 흐름 | [HTML](diagrams/os-flow.html) | [PNG](diagrams/os-flow.png) |
| 시작·승인·구현·검증 | [HTML](diagrams/feature-flow.html) | [PNG](diagrams/feature-flow.png) |
| 역할과 책임 | [HTML](diagrams/os-flow-roles.html) | [PNG](diagrams/os-flow-roles.png) |
| 스킬 목록 | [HTML](diagrams/os-skill-catalog.html) | [PNG](diagrams/os-skill-catalog.png) |
| 스킬 관계 | [HTML](diagrams/os-skill-map.html) | [PNG](diagrams/os-skill-map.png) |
| 컨텍스트 연결 | [HTML](diagrams/context-system.html) | [PNG](diagrams/context-system.png) |
| 에이전트 역할 | [HTML](diagrams/subagent-map.html) | [PNG](diagrams/subagent-map.png) |
| 커버리지 개선 | [HTML](diagrams/coverage-loop.html) | [PNG](diagrams/coverage-loop.png) |
| 성능 개선 | [HTML](diagrams/perf-loop.html) | [PNG](diagrams/perf-loop.png) |

현재 후보는 0.0.1/schema 2입니다. 2026-11-08 기준 Codex CLI의 로컬 설치·목록 조회와 현재 대화의 선택형 질문 UI는 확인했지만, 공개 Git 설치와 전체 호스트 lifecycle은 검증되지 않았습니다. 확인 범위와 미검증 항목은 [검증 현황](release-validation.md)에서 구분합니다.
