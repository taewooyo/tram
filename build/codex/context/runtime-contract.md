# 공통 실행 계약

패키지 도구와 대상 프로젝트 기록을 분리하고 직접 호출에서도 승인·검증 전이를 검사한다.

사용자 문맥 전달·승인 후 역할 연결·재개·Task·완료 안내는 [작업 시작·재개의 사용자 경험](./start-experience.md)을, 프로젝트 조사·지식 재사용·작업 공간 보호는 [공통 프로젝트 경험](./project-experience.md)을 따른다. 아래 기준선은 변경 감지 메모이며 runtime 데이터 모델·승인 의미·전이·검증 증거를 대신하거나 변경하지 않는다.

사용자 질문은 [공통 질문 계약](./user-questions.md)을 따르고 실제 호스트 입력 도구는 adapter에서 확인한다.

## 경로와 연결

- 스킬 파일 위치의 `../..`는 plugin root다. 먼저 그 root의 `adapter.md`를 읽어 실제 native 도구와 지원 한계를 확인한다. host 환경변수가 Markdown 안에서 자동 치환된다고 가정하지 않는다.
- 대상 프로젝트는 명시한 실제 경로다. 프로젝트 상대 경로의 읽기·쓰기·명령 cwd는 모두 그 경로를 기준으로 한다. plugin cache에 프로젝트 문서·로그를 쓰지 않는다.
- 공유 카드는 plugin root의 `context/`, 프로젝트 카드는 대상 `.tram/project.json`의 매핑에서 찾는다. 프로필에 없으면 Android 등 특정 스택 카드를 기본 적용하지 않는다.
- `.tram/project.json`이 우선이다. legacy `.codex/project-profile.json`은 호환 입력으로만 읽고 충돌 시 선택 근거를 보고한다. 새 coverage 설정은 미설정이다. legacy 프로필 경로에서만 기존 Python 기본값을 허용한다.
- 새 로그·marker는 대상 `.tram/local/` 아래 둔다. legacy `.codex/skill-usage.log`·회고 marker는 조회만 하며 변경하지 않는다. `.tram/local/` ignore가 보장되지 않으면 원문 로그를 남기지 않는다.

## 상태와 승인

runtime은 `python3 "<plugin-root>/runtime/tram.py"`로 실행한다. 아래 모든 task 명령에는 `--project "<target>" --slug "<slug>"`를 붙인다. `init`·`status`는 slug 없이도 호출할 수 있다. `<...>`는 실제 값으로 치환하며 셸 경로와 사용자 인용은 안전하게 인용한다.

- `init --project "<target>"`: 조사·연결. 기존 관리 block 충돌은 보존하고 알린다.
- `status`: 조회만 한다. 실패한 조회도 로그·marker·잠금을 쓰지 않는다. 여러 task는 사용자가 식별한 slug로 선택하며 최신 task를 임의 선택하지 않는다.
- `start --route full|quick|coverage|perf`: 작업을 만들거나 재개한다. 위험 감별 후 route를 선택하며 runtime의 전이 거부를 우회하지 않는다.
- `approve --scope prd|plan --quote "<명시적 승인 최소 인용>" --session "<대화 reference>"`: 원본 대화의 승인을 확인한 뒤에만 기록한다. 먼저 문서의 확정·승인 표식을 반영하고 최종 바이트를 runtime이 읽게 한다. 문서 존재·상태 표식만으로 승인 기록을 만들어서는 안 된다.
- `transition --action submit-prd|submit-plan|implement|verify|complete|implementation-defect|design-problem|requirements-problem|escalate`: 실제 호출은 행동 하나를 선택한다. `submit-prd`·`submit-plan`은 초안을 검토 대기로, `implement`는 구현 진입 검사, `verify`는 검증 라운드 시작, `complete`는 유효 증거 확인 후 완료다. 결함은 `implementation-defect`, 설계 변경은 `design-problem`, 요구 변경은 `requirements-problem`으로 돌린다. 예외 route의 승격은 `escalate`다. phase를 직접 쓰지 않는다.
- `verify-run --command "<profile 명령 ID>"`: 선택된 프로젝트 검증 명령을 runtime이 실행해 증거를 수집한다. 종료 코드를 에이전트가 대신 등록하지 않는다.
- `review --file "<프로젝트 내부 JSON 경로>"`: 아래 스키마로 독립 검토를 등록한다. `status`의 snapshot과 `task.round`를 검토 시작 때 보관하고 그대로 전달한다. 등록 직전 새 snapshot을 넣어 오래된 검토를 위장하지 않는다.
- `configure --project "<target>" --file "<프로젝트 내부 JSON 경로>"`: 조사·사용자 선택으로 확정한 프로필 델타를 적용한다. 허용 필드는 `commands`, `inputs`, `exclude`, `coverage`, `perf`, `reviewer`, `conventions`, `territories`, `retain_raw_output`, `diagnostics`, `metrics`다. 명령은 `id`, `argv` 배열, 프로젝트 상대 `cwd`, `confirmed`, `required`, 선택 `timeout`을 명시한다. 후보를 임의로 confirmed로 바꾸지 않는다. `coverage`·`perf`·`reviewer`는 `configured` boolean을 포함한다. 실행 조건까지 확보한 기능만 true로 설정한다.
- `unlink --project "<target>"`: 관리 block만 검사해 해제하며 프로젝트 기록·문서를 보존한다. 설치 본체 제거는 native manager의 별도 작업이다.

