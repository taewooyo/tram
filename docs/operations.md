# Tram 운영·진단·복구

0.0.1/schema 2 후보의 검증 실패·진단·복구를 안내한다. 원본을 보존하며 schema 변경과 운영 증거를 관리한다. 실제 명령과 옵션은 설치본 `runtime/tram.py --help` 및 하위 명령의 `--help`를 먼저 확인한다. 후보의 구현 검증, 실제 호스트 운영 검증, 공개 배포 준비는 서로 다른 판정이다.

## 실행 결과 확인

`verify-run --project PATH --slug SLUG --command ID`는 프로필에서 확정한 명령을 실제 실행한다. 검증 성공은 exit 0, 검증 실패·timeout·정리 실패는 exit 1, 입력·상태 오류는 exit 2, 사용자 인터럽트는 exit 130이다. JSON의 증거 기록 여부와 실행 성공 여부를 함께 읽는다. exit 7인 대상 명령의 원래 종료 코드는 증거에 보존되며 runtime의 성공으로 해석하지 않는다.

timeout·취소 시 해당 실행에서 소유권을 확인한 프로세스를 정리한다. PID 재사용·권한 부족·관찰 전에 완전히 이탈한 자손은 안전한 자동 종료를 보장할 수 없다. `PROCESS_CLEANUP_FAILED` 또는 소유권 불명 상태이면 다음 검증과 완료를 보류하고 `doctor`의 소유 실행 정보를 확인한다. 무관한 프로세스를 이름이나 추측한 PID로 종료하지 않는다.

sandbox가 `ps`·libproc의 프로세스 관찰을 EPERM으로 거부하면 실행 권한 제약과 검증 대상 명령의 실패를 구분한다. `PROCESS_OBSERVATION_FAILED`는 소유 실행을 관찰할 수 없다는 뜻이며 테스트 assertion 실패의 증거가 아니다. `PROCESS_CLEANUP_FAILED`는 종료 확인을 마치지 못했다는 뜻이다. 어느 경우도 성공·완료로 처리하지 않는다. `doctor --project PATH`로 잠금·활성 실행과 다음 조치를 확인하고, 프로젝트에서 승인한 실행 환경에 필요한 권한을 정식으로 요청한 뒤 검증을 재실행한다. 자동 권한 상승이나 sandbox 제한을 피하는 실행을 하지 않는다. [지원 조건](support.md)의 관찰 범위와 [검증 기록](release-validation.md)의 환경별 결과를 함께 확인한다.

## 검증 강도와 추가 full 요청

`light`는 적용 가능한 테스트·검사를, `full`은 실제 테스트와 새 독립 reviewer의 기준 대조를 요구한다. full·coverage 경로는 full이 필수이고 한 번 full을 사용한 작업은 light로 낮추지 않는다. quick은 기본 light이며 순수 문서 변경에는 링크·문법 등 적용 가능한 검사를 사용한다.

일반 full 경로는 기본 5라운드와 정체 가드에서 멈춘다. 사용자가 verify 스킬에 추가 full 검증을 직접 요청하면 메인이 해당 호출에만 `--manual-full-continuation`을 적용해 한 라운드를 더 열 수 있다. 자동 반복이나 기존 검증 재사용은 허용하지 않으며 새 테스트 증거와 fresh reviewer가 필요하다.

## 진단과 입력

원문 출력 보존은 기본 off다. 프로필 `diagnostics`를 명시적으로 설정한 경우만 `.tram/local`의 제외·symlink·권한 조건을 검사해 제한된 자료를 남긴다. 기본 상한은 각 스트림당 256 KiB, 보존 7일, 총 50 MiB다. 바이트 수·해시는 실제 수집한 출력에 대한 값이며 `output_complete`가 true인 경우에만 전체 출력의 값으로 해석한다. 스트림 EOF 미확인·drain 제한 등으로 수집이 미완료이면 `output_incomplete_reason`과 실행·정리 상태를 함께 확인하고 전체 출력 해시로 주장하지 않는다. 보존 자료의 `truncated`는 저장 상한에 따른 잘림으로, 출력 수집 미완료나 프로세스 정리 실패와 구별한다. 마스킹은 완전한 비밀 제거가 아니다. 원문·환경·인증·대화를 공개 이슈에 붙이지 않는다. `diagnostics show|prune|purge`의 실제 옵션은 하위 도움말로 확인한다. 조회는 파일·잠금·marker를 만들지 않는다.

