---
name: status
description: Tram 작업 단계·승인 유효성·검증·제한·다음 행동을 쓰기 없이 조회한다.
---

# 진행 상태 조회

현재 스킬 파일의 `../..`를 plugin root로 해석하고 `<plugin-root>/adapter.md`와 [공통 실행 계약](../../context/runtime-contract.md)과 [작업 시작·재개의 사용자 경험](../../context/start-experience.md)을 읽는다. 대상 프로젝트를 명시한다.

메인이 직접 `python3 "<plugin-root>/runtime/tram.py" status --project "<target>"`를 실행한다. 특정 작업은 `--slug "<slug>"`를 붙인다. 여러 작업이 있으면 식별 가능한 목록을 보여주고 재개 대상을 임의로 정하지 않는다.

상태 조회 뒤 [준비 상태와 문제 해결 안내](../../context/start-experience.md#준비-상태와-문제-해결-안내)에 따라 doctor를 보조 조회하고 정상 범위 또는 막힌 이유·첫 행동을 설명한다. 상태 조회 실패 시에도 원래 오류를 보존한다. 작업별 승인·검증 판단은 status를 따른다.

`effective_phase`·`next_action`·`approvals_valid`·`blocked`·`completion_issues`를 함께 읽고 현재 단계·승인 누락/변경·검증의 유효성·지원 제한·다음 행동을 설명한다. 승인과 증거가 낡았으면 필요한 검토·재검증을 안내하며 이 조회에서 실행하지 않는다. 조회는 작업자 배정·새 Task·지식 조사·작업 실행·init·전이·승인 기록·로그·marker·잠금 쓰기를 하지 않는다. 미연결·손상·모호함도 읽은 결과로 보고한다. 재개 요청은 [start](../start/SKILL.md)가 맡는다.