`prd`·`plan`·`impl`·`verify` 직접 호출도 먼저 `status`를 확인하고 해당 행동의 `transition` 검사를 통과한다. 사람이 이미 승인한 현재 문서가 있으면 위 절차로 기록하고 이어간다. 새 세션의 구현 요청만으로 과거 승인을 추정하지 않는다. 문서 digest 변경·승인 기록 누락·오래된 검증은 재확인하며 JSON을 수동 편집해 게이트를 넘지 않는다.

## 검증과 전문 트랙

전체 경로와 전문 스킬 직접 호출의 위임·Task·실행 참조·재개는 [작업 시작·재개의 사용자 경험](./start-experience.md)의 단일 오케스트레이션 절을 따른다. 메인은 상태 조회와 `approve`·`transition`·`configure`·`review` 등 진행 제어·증거 등록을 맡고 작업자는 배정된 실질 실행을 맡는다. 메인만 검증 라운드·결과 전이를 실행하며 full은 매 라운드 fresh reviewer를 직접 생성하고 반환 결과를 검산·등록한다. light는 메인 또는 구현 담당이 직접 실제 `verify-run`과 테스트를 수행할 수 있다. full 검증 작업자는 실제 `verify-run`과 독립 검사·판정을 수행한다. route별 진입 조건·강도 이력·전문 안전판은 그대로 유지하며 자료 작업 때문에 새 route를 만들지 않는다.

### 독립 리뷰 JSON

`review` 입력은 `reviewer`(매번 새 실행 식별자), `reference`(독립 실행 reference), `adapter`, `implementer_reference`, `fresh: true`, 검토 시작 `status.snapshot`을 담은 `snapshot`, `status.task.round`를 담은 `round`, `axes`, `blocking`, `unmet`, `score`, `verdict`를 포함한다. `axes`는 서로 다른 5축의 배열이며 각 객체에 `name`, 정수 `level`(0·1·2), 비어 있지 않은 `evidence`가 필요하다. `blocking`·`unmet`은 배열, `score`는 레벨 합×10이다. `verdict`는 `pass`·`implementation-defect`·`design-problem`이다. pass는 ≥90·0축 없음·blocking/unmet 없음일 때만 허용한다.

실제 독립 실행 결과로 JSON을 채워 대상 `.tram/local/`에 host의 허용된 편집 도구로 저장한다. 동일 reviewer/reference는 재사용하지 않는다. 등록 직전 snapshot/round를 갱신해 오래된 결과를 위장하지 않는다. 리뷰·로그가 입력 snapshot을 바꾸지 않도록 `.tram/` 제외 계약을 유지한다. 사람의 PRD·Plan 검토 결과는 코드 리뷰 JSON으로 위장하지 않으며 `approve`로 기록한다.

full은 매 라운드 adapter로 새 독립 reviewer를 실행하고 `agents/reviewer.md`·루브릭·최신 diff·필요한 카드를 전달한다. Codex는 fresh generic reviewer, Claude는 native reviewer를 adapter대로 연결한다. 구현자 대화·이전 점수는 전달하지 않는다. 독립 실행이 없으면 full은 검증 불가이며 자체 검토로 통과시키지 않는다. 실행되지 않은 검사도 통과로 등록하지 않는다.

테스트 증거는 `verify-run`, 독립 검토 증거는 `review`로 구분한다. 통과·구현결함·설계문제 판정과 기존 min-gate·라운드 예산·막힘 가드를 유지한다. 수정 후에는 새 증거로 검증하고 `transition`으로 결과를 반영한다. runtime 오류는 보고하고 완료를 주장하지 않는다.