초기 연결의 입력 추천은 실제 소스·설정과 생성물을 구분하는 후보이며 자동 확정이 아니다. 기존 명시 `inputs`·`exclude`는 보존한다. 캐시만 생성된 경우 검증을 무효화하지 않되 실제 입력의 추가·수정·삭제·실행 비트 변화는 재검증한다. status의 stale 이유·변경 경로는 100개 상한의 설명이며 전체 diff나 복원 근거가 아니다. 명시 입력과 중첩 캐시 제외가 충돌하면 후보를 대조해 configure로 확정한다.

## 읽기 진단과 명시적 복구

### 사용 준비 상태 확인

연결 상태나 막힌 이유가 불분명하면 에이전트에 “Tram 상태와 다음 행동을 확인해 주세요”라고 요청한다. 메인이 status와 doctor를 읽고 이유·영향·먼저 할 행동을 설명한다. 직접 조회하려면 설치된 패키지의 경로를 사용한다.

```bash
python3 "<Tram 루트>/runtime/tram.py" doctor --project "<프로젝트 경로>"
```

`readiness`는 관측한 준비 상태(`ready`·`attention`·`blocked`·`unknown`), 요약, 문제별 근거와 다음 행동을 제공한다. 정상일 때는 불필요한 복구나 migration을 안내하지 않는다. 살아 있거나 소유권이 불명확한 실행은 상태 확인을 먼저 안내하고, 손상 기록·연결 누락·구 schema 등은 근거와 후속 행동을 함께 설명한다. 진단에서 발견한 문제와 명령 자체의 입력 오류(exit 2·errorCode)는 구분한다. 기존 `files`·`lock`·`active_runs` 등의 원본 관측도 유지한다.

`runtime.version`은 실행 중인 패키지의 버전이고 `runtime.project_schema`는 프로젝트 기록 형식이다. `package_identity`와 `host_validation`은 이 조회로 검증하지 않아 `unknown`이다. 버전이 같아도 패키지 파일이 같다는 뜻은 아니며, ready도 실제 호스트 지원·테스트 통과·작업 완료의 증거는 아니다. 메타데이터를 읽지 못하면 확인 불가로 표시하고 나머지 진단을 보존한다.

진단은 관측 시점의 설명이다. 실제 쓰기 전에 기존 잠금·승인·검증 검사를 다시 적용한다. init은 연결 결과 뒤 남은 문제를, start는 기존 전이에서 차단됐을 때 관련 문제를 설명하며 정상 작업에 새 승인 단계를 추가하지 않는다. 자동 복구·migration·잠금 삭제·프로세스 종료는 수행하지 않는다.

### 복구 절차

`doctor --project PATH`와 `status`는 손상·잠금 소유자·활성 실행·승인·증거를 읽기만 한다. 조회 실패도 성공으로 보고하지 않는다. 살아 있거나 소유권을 확인할 수 없는 잠금과 실행은 자동 삭제·종료하지 않는다.

`recover preview`에서 대상·현재 digest·충돌·복구 가능성을 먼저 확인한다. 원본 backup과 journal을 확인한 뒤 같은 digest를 `recover apply --expected-digest DIGEST`에 전달한다. `restore preview|apply`도 backup 무결성·현재 대상 digest·덮어쓰기 충돌을 검사한다. preview 이후 변경되면 apply를 거부하므로 새 preview부터 수행한다. 부분 실패는 journal과 파일별 결과를 보존하고 같은 복구 절차의 재개 가능성을 확인한다. JSON 직접 편집·잠금 파일 삭제·전체 트리 reset으로 우회하지 않는다. 복구 후 과거 완료·검증이 살아났다고 추정하지 말고 새 status와 재검증을 확인한다.

## schema 1과 2의 업데이트·복귀

최초 공개 후보 0.0.1은 schema 2다. 공개 전 개발용 schema 1 기록은 명시적 migration이 필요하다. 새 runtime은 schema 1을 doctor/status/migration preview에서 읽지만 일반 쓰기는 `SCHEMA_MIGRATION_REQUIRED`로 거부한다. 구 runtime은 schema 2를 거부한다. 설치 캐시를 덮어쓰지 않고 native plugin manager로 본체를 관리한다.

