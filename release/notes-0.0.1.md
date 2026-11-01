# Tram 0.0.1 — 공개 alpha 릴리스 초안

> 게시 전 초안. GitHub Release·태그·공개 설치 성공을 뜻하지 않는다.

Tram은 요구사항과 계획을 승인하면 구현·검증·재개까지 이어가는 개발 하네스 플러그인이다. Codex와 Claude Code용 패키지를 같은 저장소에서 제공한다.

## 포함 기능

- 프로젝트 환경·검증 명령 연결, 새 작업 시작과 상태 조회·재개.
- 요구사항(PRD) 확정·계획(Plan) 승인과 변경 감지.
- 실제 검사 증거와 full 독립 검토를 이용한 구현·검증 흐름.
- 작은 수정·커버리지·성능 개선·프로젝트 지식 기록 등 전문 스킬.

## 설치

[README](../README.md#install)의 Codex·Claude Code별 설치·업데이트 방법을 따른다. 사용자 빌드는 필요하지 않으며 각 호스트와 Python 3.10+, 대상 프로젝트의 도구가 필요하다.

## 제한과 검증

schema 2를 사용한다. 개발용 schema 1 기록은 명시적 migration이 필요하다. 자동 회귀와 실제 호스트 검증의 범위·미실행 항목은 [검증 기록](../docs/release-validation.md)과 [지원 조건](../docs/support.md)을 따른다. 훅 자동 실행은 호스트·도구 이벤트·신뢰 설정 조건을 따른다.

## 라이선스와 피드백

Apache-2.0. 질문·오류는 [Issues](https://github.com/taewooyo/tram/issues), 보안 문제는 [비공개 제보](https://github.com/taewooyo/tram/security/advisories/new)를 사용한다.