검증 라운드는 `transition --action verify --strength light|full`로 연다. full·coverage 경로는 full 필수다. quick은 기본 light, perf는 기본 full이며 착수 때 충분한 동작 보존 테스트와 저위험 근거를 확인한 경우에만 `--strength light --reason "최소 근거"`를 선택한다. 한 번 full을 사용한 task는 후속 라운드에서 light로 낮출 수 없다. full route의 기본 예산은 5라운드이며 기본 상한과 정체 가드는 모든 일반 호출에 적용된다. 사용자가 `/verify full`을 직접 다시 요청한 경우에만 `--manual-full-continuation`으로 해당 호출의 상한·정체 가드를 건너뛰어 추가 라운드 하나를 연다. 이는 caller attestation이며 신원 인증이 아니다. 자동 반복은 하지 않고, 매 추가 라운드도 현재 snapshot의 테스트 증거와 fresh 독립 reviewer가 필요하다. task와 실제 테스트 증거에 선택 강도가 기록되며 light에는 코드 리뷰 점수를 만들지 않는다. perf의 별도 측정·정확성·성능 6차원 기준은 light여도 생략하지 않는다.

coverage는 Git·깨끗한 비기본 브랜치·명시적 adapter·전체 테스트·독립 리뷰·건강도·라운드 안전판을 유지한다. perf는 측정·정확성·6축 루브릭·되돌림·예산을 유지한다. 필요한 Git/gh·Bash/jq·Java/wrapper·pytest-cov·Chrome/Node 등은 해당 기능을 실행할 때 검사한다. core 조회 때문에 모든 선택 도구를 요구하지 않는다. 훅이 없으면 카드를 명시적으로 읽고 retro·PR 사전 검사를 수행하며 자동 주입·차단의 부재를 보고한다.

## 선택형 하네스 관찰 계약