1. 소유 실행의 종료를 확인하고 사용자 코드·dirty 파일·관리 block·`.tram` 이력을 backup한다.
2. `migrate preview --project PATH --from 1 --to 2`에서 전체 대상·backup·digest·잠금과 활성 실행을 확인한다.
3. 명시적으로 승인된 프로젝트에서만 `migrate apply --project PATH --from 1 --to 2 --expected-digest DIGEST`를 실행한다. 문서·입력·제외·승인 이력은 보존하며 기존 검증은 stale다.
4. 복귀도 실행 종료와 backup 후 `--from 2 --to 1`의 preview/apply를 먼저 하고 보존한 schema 1 개발용 패키지를 재설치한다. verification/review와 완료를 재검증 상태로 돌릴 수 없으면 복귀를 거부한다. 로컬 진단·지표와 backup은 보존한다.

프로젝트 schema와 설치 cache의 버전은 별개다. schema 1 원본에 새 runtime으로 쓰려면 해당 프로젝트의 migration을 명시적으로 승인해야 한다. 복귀용 이전 배포본과 backup을 미리 보존하고, fixture 검증을 원본 프로젝트의 migration 완료로 간주하지 않는다.

## 로컬 운영 지표

`metrics.enabled`는 기본 true이며 관측한 사건만 로컬에 기록한다. configure에서 false로 비활성화할 수 있고 `metrics purge`로 명시 삭제한다. 기본 보존은 30일·10 MiB다. 대화·환경·출력 원문을 넣지 않으며 미측정 비용/토큰을 0으로 채우지 않는다. 보존 절단·기록 실패는 coverage 제한으로 표시한다.

`metrics summary --since ISO8601 --until ISO8601 [--slug SLUG]`와 `metrics events`는 UTC `[since, until)`의 읽기 전용 조회다. task 완료율은 각 task의 최신 관측 주기 중 기간 내 종료된 `complete/(complete+failed)`다. pending 재오픈은 과거 종료를 재집계하지 않는다. resume 성공률은 종료된 고유 재개의 `succeeded/(succeeded+failed)`이며 pending·unexecuted를 분모에서 뺀다. 분모 0은 null/측정 없음이다. 검증 실패나 timeout만으로 실패 마감을 추정하지 않는다.

`metrics task-close`·`metrics resume-close`는 실제 사용자 중단·실패 마감의 reference와 이유 코드가 있을 때만 사용한다. 로컬 평가상의 마감은 task phase·승인·완료를 바꾸지 않는다. `question-assessment`는 질문 원문 없이 necessary/unnecessary/unknown과 근거 유형·자료 경로만 기록한다. `metrics prune|purge`와 수동 평가·마감은 명시적 쓰기다. 반복 start는 진행 전 pending 재개를 중복 생성하지 않는다.

## 작업별 검사·정책 관찰

에이전트에게 기존처럼 Tram으로 작업을 요청하면 현재 요청과 변경 경로를 바탕으로 필요한 검사와 정책 후보를 확인할 수 있다. 관찰 기능은 선택 사항이다. 설정이 없거나 검색하지 못한 부분은 미확인으로 설명하며, 기존 필수 검사·승인·독립 검토·완료 조건은 그대로 적용한다. 사용자가 매번 검사 전체를 선택하거나 새 단계 명령을 입력할 필요는 없다.

보조 설정은 `.tram/harness.json`, 작업별 참고 기록은 `.tram/local/harness/<slug>/`다. 보조 설정은 `mode: observe`만 허용하고 기존 profile의 command ID에 설명·경로·키워드·결과 기대 여부를 연결한다. 기존 argv·required를 다시 정의하지 않는다. 초기 설정은 에이전트가 프로젝트 자료를 조사해 제안하며 확정할 수 없는 정책만 질문한다. 명령 실행 권한이나 제품 정책 승인을 예시 설정으로 대신하지 않는다.

설치본에서 `python3 "<Tram 루트>/scripts/harness.py" contract`와 해당 하위 명령의 `--help`로 정확한 입력을 확인한다. 설정 변경은 configure, 관찰 저장은 record만 수행하며 예상 revision/digest로 동시 변경을 검사한다. 최초 설정은 `--expected-revision 0 --expected-digest missing`, 최초 관찰 기록은 `--expected-digest missing`을 사용한다. 이후 실제 조회의 revision·digest를 사용하고 JSON 직접 덮어쓰기나 ignore 자동 변경으로 충돌을 우회하지 않는다.

