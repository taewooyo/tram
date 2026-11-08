"""정본 자산의 배포 경계·보조 자산·검증 계약 회귀 검사 (stdlib only)."""

from pathlib import Path
import ast
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
SKILLS = SOURCE / "skills"
LEGACY = ROOT / ".codex/skills"
PRESERVED = {
    "prd", "plan", "impl", "verify", "interview", "quick", "coverage",
    "perf-loop", "domain", "retro", "commit", "push", "pr", "diagram",
    "skill-stat",
}


def read(relative):
    return (SOURCE / relative).read_text(encoding="utf-8")


def markdown_section(content, heading):
    """Select one real stage; stop at a heading of the same or higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    tail = content.split(heading + "\n", 1)[1]
    return re.split(r"(?m)^#{1," + str(level) + r"} ", tail, maxsplit=1)[0]


class SkillContracts(unittest.TestCase):
    def test_guided_onboarding_and_native_question_contracts(self):
        questions = read("context/user-questions.md")
        for boundary in ("실제 도구로 질문", "추천 선택지를 먼저", "자유롭게 입력", "의존하는 질문", "필요한 자유 입력을 지원하지", "일반 대화", "별개", "명시적 응답"):
            self.assertIn(boundary, questions)
        onboarding = read("context/project-onboarding.md")
        for boundary in ("심화 조사를 권장", "staged 삭제", "사용자가 승인한 범위만", "fresh 독립 reviewer", "미결정", "기존 runtime"):
            self.assertIn(boundary, onboarding)
        self.assertIn("project-onboarding.md", read("skills/init/SKILL.md"))
        self.assertIn("user-questions.md", read("context/runtime-contract.md"))
        for host in ("codex", "claude"):
            self.assertIn("context/user-questions.md", (ROOT / "platform" / host / "adapter.md").read_text())

    def test_observation_integration_preserves_runtime_and_read_only_boundaries(self):
        # Instruction contracts only; runtime/host behavior is tested separately.
        target = "../../context/start-experience.md#작업별-검증과-정책-관찰"
        for name in ("init", "start", "status", "impl", "quick", "verify"):
            with self.subTest(skill=name):
                self.assertIn(target, read(f"skills/{name}/SKILL.md"))
        contract = markdown_section(read("context/runtime-contract.md"),
                                    "## 선택형 하네스 관찰 계약")
        for boundary in ("기존 runtime이 정본", "mode: observe", "기존 required는 항상 포함",
                         "source: caller_reported", "reported_pass", "storage_digest",
                         "요청·범위를 확보하지 못하면", "완료 판정을 덮어쓰지 않는다",
                         "디렉터리·잠금·Task·marker·metrics도 만들지 않는다"):
            self.assertIn(boundary, contract)
        for diagnostic in ("VERIFICATION_RESULT_MISSING", "VERIFICATION_RESULT_INVALID",
                           "HUMAN_REVIEW_PENDING", "REQUIRED_CHECK_OMISSION_PROPOSED"):
            self.assertIn(diagnostic, contract)
        status = read("skills/status/SKILL.md")
        self.assertIn("show로만 읽을 수", status)
        self.assertIn("search·recommend·record·configure나 새 지식 조사를 시작하지 않는다", status)
        flow = markdown_section(read("context/start-experience.md"),
                                "## 작업별 검증과 정책 관찰")
        self.assertIn("관찰 기록은 작업 메모이며 승인·증거·별도 상태 엔진이 아니다", flow)
        self.assertIn("실제 호스트 행동·속도 개선의 증거가 아니다", contract)
        knowledge = read("context/project-experience.md")
        self.assertIn("기존 매핑의 우선순위와 명시적 빈 설정을 존중", knowledge)
        self.assertIn("정책 없음이 아니라 미확인", knowledge)

    def test_conversation_collection_keeps_entrypoint_and_decision_boundaries(self):
        # Structural regression only; scenario execution requires a real agent.
        prd = read("skills/prd/SKILL.md")
        branch = prd.split("3. **재료가 거의 없음:**", 1)[1].split("입력이 충분하지", 1)[0]
        for rule in ("start에서 진입", "같은 대화", "직접 호출", "interview 수집 모드"):
            self.assertIn(rule, branch)
        interview = read("skills/interview/SKILL.md")
        for obsolete in ('"응"만 하면', '"응"만 오면', '**한 번에 하나씩**', '**확인만**'):
            self.assertNotIn(obsolete, interview)
        for guard in ("요약 확인 전에 저장하지", "임의로 /prd·Plan·구현으로 넘어가지 않는다"):
            self.assertIn(guard, interview)
        policy = read("context/project-experience.md")
        for boundary in ("데이터 의미", "외부 계약", "쉽게 되돌릴 수 있는", "명확한 동의", "독립적인 질문"):
            self.assertIn(boundary, policy)

    def test_open_questions_preserve_decision_and_collection_boundaries(self):
        policy = markdown_section(read("context/project-experience.md"), "## 열린 질문의 능동적 해소")
        for rule in ("확인 가능한 사실은 조사", "직접 질문", "별도 명령 입력을 요구하지 않는다",
                     "현재 미승인 PRD", "이미 승인된 PRD·Plan은 덮어쓰지",
                     "관련 승인·구현을 보류", "무응답을 동의", "읽기 전용 조회",
                     "추천안을 적극적으로 제안", "장단점·위험", "추천은 사용자 답변과 구분"):
            self.assertIn(rule, policy)
        prd = read("skills/prd/SKILL.md")
        self.assertIn("미결정을 남긴 채 확정을 요청하지 않는다", prd)
        interview = markdown_section(read("skills/interview/SKILL.md"), "## 호출 흐름 안의 수집 모드")
        for rule in ("저장 확인 게이트를 추가하지 않는다", "씨앗으로 덮어쓰지 않는다", "독립 interview 호출"):
            self.assertIn(rule, interview)

    def test_summary_display_preserves_snapshot_and_read_only_boundaries(self):
        # Instruction boundaries only; real conversation quality is evaluated separately.
        display = markdown_section(read("context/start-experience.md"), "## 요약·문서 안내")
        for rule in ("본문과 일치", "이전 승인과 달라진", "명시적 응답 없이", "실제 존재하고 읽을 수 있는",
                     "아직 생성 전", "생성하지 않는다", "runtime 조회가 정본", "승인 문서에 덧붙이지 않는다",
                     "문서·로그·marker·잠금을 쓰지 않는다"):
            self.assertIn(rule, display)
        for name in ("prd", "plan", "status"):
            self.assertIn("../../context/start-experience.md#요약문서-안내", read(f"skills/{name}/SKILL.md"))
        docs = read("context/doc-conventions.md")
        for boundary in ("승인 전에", "과거 승인 산출물", "바이트 digest", "무단 삭제·공유하지 않는다",
                         "문서만 복사", "Git 추적이나 공개 허가"):
            self.assertIn(boundary, docs)

    def test_readiness_guidance_preserves_entrypoint_authority(self):
        # Prompt contracts only; this does not establish actual host/LLM behavior.
        guidance = markdown_section(read("context/start-experience.md"),
                                    "## 준비 상태와 문제 해결 안내")
        for rule in ('doctor --project "<target>"', "readiness", "runtime",
                     "이유 → 영향 → 먼저 할 행동", "관측한 범위", "원래 exit/errorCode",
                     "정상 흐름에 필수 진단 게이트를 추가하지 않는다",
                     "기존 `status`가 정본", "자동 migration·복구 적용·잠금 삭제·프로세스 종료를 하지 않는다",
                     "package_identity", "host_validation", "미확인",
                     "로그·marker·잠금을 쓰지 않는다"):
            with self.subTest(rule=rule):
                self.assertIn(rule, guidance)
        link = "../../context/start-experience.md#준비-상태와-문제-해결-안내"
        cases = {
            "status": ("상태 조회 뒤", "상태 조회 실패", "원래 오류를 보존", "승인·검증 판단은 status"),
            "init": ("연결·설정 결과 뒤", "연결 실패", "자동 재시도·복구하지 않는다"),
            "start": ("기존 전이 검사에서 막혔을 때", "정상 흐름에 필수 진단 게이트를 추가하지 않으며",
                      "승인·검증 차단은 status가 정본"),
        }
        for name, rules in cases.items():
            content = read(f"skills/{name}/SKILL.md")
            with self.subTest(entrypoint=name):
                self.assertIn(link, content)
                self.assertIn("doctor를 보조 조회", content)
                for rule in rules:
                    self.assertIn(rule, content)

    def test_start_experience_links_and_execution_boundaries(self):
        # These structural assertions check instructions, not actual LLM behavior.
        card = SOURCE / "context/start-experience.md"
        self.assertTrue(card.is_file())
        for name in sorted(PRESERVED | {"init", "start", "status"}):
            path = SKILLS / name / "SKILL.md"
            content = path.read_text()
            with self.subTest(skill=name):
                links = re.findall(r"\]\(([^)]+)\)", content)
                self.assertIn(card.resolve(), {(path.parent / link).resolve()
                                              for link in links if "://" not in link})
        self.assertIn("./start-experience.md", read("context/runtime-contract.md"))
        experience = SOURCE / "context/project-experience.md"
        self.assertTrue(experience.is_file())
        for name in ("start", "prd", "plan", "impl", "verify", "quick", "init",
                     "domain", "retro", "coverage", "perf-loop"):
            path = SKILLS / name / "SKILL.md"
            content = path.read_text()
            with self.subTest(project_experience=name):
                links = re.findall(r"\]\(([^)]+)\)", content)
                self.assertIn(experience.resolve(), {(path.parent / link).resolve()
                                                     for link in links if "://" not in link})
        helper = SOURCE / "scripts/project-context.py"
        self.assertTrue(helper.is_file())
        for command in ("workspace", "knowledge", "capture", "compare"):
            self.assertIn(f'"{command}"', helper.read_text())
        worktree = SOURCE / "scripts/worktree.py"
        self.assertTrue(worktree.is_file())
        for function in ("create", "list_worktrees", "connect", "disconnect", "merge_suggestion", "remove"):
            self.assertRegex(worktree.read_text(), rf"(?m)^def {function}\(")
        self.assertIn("merge-tree", worktree.read_text())
        self.assertIn('subs.add_parser("suggest-merge")', worktree.read_text())
        self.assertIn('disconnect_parser.add_argument("--to", required=True)', worktree.read_text())
        self.assertIn('"worktree", "remove"', worktree.read_text())
        self.assertNotIn('"--force"', worktree.read_text())
        self.assertIn("실행 직전에", read("skills/start/SKILL.md"))
        self.assertIn("start", read("skills/quick/SKILL.md"))
        self.assertIn("quick", read("skills/init/SKILL.md"))
        knowledge_policy = read("context/project-experience.md")
        for marker in ("해당 slug에서만", "출처와 검증 상태", "사용자의 결정·승인", "docs/knowledge/"):
            self.assertIn(marker, knowledge_policy)
        for name in ("prd", "plan", "impl"):
            content = read(f"skills/{name}/SKILL.md")
            with self.subTest(context=name):
                self.assertRegex(content, r"(?m)^- (?:인자가 )?없[^\n]*문맥[^\n]*재사용")
        for name, scope, target in (("prd", "prd", "plan"), ("plan", "plan", "impl")):
            runtime_section = read(f"skills/{name}/SKILL.md").split("## 런타임 기록", 1)[1].strip().split("\n\n", 1)[0]
            with self.subTest(approval=name):
                self.assertIn(f"approve --scope {scope}", runtime_section)
                self.assertIn("저장 성공", runtime_section)
                self.assertIn("start에서 진입한 흐름", runtime_section)
                self.assertIn(f"../{target}/SKILL.md", runtime_section)
        status = read("skills/status/SKILL.md")
        for field in ("effective_phase", "next_action", "approvals_valid", "blocked", "completion_issues"):
            self.assertIn(field, status)
        self.assertRegex(status, r"조회는[^\n]*작업 실행[^\n]*전이[^\n]*로그[^\n]*marker[^\n]*잠금 쓰기를 하지 않는다")

    def test_status_table_preserves_uncertainty_and_route_boundaries(self):
        status = read("skills/status/SKILL.md")
        for rule in ("작업 | 진행 상태 | 다음 행동", "항목 | 현재 상태",
                     "상세 조회 대상을 임의로 선택하지 않는다", "해당 없음",
                     "미확인", "정상·통과로 추정하지 않는다",
                     "실제 존재하는 문서만 링크", "원래 오류와 다음 행동",
                     "기록이나 문서를 생성하지 않는다"):
            self.assertIn(rule, status)

    def test_adoption_finishing_and_document_check_guards(self):
        # Reference and critical instruction regression; not agent-dialogue evidence.
        adoption = markdown_section(read("context/project-experience.md"),
                                    "## 선택형 프로젝트 도입 조사")
        for rule in ("생략해도", "프로젝트 전반", "해당 변경과 관련된 범위만",
                     "AGENTS.md", "CLAUDE.md", "조사 선택은 문서 쓰기 승인이 아니다",
                     "검토한 변경만", "일괄 생성", "코드 동작만으로"):
            self.assertIn(rule, adoption)
        self.assertIn("#선택형-프로젝트-도입-조사", read("skills/init/SKILL.md"))
        finishing = markdown_section(read("context/start-experience.md"),
                                     "## worktree 마무리와 재개")
        for rule in ("finish-status --project", "--target", "next_action", "선택은 실행 권한이 아니다",
                     "인증·원격 접근·실제 PR 성공은 미확인", ".tram/local/tasks/<slug>.md",
                     "승인 증거·현재 상태 증거가 아니다", "다시 확인", "ignore",
                     "status는 로컬 마무리 메모도 쓰지 않는다", "영속 저장 성공으로 보고하지 않으며"):
            self.assertIn(rule, finishing)
        for name in ("commit", "push", "pr"):
            self.assertIn(f"../skills/{name}/SKILL.md", finishing)
        start = read("skills/start/SKILL.md")
        for rule in ("effective_phase=complete", "next_action=finishing", "#worktree-마무리와-재개"):
            self.assertIn(rule, start)
        for name in ("impl", "quick", "verify"):
            self.assertIn("#변경-관련-문서-점검과-보고", read(f"skills/{name}/SKILL.md"))
        for name, final_stage in (("impl", "### 3. 검증 —"), ("quick", "### 5. 검증 —")):
            content = read(f"skills/{name}/SKILL.md")
            self.assertLess(content.index("### 관련 문서 점검"), content.index(final_stage))
        docs = markdown_section(read("context/project-experience.md"),
                                "## 변경 관련 문서 점검과 보고")
        for rule in ("변경 불필요", "조사 범위", "미해결", "승인 스냅샷", "낡은 증거"):
            self.assertIn(rule, docs)

    def test_impl_delegation_and_verification_roles(self):
        # Structural regression only: these checks cannot prove LLM compliance,
        # successful host execution, or real independence of worker sessions.
        card = read("context/start-experience.md")
        task = card.split("## 프로젝트 전체 작업의 단일 오케스트레이션", 1)[1].split("## 완료", 1)[0]
        for rule in ("메인 하나", "재위임하지 않는다", "작은 보완", "실제 실행 참조",
                     "소유 파일", "의존 관계", "메인만 Task", "중복 배정하지 않는다",
                     "명시적 사용자 요청", "fresh reviewer", "보류"):
            with self.subTest(rule=rule):
                self.assertIn(rule, task)
        for failure in ("확인 불가", "지원 불가", "오류", "중단", "빈 결과"):
            self.assertIn(failure, task)
        self.assertIn("작은 순차 저위험 조사·수정·light 테스트는 메인이 직접 수행", task)
        self.assertIn("별도 실행 의무가 없다", task)
        for resource in ("파일", "포트", "DB", "출력 디렉터리"):
            self.assertIn(resource, task)
        self.assertIn("자원이 독립적인 작업만 병렬", task)
        self.assertIn("공유 파일 수정 또는 선행 결과가 필요한 작업은 순차", task)
        self.assertNotIn("실질 작업은 작업자에게 기본 위임", task)
        self.assertNotIn("light 검증 작업자는 구현 담당과 다른 실행으로 분리", task)
        impl = read("skills/impl/SKILL.md")
        self.assertNotRegex(impl, r"메인에서 바로[^\n]*(?:apply_patch|고친다)")
        self.assertIn("새 좁은 구현 에이전트", impl)
        self.assertIn("후속 작업", impl)
        self.assertIn("fresh reviewer를 직접 생성", impl)
        self.assertIn("메인이 `transition --action verify --strength light|full`", impl)
        self.assertIn("`--manual-full-continuation`을 전달하지 않는다", impl)
        self.assertIn("review", impl)
        verify = read("skills/verify/SKILL.md")
        self.assertIn("사용자가 이 스킬을 직접 호출", verify)
        self.assertIn("`--manual-full-continuation`", verify)
        self.assertIn("자동으로 다음 라운드를 시작하지 않는다", verify)
        worker = markdown_section(verify, "## 런타임 증거 저장")
        for rule in ("메인", "fresh reviewer", "재위임", "구현 파일 수정",
                     "verify-run --command ID", "메인은 full 합계", "quick·coverage·perf-loop"):
            with self.subTest(verification_rule=rule):
                self.assertIn(rule, worker)
        start = read("skills/start/SKILL.md")
        self.assertIn("별도 단계 명령 없이 메인이 다음 역할로 연결", start)
        for stage in ("prd", "plan", "impl", "verify"):
            self.assertIn(f"../{stage}/SKILL.md", start)
        path = SKILLS / "verify/SKILL.md"
        links = re.findall(r"\]\(([^)]+)\)", verify)
        self.assertIn((SOURCE / "context/start-experience.md").resolve(),
                      {(path.parent / link).resolve() for link in links if "://" not in link})

    def test_prd_and_plan_keep_gates_while_allowing_small_direct_work(self):
        # Instructions define the intended workflow; live agent behavior needs separate dialogue evidence.
        prd = read("skills/prd/SKILL.md")
        self.assertIn("직접 작성하거나 기존 작성자 역할에 좁게 배정한다", prd)
        self.assertIn("fresh 독립 서브에이전트", prd)
        self.assertIn("직접 작성한 경우에도 이 검토는 생략", prd)
        self.assertIn("원 요청 요약·결정·가정·근거·미결정", prd)
        self.assertIn("확정 전에 ②/③으로 넘어가지 않는다", prd)
        self.assertNotIn("PRD 작성과 검토를 별도 서브에이전트로 수행한다", prd)

        reviewer = read("agents/reviewer.md")
        for item in ("[의도 출처와 판단 근거]", "근거 없는 정책", "전체 대화 원문"):
            self.assertIn(item, reviewer)

        experience = read("context/start-experience.md")
        provenance = markdown_section(experience, "### Reviewer에게 전달할 의도 근거")
        for item in ("압축 요약", "확정한 결정", "명시적 가정", "미결정 항목", "원문 대화 전체"):
            self.assertIn(item, provenance)

        plan = read("skills/plan/SKILL.md")
        self.assertIn("메인이 위험·범위·맥락 재구성 비용을 보고 직접 수행하거나", plan)
        self.assertIn("복잡한 구현의 실행 정합성", plan)
        for item in ("`ID`", "`depends`", "소유 파일", "공유 자원", "생성·재생성 명령",
                     "순환이 없는지", "공유 자원이 병렬 처리로 충돌", "변경 후 검사 단계"):
            with self.subTest(plan_requirement=item):
                self.assertIn(item, plan)
        self.assertIn("단순하고 순차적인 작업은 현재의 간결한 순서형 단계", plan)
        self.assertIn("승인 없이 구현으로 안 넘어간다", plan)

    def test_project_wide_roles_and_read_only_boundaries(self):
        # Markdown and runtime contracts cannot guarantee continued LLM compliance.
        card = markdown_section(read("context/start-experience.md"),
                                "## 프로젝트 전체 작업의 단일 오케스트레이션")
        for rule in ("메인만 Task", "재위임하지 않는다", "작업자는", "사용자 질문",
                     "승인/전이", "실제 실행 참조", "작은 보완", "상태 확인 전",
                     "순차 실행", "동시 실행 한도", "명시적 사용자 요청"):
            with self.subTest(common=rule):
                self.assertIn(rule, card)
        for name in sorted(PRESERVED | {"init", "start", "status"}):
            content = read(f"skills/{name}/SKILL.md")
            with self.subTest(role=name):
                self.assertIn("메인", content)
                self.assertIn("../../context/start-experience.md", content)
                if name != "status":
                    self.assertRegex(content, r"작업자|검증 담당|reviewer")
        status = read("skills/status/SKILL.md")
        self.assertRegex(status, r"읽기 전용|쓰기 없이")
        for boundary in ("Task", "로그", "marker", "잠금", "전이"):
            self.assertIn(boundary, status)
        self.assertNotRegex(status, r"(?m)^`python3[^\n]* (?:start|transition|approve|verify-run) ")
        for name in ("init", "interview", "domain", "retro", "diagram", "skill-stat"):
            with self.subTest(material=name):
                content = read(f"skills/{name}/SKILL.md")
                self.assertNotRegex(content, r"start --route full")
        for route in ("full", "quick", "coverage", "perf"):
            self.assertIn(route, card)
        runtime = markdown_section(read("context/runtime-contract.md"), "## 검증과 전문 트랙")
        for rule in ("메인만 검증 라운드", "fresh reviewer를 직접 생성", "작업자는",
                     "verify-run", "자료 작업 때문에 새 route를 만들지 않는다"):
            self.assertIn(rule, runtime)

    def test_project_wide_stage_ownership_has_no_direct_execution_conflicts(self):
        # Reject conflicting execution instructions, while allowing words such as
        # 'inline' in comparisons and exceptions explicitly authorized by users.
        for path in SKILLS.glob("*/SKILL.md"):
            content = path.read_text()
            with self.subTest(skill=path.parent.name):
                self.assertNotRegex(content, r"메인에서 바로[^\n]*(?:apply_patch|고친다)")
                self.assertNotRegex(content, r"작고 명확한 테스트는 메인에서 수정한다")
                self.assertNotRegex(content, r"작으면 인라인으로 처리한다")
                self.assertNotRegex(content, r"(?:모든 갭|각 갭)[^\n]*(?:반드시|무조건)[^\n]*병렬")
                self.assertNotRegex(content, r"순차 (?:조사|실행)(?:는|를)? 금지")
                self.assertNotRegex(content, r"light는 구현(?:자| 담당)와 다른 검증 작업자")
                self.assertNotIn("직접 수행은 명시적 사용자 요청의 예외", content)
        quick = markdown_section(read("skills/quick/SKILL.md"), "## 런타임 기록")
        coverage = markdown_section(read("skills/coverage/SKILL.md"), "## 런타임 기록")
        perf = markdown_section(read("skills/perf-loop/SKILL.md"), "## 런타임 기록")
        for name, section in (("quick", quick), ("coverage", coverage), ("perf", perf)):
            with self.subTest(runtime_owner=name):
                self.assertIn("메인", section)
                self.assertIn("transition", section)
                self.assertIn("작업자", section)
        for name in ("coverage", "perf-loop"):
            with self.subTest(serial=name):
                content = read(f"skills/{name}/SKILL.md")
                self.assertIn("직렬", content)
                self.assertIn("소유", content)

    def test_quick_retry_preserves_full_history(self):
        quick = read("skills/quick/SKILL.md")
        self.assertIn("task.full_required", quick)
        self.assertIn("재시도도 **full을 유지**", quick)
        self.assertNotIn("**강도 `light`로 실행**", quick)

    def test_entrypoints_and_native_discovery(self):
        self.assertEqual(
            {p.parent.name for p in SKILLS.glob("*/SKILL.md")},
            PRESERVED | {"init", "start", "status"},
        )
        for path in SKILLS.glob("*/SKILL.md"):
            with self.subTest(skill=path.parent.name):
                content = path.read_text(encoding="utf-8")
                metadata = content.split("---", 2)[1]
                self.assertRegex(metadata, rf"(?m)^name: {path.parent.name}$")
                self.assertRegex(metadata, r"(?m)^description: .+")
                # Common skills must not whitelist tools from only one host.
                self.assertNotIn("allowed-tools:", metadata)
                self.assertIn("../../context/runtime-contract.md", content)
                self.assertIn("<plugin-root>/adapter.md", content)

    def test_auxiliary_assets_survive_extraction(self):
        # Compare inventories rather than a hand-maintained subset of playbooks.
        # Legacy work copies may later be generated from source: the fixed files
        # below ensure that an empty work copy cannot make this test vacuous.
        required = {
            "coverage/playbook.md", "coverage/adapters/python.md",
            "coverage/adapters/kotlin-kover.md", "coverage/agents/openai.yaml",
            "commit/agents/openai.yaml", "push/agents/openai.yaml",
            "skill-stat/agents/openai.yaml",
        }
        source_files = {p.relative_to(SKILLS).as_posix()
                        for p in SKILLS.rglob("*") if p.is_file()}
        self.assertTrue(required <= source_files)
        for name in PRESERVED:
            for path in (LEGACY / name).rglob("*"):
                if path.is_file() and path.name != ".DS_Store":
                    self.assertIn(path.relative_to(LEGACY).as_posix(), source_files)

    def test_package_links_resolve_after_removing_src(self):
        # OS.md is packaged at root; all other relative links resolve in src.
        for folder in (SKILLS, SOURCE / "context", SOURCE / "agents"):
            for path in folder.rglob("*.md"):
                content = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
                for link in re.findall(r"\]\(([^)]+)\)", content):
                    if "://" in link or link.startswith("#"):
                        continue
                    target = (path.parent / link.split("#", 1)[0]).resolve()
                    if target == SOURCE / "OS.md":
                        target = ROOT / "OS.md"
                    with self.subTest(path=path, link=link):
                        self.assertTrue(target.is_file(), str(target))

    def test_tool_paths_do_not_depend_on_project_codex_directory(self):
        for path in SKILLS.rglob("*.md"):
            content = path.read_text()
            with self.subTest(path=path):
                for old in (".codex/scripts/", ".codex/agents/",
                            ".codex/skills/", ".codex/context/",
                            "collaboration.spawn_agent", "fork_turns:"):
                    self.assertNotIn(old, content)
        self.assertFalse((SOURCE / "context/android-conventions.md").exists())
        self.assertNotIn("android-conventions.md", read("skills/impl/SKILL.md"))

    def test_specialized_gates_are_preserved(self):
        coverage = read("skills/coverage/SKILL.md")
        perf = read("skills/perf-loop/SKILL.md")
        # Preserve complete safety sections, not just an isolated keyword.
        for name, marker in (("coverage", "### 5. 반복 안전판"),
                             ("perf-loop", "### R-f. 종료")):
            old = (LEGACY / name / "SKILL.md")
            if old.exists():
                section = old.read_text().split(marker, 1)[1].split("\n##", 1)[0]
                self.assertIn(section, read(f"skills/{name}/SKILL.md"))
        for text in (coverage, perf):
            self.assertIn("독립", text)
            self.assertIn("되돌", text)
        self.assertIn("전체 테스트", coverage)
        # Fixed safety constants are independent of generated source comparisons.
        safety = markdown_section(coverage, "### 5. 반복 안전판")
        for limit in ("8라운드", "30분", "60,000", "2라운드 연속"):
            self.assertIn(limit, safety)
        ending = markdown_section(perf, "### R-f. 종료")
        for limit in ("100라운드", "K=2", "실패·폐기", "직렬"):
            self.assertIn(limit, ending)
        self.assertIn("6차원 루브릭", perf)
        self.assertIn("산출물 동일성", perf)
        self.assertIn("min-gate", read("context/runtime-contract.md"))

    def test_new_coverage_is_explicit_and_legacy_remains_readable(self):
        for path in ("skills/coverage/SKILL.md", "skills/coverage/adapters/python.md"):
            content = read(path)
            self.assertIn("legacy `.codex/project-profile.json`", content)
            self.assertIn("신규 `.tram/project.json`", content)
        contract = read("context/runtime-contract.md")
        self.assertIn("새 coverage 설정은 미설정", contract)
        for name in ("skill-stat", "retro"):
            self.assertIn(".codex/skill-usage.log", read(f"skills/{name}/SKILL.md"))
            self.assertIn(".tram/local/logs/skill-usage.log", read(f"skills/{name}/SKILL.md"))

    def test_review_and_runtime_contract_are_host_independent(self):
        reviewer = read("agents/reviewer.md")
        self.assertTrue(reviewer.startswith("---\nname: reviewer\n"))
        self.assertNotIn("developer_instructions", reviewer)
        contract = read("context/runtime-contract.md")
        for command in ("approve --scope", "transition --action", "verify-run --command",
                        "review --file", "--project", "--slug", "--session"):
            self.assertIn(command, contract)
        self.assertIn("fresh generic", contract)
        self.assertIn("native reviewer", contract)
        self.assertIn("자체 검토로 통과시키지 않는다", contract)
        self.assertIn("잠금 쓰기를 하지 않는다", read("skills/status/SKILL.md"))

    def test_pr_uses_body_file_and_packaged_fallback(self):
        content = read("skills/pr/SKILL.md")
        self.assertIn("--body-file", content)
        self.assertNotIn('--body "', content)
        self.assertIn("../../templates/pull_request_template.md", content)
        self.assertTrue((SOURCE / "templates/pull_request_template.md").is_file())

    def test_documented_transition_actions_exist_in_runtime(self):
        runtime = ast.parse(read("runtime/tram.py"))
        transition = next(node for node in runtime.body
                          if isinstance(node, ast.FunctionDef) and node.name == "transition")
        accepted = {node.value for node in ast.walk(transition)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        actions = {
            "submit-prd", "submit-plan", "implement", "verify", "complete",
            "implementation-defect", "design-problem", "requirements-problem", "escalate",
        }
        contract = read("context/runtime-contract.md")
        for action in actions:
            with self.subTest(action=action):
                self.assertIn(action, accepted)
                self.assertIn(action, contract)


if __name__ == "__main__":
    unittest.main()