`scripts/harness.py`는 프로젝트별 검사 추천·정책 검색·선언 결과의 참고 해석을 제공한다. **승인·필수 검사·검증 강도·독립 검토·반복 예산·중단·완료 판정은 기존 runtime이 정본**이다. 관찰 경고나 추천 선택으로 이를 생략하거나 약화하지 않는다. 기본 도입·작업·조회에 관찰 설정은 필수가 아니며, 미설정이면 기존 Tram 흐름을 이어간다. 실제 행동 연결은 [시작·재개 경험](./start-experience.md#작업별-검증과-정책-관찰)을 따른다.

- 실행 전 `python3 "<plugin-root>/scripts/harness.py" contract`와 해당 하위 명령의 `--help`를 읽는다. 명령은 에이전트가 호출하며 사용자에게 새 명령 입력이나 검사 전체의 수동 선택을 요구하지 않는다.
- `.tram/harness.json`은 schema 1의 보조 설정이며 `mode: observe`만 지원한다. `checks`는 기존 프로젝트 프로필의 command ID를 참조하고 argv·required를 복제하지 않는다. `knowledge`는 검색 경로와 기존 문서의 선택적 출처·태그·적용 범위·확인 시점·대체 관계를 연결한다. schema 2의 project/task와 분리하며 자동 migration하지 않는다.
- 메인이 확정한 프로젝트 내부 delta를 `configure --project PATH --file RELATIVE_JSON --expected-revision N --expected-digest DIGEST`로 저장한다. 최초 생성은 revision 0·digest `missing`, 이후에는 현재 revision·digest를 사용한다. 보조 설정의 schema/revision과 기존 프로필 JSON을 수동 덮어쓰지 않는다. 예시 `templates/harness-observation.json`은 선택 설정의 출발점이며 실행 명령을 자동 등록하지 않는다.
- `recommend --project PATH --slug SLUG --request TEXT --path REL`은 작업의 현재 요청·경로로 후보와 선택·제외 이유를 계산한다. 반복 `--path`로 범위를 전달한다. 기존 required는 항상 포함하며 미확정 명령은 실행할 수 없다고 표시한다. `--omit ID`로 필수 검사 제외가 제안돼도 실제로 제외하지 않고 `REQUIRED_CHECK_OMISSION_PROPOSED`를 표시한다. 경로와 키워드는 영향의 단서이며 검사 불필요나 정책 부재의 증거가 아니다.
- `search --project PATH --query TEXT --path REL`의 결과는 기존 knowledge 매핑에 더하는 후보다. 기존 매핑·우선순위·명시적 빈 설정을 변경하지 않는다. 문서 출처·digest·검색 범위·생략·미확인을 확인하고 실제 문서를 읽는다. 검색 결과 없음은 정책 없음이 아니다. 제품·보안 정책의 충돌과 확정은 기존 사람 결정 경계를 따른다.
- `record --project PATH --slug SLUG --file RELATIVE_JSON --expected-digest DIGEST`만 작업별 관찰을 명시 저장한다. 최초 digest는 `missing`, 이후에는 `show`의 `storage_digest`를 사용한다. `.tram/local/harness/<slug>/`에 저장하며 기존 ignore·잠금·경로·동시 변경 검사를 따른다. 기록 실패를 저장 성공으로 보고하거나 ignore 규칙을 자동 변경하지 않는다.
- 추천 입력은 schema 1의 `kind: recommendation`과 `report`(실제 recommend의 result), 결과 입력은 `kind: result`, `command_id`, `run_id`, `outcome`, `declared_scope`, `limitations`, 선택적 `cases_count`·`artifacts`·`reason`을 사용한다. `not_run`은 run_id null과 이유가 필요하며 실행된 결과는 task에 등록된 실제 run을 참조한다. 선언은 `source: caller_reported`이며 검사 범위와 통과 선언을 실행 사실로 승격하지 않는다.
- 기존 실패·취소·미등록·오래된 run의 passed 선언은 통과로 표현하지 않는다. 유효한 실행에 연결된 통과 선언도 `reported_pass`로 구분한다. `minimum_cases`가 설정된 검사는 boolean이 아닌 음이 아닌 정수의 cases_count가 필수이며 누락·타입 오류·미달은 통과 선언으로 인정하지 않는다. 기준 없는 0개 실행은 범위 미확인이다.
- 정책 검색에서는 생성물·의존성·민감 경로를 제외한다. 결과 artifact 참조는 프로젝트 내부 `build`·`dist`·`.tram/local/` 산출물도 허용하되 경로 이탈·symlink·민감 파일·의존성·Git 및 `.tram` 제어 기록은 거부한다. 원문을 복사하지 않고 digest로 변경 여부를 확인한다.
- 구조화 결과가 없는 기존 명령은 기존 성공·완료 계약을 유지하며 검사 범위는 unknown이다. 결과를 기대한 검사의 누락은 `VERIFICATION_RESULT_MISSING`, 손상·모순은 `VERIFICATION_RESULT_INVALID`, 사람 판정 대기는 `HUMAN_REVIEW_PENDING`이다. 관찰 결과의 경고 식별자이며 기존 verify-run 종료 코드·최상위 errorCode·완료 판정을 덮어쓰지 않는다.
- `show --project PATH --slug SLUG [--request TEXT --path REL]`는 저장 관찰과 현재 코드·설정·요청·범위를 대조한다. 요청·범위를 확보하지 못하면 해당 유효성은 unknown이다. 오래된 관찰·변경되거나 사라진 artifact·정책 문서의 근거를 확인하고 재추천·재해석할 항목을 설명한다. 관찰 기록은 승인·실행 증거가 아니다.
- `contract/recommend/search/show/evaluate`는 읽기 전용이다. 디렉터리·잠금·Task·marker·metrics도 만들지 않는다. configure/record만 명시 쓰기이며 성공 exit 0, 입력·저장 충돌 exit 2다. 분석 실패와 관찰 대상의 failed 상태를 구분한다. 보조 도구 오류가 기존 status/verify-run의 결과를 바꾸지 않는다.
- `evaluate --project PATH --file RELATIVE_JSON`는 명시한 고정 사례의 기대값과 추천·검색·해석 결과를 대조하며 프로젝트 명령·fixture 문자열을 실행하지 않는다. 분모 0·미측정은 null, unknown·잘림·미실행은 별도로 보고한다. fixture·정적 스킬 계약 검사는 실제 호스트 행동·속도 개선의 증거가 아니다.

## 운영·호환 계약

`doctor --project PATH`는 기존 파일·잠금·실행 관측에 `readiness`(상태·요약·문제별 근거·다음 행동)와 `runtime`(실행 패키지 버전·프로젝트 schema·미확인 항목)을 더한다. 기존 응답 필드를 보존하며 doctor의 문자열 `next_action`은 관측한 문제에 맞게 구체화한다. status의 단계 라우팅과 CLI exit/errorCode는 유지한다. 진단의 ready는 관측한 준비 범위만 뜻하며 승인·검증·호스트 지원을 증명하지 않는다. 사용자 설명과 진입점별 보조 조회는 [준비 상태 안내](./start-experience.md#준비-상태와-문제-해결-안내)를 따른다.

현재 후보 0.0.1은 schema 2다. schema 1은 읽기 진단만 허용하며 일반 쓰기는 `SCHEMA_MIGRATION_REQUIRED`로 거부한다. 명시적 migration·backup·복귀, doctor/recover/restore, 입력 변경 설명, 진단·지표의 사용법과 한계는 배포 문서 `docs/operations.md`를 따른다. 검증 성공 exit 0, 검증 실패·timeout·정리 실패 exit 1, 입력·상태 오류 exit 2, 사용자 인터럽트 exit 130을 구분하고 JSON의 기록 성공과 실행 성공을 따로 확인한다.