| 확인할 내용 | 내부 조회 | 해석 |
| --- | --- | --- |
| 작업별 검사 후보 | recommend에 slug·현재 request·변경 path 전달 | 필수 검사는 항상 포함, 나머지 선택·제외 이유와 미확인 영향 확인 |
| 관련 정책 | 기존 knowledge와 search에 query·관련 path 전달 | 실제 문서를 읽고 출처·확인 시점·대체 관계·검색 잘림 확인 |
| 재개 시 참고 기록 | show에 slug와 가능한 현재 request/path 전달 | 코드·설정·범위 변경은 stale, 현재 요청 미확보는 unknown |
| 고정 사례 평가 | evaluate에 명시 fixture 파일 전달 | 정답 label 대비 추천·검색·해석 결과이며 실제 호스트 E2E 증거가 아님 |

runtime의 실행 성공, caller_reported 선언, 사람 판정 대기, 미실행을 구분한다. 유효한 실행에 연결된 통과 선언도 reported_pass이며 선언한 scope가 실제 테스트 범위를 증명하지 않는다. 필수 건수 기준이 있는 검사는 건수 누락·타입 오류·미달을 통과 선언으로 인정하지 않는다. 화면 비교 리포트 생성은 사람 판정이나 화면 검증 통과 자체가 아니다.

관찰의 `VERIFICATION_RESULT_MISSING`·`VERIFICATION_RESULT_INVALID`·`HUMAN_REVIEW_PENDING`·`REQUIRED_CHECK_OMISSION_PROPOSED`는 참고 경고다. 이를 실행 성공으로 바꾸거나 기존 verify-run의 exit/errorCode를 덮어쓰지 않는다. 구조화 결과를 제공하지 않는 기존 명령은 기존 계약대로 실행·판정하고 관찰 범위만 unknown으로 설명한다. 기존 runtime에서 필수 검사 누락으로 차단된 완료를 관찰 도구로 허용할 수 없다.

contract/recommend/search/show/evaluate는 읽기 전용이며 조회 중 파일·잠금·Task·metrics를 만들지 않는다. status에서는 저장된 show만 읽고 search·recommend·record·configure나 새 정책 조사를 시작하지 않는다. 저장 실패는 원인과 다음 행동을 알리고 기존 runtime 결과를 보존한다. 보조 기능을 중단할 때는 호출을 비활성화하고 기록을 보존한다. 기존 profile/task·승인·증거를 지우거나 migration할 필요가 없다.

완료 시간·개입·검증 시간·재개·검사 누락·후속 결함은 관측 자료와 정의가 있을 때만 보고한다. 기존 metrics와 고정 사례를 활용하며 미측정은 0 대신 null/미측정이다. 실제 호스트 비교는 동일 시작 코드·요청·호스트·모델·권한 및 후보 식별자를 남겨 수행하고, 정적 계약·fixture 결과를 실제 행동·속도 개선으로 확대하지 않는다.

## 실제 호스트와 공개 준비

현재 Codex·Claude Code용 공개 alpha 준비 중이며 전체 native lifecycle은 미검증이다. 로컬 제거·재설치는 Git upgrade 성공 증거가 아니다. 실제 호스트에서 새 세션 재개·업데이트·제거·복귀와 기존 변경·기록 보존을 확인해야 한다. 검증용 fixture에서도 PRD·Plan의 실제 승인은 각각 필요하며 다른 작업 승인을 재사용하지 않는다. 사용자 인증 복사·전역 trust 자동 변경은 하지 않는다.

현재 후보의 host 검증 목록은 `release.json`의 `validatedHosts`에 기록하며 목표 버전인 `validationTargets`를 통과 증거로 사용하지 않는다. 라이선스는 Apache-2.0이고 GitHub 비공개 취약점 제보를 사용한다. 실제 호스트 검증과 최종 배포본 공개 확인은 남아 있다. [지원표](support.md), [검증 기록](release-validation.md), [보안 안내](../SECURITY.md)를 함께 확인한다.
