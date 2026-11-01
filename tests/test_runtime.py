"""Runtime contracts use real subprocesses; no host-support claims."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / "src/runtime/tram.py"
spec = importlib.util.spec_from_file_location("tram_runtime", RUNTIME)
tram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tram)


class RuntimeCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        tram.init(self.root)
        self.slug = "sample-task"

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def configure(self, argv=None, **changes):
        config = {"commands": [{"id": "test", "argv": argv or [sys.executable, "-c", "print('ok')"],
                                "cwd": ".", "required": True, "confirmed": True}],
                  "inputs": ["code.py"], "reviewer": {"configured": True}}
        config.update(changes)
        self.write("code.py", "value = 1\n")
        return tram.configure(self.root, self.write("config.json", json.dumps(config)))

    def full(self):
        tram.start(self.root, self.slug)
        for scope in ("prd", "plan"):
            self.write(f"docs/{scope}/{self.slug}.md", "# 문서\n\n> 상태: 초안\n내용\n")
            tram.transition(self.root, self.slug, "submit-" + scope)
            tram.approve(self.root, self.slug, scope, "승인", "user-session-1")

    def verifying(self, route="quick"):
        if route == "full":
            self.full()
        else:
            tram.start(self.root, self.slug, route)
        tram.transition(self.root, self.slug, "verify")

    def review_data(self, **changes):
        state = tram.status(self.root, self.slug)
        value = {"reviewer": "reviewer-1", "reference": "spawn-1", "adapter": "test-native",
                 "implementer_reference": "implementation-1", "fresh": True,
                 "snapshot": state["snapshot"], "round": state["task"]["round"],
                 "axes": [{"name": name, "level": 2, "evidence": "code.py:1 — value=1 경계 확인"}
                          for name in ("correctness", "tests", "reuse", "simplicity", "conventions")],
                 "score": 100, "blocking": [], "unmet": [], "verdict": "pass"}
        value.update(changes)
        return value

    def review(self, **changes):
        path = self.write("review.json", json.dumps(self.review_data(**changes)))
        return tram.review(self.root, self.slug, path)

    def assertError(self, code, function, *args, **kwargs):
        with self.assertRaises(tram.TramError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def tree(self):
        return {p.relative_to(self.root).as_posix(): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                for p in self.root.rglob("*")}

    def test_full_flow_real_execution_and_review(self):
        self.configure()
        self.verifying("full")
        self.assertError("VERIFICATION_REQUIRED", tram.transition, self.root, self.slug, "complete")
        result = tram.verify_run(self.root, self.slug, "test")
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["stale"])
        self.assertNotIn("argv", result)
        self.assertNotIn("stdout", result)
        self.assertError("VERIFICATION_REQUIRED", tram.transition, self.root, self.slug, "complete")
        self.review()
        result = tram.transition(self.root, self.slug, "complete")
        self.assertEqual(result["effective_phase"], "complete")
        self.assertIsNone(result["task"]["finishing"]["push"])

    def test_direct_implementation_and_missing_artifact_blocked(self):
        tram.start(self.root, self.slug)
        self.assertError("APPROVAL_REQUIRED", tram.transition, self.root, self.slug, "implement")
        self.assertError("ARTIFACT_REQUIRED", tram.transition, self.root, self.slug, "submit-prd")
        self.assertError("INVALID_TRANSITION", tram.approve, self.root, self.slug, "prd", "승인", "s")

    def test_separate_approvals_and_next_actions(self):
        self.configure()
        state = tram.start(self.root, self.slug)
        self.assertEqual((state["effective_phase"], state["next_action"]), ("prd_draft", "prd"))
        for scope, next_phase, next_action in (("prd", "plan_draft", "plan"),
                                               ("plan", "implementing", "impl")):
            self.write(f"docs/{scope}/{self.slug}.md", "# Fixture document\n")
            state = tram.transition(self.root, self.slug, "submit-" + scope)
            self.assertEqual((state["effective_phase"], state["next_action"]),
                             (scope + "_review", "approve-" + scope))
            self.assertError("APPROVAL_REQUIRED", tram.transition, self.root, self.slug, "implement")
            self.assertError("APPROVAL_REQUIRED", tram.transition, self.root, self.slug, "verify")
            tram.approve(self.root, self.slug, scope, "승인", "fixture-user")
            state = tram.start(self.root, self.slug)
            self.assertEqual((state["effective_phase"], state["next_action"]), (next_phase, next_action))
            self.assertTrue(state["approvals_valid"][scope])
        state = tram.transition(self.root, self.slug, "verify")
        self.assertEqual((state["effective_phase"], state["next_action"]), ("verifying", "verify"))

    def test_resume_preserves_approvals_verification_and_completed_history(self):
        self.configure()
        self.verifying("full")
        tram.verify_run(self.root, self.slug, "test")
        self.review()  # Runtime contract fixture, not evidence of an independent host review.
        tram.transition(self.root, self.slug, "complete")
        path = self.root / ".tram/tasks" / (self.slug + ".json")
        before = path.read_bytes()
        state = tram.start(self.root, self.slug)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((state["effective_phase"], state["next_action"]), ("complete", "finishing"))
        self.assertEqual(state["approvals_valid"], {"prd": True, "plan": True})
        self.assertEqual([x["scope"] for x in state["task"]["approvals"]], ["prd", "plan"])
        self.assertEqual(len(state["task"]["verification"]), 1)
        self.assertEqual(len(state["task"]["reviews"]), 1)

    def test_review_must_use_the_actual_five_rubric_axes(self):
        self.configure()
        self.verifying("full")
        data = self.review_data()
        data["axes"][0]["name"] = "unrelated-dimension"
        path = self.write("wrong-axes.json", json.dumps(data))
        self.assertError("INVALID_REVIEW", tram.review, self.root, self.slug, path)

    def test_perf_light_completes_with_actual_test_evidence_and_reason(self):
        self.configure(perf={"configured": True}, reviewer={"configured": False})
        tram.start(self.root, self.slug, "perf")
        self.assertError("LIGHT_REASON_REQUIRED", tram.transition, self.root, self.slug, "verify", "light")
        tram.transition(self.root, self.slug, "verify", "light", "동작 보존·저위험이며 출력 동일성 테스트가 경계를 덮음")
        record = tram.verify_run(self.root, self.slug, "test")
        self.assertEqual(record["strength"], "light")
        self.assertEqual(record["exit_code"], 0)
        result = tram.transition(self.root, self.slug, "complete")
        self.assertEqual(result["effective_phase"], "complete")

    def test_perf_full_cannot_downgrade_after_defect(self):
        self.configure(perf={"configured": True})
        tram.start(self.root, self.slug, "perf")
        tram.transition(self.root, self.slug, "verify", "full")
        tram.verify_run(self.root, self.slug, "test")
        self.assertError("VERIFICATION_REQUIRED", tram.transition, self.root, self.slug, "complete")
        tram.transition(self.root, self.slug, "implementation-defect")
        self.assertError("FULL_REQUIRED", tram.transition, self.root, self.slug, "verify", "light", "low risk")

    def test_full_route_cannot_request_light(self):
        self.configure()
        self.full()
        self.assertError("FULL_REQUIRED", tram.transition, self.root, self.slug, "verify", "light", "skip review")

    def test_quick_full_defect_retry_keeps_full_and_requires_fresh_review(self):
        self.configure()
        tram.start(self.root, self.slug, "quick")
        tram.transition(self.root, self.slug, "verify", "full")
        tram.verify_run(self.root, self.slug, "test")
        tram.transition(self.root, self.slug, "implementation-defect")
        self.assertError("FULL_REQUIRED", tram.transition, self.root, self.slug, "verify", "light")
        retried = tram.transition(self.root, self.slug, "verify")
        self.assertEqual(retried["task"]["verification_strength"], "full")
        self.assertEqual(retried["task"]["round"], 2)
        tram.verify_run(self.root, self.slug, "test")
        self.assertError("VERIFICATION_REQUIRED", tram.transition, self.root, self.slug, "complete")
        self.review()
        self.assertEqual(tram.transition(self.root, self.slug, "complete")["effective_phase"], "complete")

    def test_two_runtime_processes_cannot_publish_stale_round_evidence(self):
        ready, release = self.root / ".tram/local/ready", self.root / ".tram/local/release"
        code = ("from pathlib import Path; import sys,time; "
                "Path(sys.argv[1]).touch(); deadline=time.monotonic()+8\n"
                "while not Path(sys.argv[2]).exists() and time.monotonic()<deadline: time.sleep(.01)\n")
        self.configure([sys.executable, "-c", code, str(ready), str(release)])
        self.verifying()
        common = [sys.executable, str(RUNTIME)]
        task_args = ["--project", str(self.root), "--slug", self.slug]
        writer = subprocess.Popen(common + ["verify-run", *task_args, "--command", "test"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists(), "verification subprocess did not reach barrier")
            for action in ("implementation-defect", "verify"):
                other = subprocess.run(common + ["transition", *task_args, "--action", action],
                                       capture_output=True, text=True, timeout=5)
                self.assertEqual(other.returncode, 0, other.stdout + other.stderr)
        finally:
            release.touch()
            stdout, stderr = writer.communicate(timeout=10)
        self.assertEqual(writer.returncode, 1, stdout + stderr)
        evidence = json.loads(stdout)["result"]
        self.assertTrue(evidence["stale"])
        self.assertEqual(evidence["round"], 1)
        current = tram.task(self.root, self.slug)
        self.assertEqual(current["round"], 2)
        self.assertEqual(current["phase"], "verifying")
        self.assertError("VERIFICATION_REQUIRED", tram.transition, self.root, self.slug, "complete")

    def test_approval_digest_includes_final_marker_and_upstream(self):
        self.full()
        state = tram.task(self.root, self.slug)
        docs = tram.doc_digests(self.root, state)
        self.assertEqual(state["approvals"][-1]["digest"], docs["plan"])
        self.assertEqual(state["approvals"][-1]["upstream_digest"], docs["prd"])
        self.assertIn("> 상태: 승인", (self.root / f"docs/plan/{self.slug}.md").read_text())

    def test_prd_change_invalidates_downstream_status_is_read_only(self):
        self.configure()
        self.full()
        self.write(f"docs/prd/{self.slug}.md", "changed\n")
        before = self.tree()
        result = tram.status(self.root, self.slug)
        self.assertEqual(result["effective_phase"], "prd_draft")
        self.assertEqual(result["approvals_valid"], {"prd": False, "plan": False})
        self.assertEqual(before, self.tree())
        tram.start(self.root, self.slug)
        state = tram.task(self.root, self.slug)
        self.assertTrue(all(x["invalidated"] for x in state["approvals"]))
        self.assertEqual(state["phase"], "prd_draft")

    def test_plan_change_invalidates_only_plan(self):
        self.full()
        self.write(f"docs/plan/{self.slug}.md", "changed\n")
        result = tram.status(self.root, self.slug)
        self.assertEqual(result["approvals_valid"], {"prd": True, "plan": False})
        self.assertEqual(result["effective_phase"], "plan_draft")

    def test_approval_state_write_failure_never_infers_approval(self):
        tram.start(self.root, self.slug)
        self.write(f"docs/prd/{self.slug}.md", "# 초안\n")
        tram.transition(self.root, self.slug, "submit-prd")
        with patch.object(tram, "save", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                tram.approve(self.root, self.slug, "prd", "승인", "s")
        self.assertIn("확정", (self.root / f"docs/prd/{self.slug}.md").read_text())
        self.assertFalse(tram.status(self.root, self.slug)["approvals_valid"]["prd"])

    def test_quick_completion_and_stale_code(self):
        self.configure()
        self.verifying()
        tram.verify_run(self.root, self.slug, "test")
        tram.transition(self.root, self.slug, "complete")
        self.write("code.py", "value = 2\n")
        before = self.tree()
        self.assertEqual(tram.status(self.root, self.slug)["effective_phase"], "verifying")
        self.assertEqual(before, self.tree())

    def test_failed_command_cannot_complete(self):
        self.configure([sys.executable, "-c", "import sys; print('secret'); sys.exit(7)"])
        self.verifying()
        result = tram.verify_run(self.root, self.slug, "test")
        self.assertEqual(result["exit_code"], 7)
        self.assertError("VERIFICATION_REQUIRED", tram.transition, self.root, self.slug, "complete")
        self.assertNotIn("secret", (self.root / f".tram/tasks/{self.slug}.json").read_text())

    def test_unconfirmed_and_no_required_commands(self):
        tram.start(self.root, self.slug, "quick")
        tram.transition(self.root, self.slug, "verify")
        self.assertError("COMMAND_UNCONFIRMED", tram.verify_run, self.root, self.slug, "unknown")
        self.assertError("VERIFICATION_REQUIRED", tram.transition, self.root, self.slug, "complete")

    def test_command_missing_executable_and_timeout_are_evidence_not_success(self):
        self.configure([str(self.root / "no-such-executable")])
        self.verifying()
        result = tram.verify_run(self.root, self.slug, "test")
        self.assertEqual(result["error"], "EXECUTION_FAILED")
        self.assertIsNone(result["exit_code"])
        self.configure(commands=[{"id": "test", "argv": [sys.executable, "-c", "import time; time.sleep(2)"],
                                  "cwd": ".", "required": True, "confirmed": True, "timeout": 0.02}])
        self.assertEqual(tram.verify_run(self.root, self.slug, "test")["error"], "TIMEOUT")

    def test_shell_metacharacters_are_literal(self):
        marker = self.root / "shell-injection"
        self.configure([sys.executable, "-c", "import sys; assert sys.argv[1].startswith(';')", ";touch " + str(marker)])
        self.verifying()
        self.assertEqual(tram.verify_run(self.root, self.slug, "test")["exit_code"], 0)
        self.assertFalse(marker.exists())

    def test_code_change_during_subprocess_is_stale(self):
        self.configure([sys.executable, "-c", "from pathlib import Path; Path('code.py').write_text('changed')"])
        self.verifying()
        result = tram.verify_run(self.root, self.slug, "test")
        self.assertTrue(result["stale"])
        self.assertError("VERIFICATION_REQUIRED", tram.transition, self.root, self.slug, "complete")

    def test_revision_race_during_command_is_stale_and_lock_is_released(self):
        code = ("import json; from pathlib import Path; p=Path('.tram/tasks/sample-task.json'); "
                "v=json.loads(p.read_text()); v['revision']+=1; p.write_text(json.dumps(v)); "
                "assert not Path('.tram/local/write.lock').exists()")
        self.configure([sys.executable, "-c", code])
        self.verifying()
        self.assertTrue(tram.verify_run(self.root, self.slug, "test")["stale"])

    def test_second_writer_is_refused_and_dead_lock_preserved(self):
        lock = self.write(".tram/local/write.lock", json.dumps({"pid": 999999999, "token": "dead"}))
        before = lock.read_bytes()
        self.assertError("LOCKED", tram.start, self.root, self.slug)
        self.assertEqual(lock.read_bytes(), before)
        snapshot = self.tree()
        tram.status(self.root)
        self.assertEqual(snapshot, self.tree())

    def test_compare_and_swap_rejects_revision(self):
        path = self.root / ".tram/project.json"
        value = tram.load(path)
        self.assertError("REVISION_CONFLICT", tram.save, path, value, value["revision"] - 1)

    def test_profile_and_document_changes_stale_evidence(self):
        self.configure()
        self.verifying("full")
        tram.verify_run(self.root, self.slug, "test")
        self.review()
        self.configure(exclude=["generated/**"])
        self.assertError("VERIFICATION_REQUIRED", tram.transition, self.root, self.slug, "complete")

    def test_deleted_untracked_input_is_fingerprinted(self):
        self.configure(inputs=["src", "missing.file"])
        self.write("src/a.py", "a=1")
        self.verifying()
        before = tram.status(self.root, self.slug)["snapshot"]
        self.write("src/new.py", "new=1")
        after = tram.status(self.root, self.slug)["snapshot"]
        self.assertNotEqual(before, after)
        (self.root / "src/new.py").unlink()
        self.assertEqual(before, tram.status(self.root, self.slug)["snapshot"])

    def test_state_and_excluded_reports_do_not_invalidate_code(self):
        self.configure(inputs=["."], exclude=["reports/**"])
        self.verifying()
        before = tram.status(self.root, self.slug)["snapshot"]
        self.write("reports/out.txt", "output")
        self.write(".tram/local/markers/a", "marker")
        self.assertEqual(before, tram.status(self.root, self.slug)["snapshot"])

    def test_review_requires_fresh_complete_consistent_evidence(self):
        self.configure()
        self.verifying("full")
        for changes in ({"fresh": False}, {"reference": "implementation-1"}, {"score": 90},
                        {"axes": []}, {"blocking": ["actual defect"]}, {"snapshot": {}}, {"round": 0}):
            path = self.write("review.json", json.dumps(self.review_data(**changes)))
            with self.assertRaises(tram.TramError):
                tram.review(self.root, self.slug, path)
        self.review()
        self.assertError("REVIEW_REUSED", self.review)

    def test_design_and_implementation_branches(self):
        self.configure()
        self.verifying("full")
        tram.transition(self.root, self.slug, "implementation-defect")
        self.assertEqual(tram.task(self.root, self.slug)["phase"], "implementing")
        tram.transition(self.root, self.slug, "verify")
        tram.transition(self.root, self.slug, "design-problem")
        result = tram.status(self.root, self.slug)
        self.assertEqual(result["effective_phase"], "plan_draft")
        self.assertTrue(result["approvals_valid"]["prd"])
        self.assertFalse(result["approvals_valid"]["plan"])

    def test_round_budget(self):
        self.configure()
        tram.start(self.root, self.slug, "quick")
        for _ in range(5):
            tram.transition(self.root, self.slug, "verify")
            tram.transition(self.root, self.slug, "implementation-defect")
        self.assertError("ROUND_LIMIT", tram.transition, self.root, self.slug, "verify")

    def test_manual_full_continuation_bypasses_only_full_round_guards(self):
        self.full()
        for _ in range(5):
            tram.transition(self.root, self.slug, "verify", "full")
            tram.transition(self.root, self.slug, "implementation-defect")
        self.assertError("ROUND_LIMIT", tram.transition, self.root, self.slug, "verify", "full")

        state = tram.task(self.root, self.slug)
        state["reviews"] = [
            {"score": 80, "blocking": ["same finding"], "unmet": []},
            {"score": 80, "blocking": ["same finding"], "unmet": []},
            {"score": 80, "blocking": ["same finding"], "unmet": []},
        ]
        tram.save(tram.slug_path(self.root, self.slug), state, state["revision"])
        self.assertError("ROUND_LIMIT", tram.transition, self.root, self.slug, "verify", "full")
        result = tram.transition(self.root, self.slug, "verify", "full", manual_full_continuation=True)
        self.assertEqual(result["task"]["round"], 6)
        tram.transition(self.root, self.slug, "implementation-defect")
        for _ in range(100):
            result = tram.transition(self.root, self.slug, "verify", "full", manual_full_continuation=True)
            self.assertEqual(result["task"]["round"], 7 + _)
            tram.transition(self.root, self.slug, "implementation-defect")

    def test_manual_full_continuation_rejects_other_routes(self):
        tram.start(self.root, self.slug, "quick")
        self.assertError("INVALID_ARGUMENT", tram.transition, self.root, self.slug, "verify", "full",
                         manual_full_continuation=True)

    def test_manual_full_continuation_requires_full_strength(self):
        self.full()
        self.assertError("INVALID_ARGUMENT", tram.transition, self.root, self.slug, "verify", "light",
                         manual_full_continuation=True)

    def test_specialized_routes_require_configuration_and_git(self):
        self.assertError("ADAPTER_UNCONFIGURED", tram.start, self.root, "cov", "coverage")
        self.assertError("ADAPTER_UNCONFIGURED", tram.start, self.root, "perf", "perf")
        self.configure(coverage={"configured": True})
        self.assertError("COVERAGE_PREREQUISITE", tram.start, self.root, "cov", "coverage")

    def test_coverage_clean_entry_allows_test_diff_during_verification(self):
        self.configure(coverage={"configured": True, "adapter": "python-pytest-cov"})
        self.write("tests/test_app.py", "# initial test\n")
        def git(*args):
            return subprocess.run(["git", *args], cwd=self.root, capture_output=True, check=True)
        git("init", "-b", "coverage-work")
        git("add", ".")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
        tram.start(self.root, self.slug, "coverage")
        self.write("tests/test_app.py", "# authorized test addition\n")
        result = tram.transition(self.root, self.slug, "verify")
        self.assertEqual(result["effective_phase"], "verifying")
        self.assertError("COVERAGE_PREREQUISITE", tram.start, self.root, "second-coverage", "coverage")
        for _ in range(7):
            tram.transition(self.root, self.slug, "implementation-defect")
            tram.transition(self.root, self.slug, "verify")
        tram.transition(self.root, self.slug, "implementation-defect")
        self.assertError("ROUND_LIMIT", tram.transition, self.root, self.slug, "verify")

    def test_coverage_checkpoint_requires_current_head_evidence_in_same_round(self):
        # Git commits exist only in this isolated fixture. Review identities are
        # schema fixtures, never claims of independent real host executions.
        self.configure(inputs=["code.py", "tests"],
                       coverage={"configured": True, "adapter": "python-pytest-cov"})
        self.write(".gitignore", ".tram/\nreview.json\n")
        self.write("tests/test_app.py", "# initial test\n")

        def git(*args):
            return subprocess.run(["git", *args], cwd=self.root, capture_output=True,
                                  text=True, check=True).stdout.strip()

        def commit(message):
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "commit", "-m", message)

        git("init", "-b", "coverage-checkpoint-fixture")
        git("add", ".gitignore", "AGENTS.md", "CLAUDE.md", "code.py", "config.json", "tests/test_app.py")
        commit("fixture baseline")
        self.assertEqual(git("status", "--porcelain"), "")
        tram.start(self.root, self.slug, "coverage")
        self.write("tests/test_app.py", "# authorized test addition\n")
        tram.transition(self.root, self.slug, "verify")
        before = tram.status(self.root, self.slug)
        initial = tram.verify_run(self.root, self.slug, "test")
        self.assertEqual(initial["exit_code"], 0)
        self.assertFalse(initial["stale"])
        self.review(reviewer="fixture-reviewer-before", reference="fixture-review-before")
        self.assertEqual(tram.status(self.root, self.slug)["completion_issues"], [])

        git("add", "tests/test_app.py")
        commit("fixture coverage checkpoint")
        after = tram.status(self.root, self.slug)
        self.assertEqual(after["task"]["round"], before["task"]["round"])
        self.assertNotEqual(after["snapshot"]["head"], before["snapshot"]["head"])
        self.assertEqual(after["snapshot"]["files"], before["snapshot"]["files"])
        self.assertError("VERIFICATION_REQUIRED", tram.transition, self.root, self.slug, "complete")
        fresh_test = tram.verify_run(self.root, self.slug, "test")
        self.assertEqual(fresh_test["exit_code"], 0)
        self.assertFalse(fresh_test["stale"])
        self.assertEqual(fresh_test["snapshot"], after["snapshot"])
        self.assertEqual(fresh_test["round"], before["task"]["round"])
        # A fresh test alone cannot replace the review of the previous HEAD.
        self.assertError("VERIFICATION_REQUIRED", tram.transition, self.root, self.slug, "complete")
        self.assertError("STALE_REVIEW", self.review,
                         reviewer="fixture-stale-reviewer", reference="fixture-stale-review",
                         snapshot=before["snapshot"])
        self.review(reviewer="fixture-reviewer-after", reference="fixture-review-after")
        completed = tram.transition(self.root, self.slug, "complete")
        self.assertEqual(completed["effective_phase"], "complete")
        self.assertEqual(completed["task"]["round"], before["task"]["round"])
        self.assertEqual(len(completed["task"]["verification"]), 2)
        self.assertEqual(len(completed["task"]["reviews"]), 2)

    def test_perf_preserves_original_hundred_round_budget(self):
        self.configure(perf={"configured": True, "adapter": "project-benchmark"})
        tram.start(self.root, self.slug, "perf")
        for _ in range(100):
            tram.transition(self.root, self.slug, "verify")
            tram.transition(self.root, self.slug, "implementation-defect")
        self.assertError("ROUND_LIMIT", tram.transition, self.root, self.slug, "verify")

    def test_escalation_and_resume_route_conflict(self):
        tram.start(self.root, self.slug, "quick")
        self.assertError("ROUTE_CONFLICT", tram.start, self.root, self.slug, "full")
        result = tram.transition(self.root, self.slug, "escalate")
        self.assertEqual(result["effective_phase"], "prd_draft")

    def test_status_multiple_tasks_requires_selection(self):
        tram.start(self.root, "first")
        tram.start(self.root, "second")
        result = tram.status(self.root)
        self.assertTrue(result["selection_required"])
        self.assertEqual(len(result["tasks"]), 2)

    def test_invalid_paths_and_symlinks(self):
        for slug in ("../escape", "Upper", "a/b", ""):
            self.assertError("INVALID_SLUG", tram.start, self.root, slug)
        for cwd in ("../outside", "/tmp"):
            self.assertError("INVALID_PATH", self.configure, commands=[{"id": "test", "argv": ["true"], "cwd": cwd, "required": True, "confirmed": True}])
        (self.root / "link").symlink_to(self.root / "code.py")
        self.assertError("SYMLINK", self.configure, inputs=["link"])

    def test_schema_rejection_and_preview_are_read_only(self):
        path = self.root / ".tram/project.json"
        value = json.loads(path.read_text())
        value["schema_version"] = 999
        path.write_text(json.dumps(value))
        before = self.tree()
        self.assertError("SCHEMA_INCOMPATIBLE", tram.status, self.root)
        result = tram.migration_preview(self.root)
        self.assertFalse(result["files"][0]["compatible"])
        self.assertEqual(before, self.tree())

    def test_cli_all_results_and_errors_are_json(self):
        for arguments, ok in ((["status", "--project", str(self.root)], True),
                              (["transition", "--project", str(self.root), "--slug", self.slug, "--action", "complete"], False),
                              (["bogus"], False)):
            process = subprocess.run([sys.executable, str(RUNTIME), *arguments], capture_output=True, text=True)
            self.assertEqual(json.loads(process.stdout)["ok"], ok)
            self.assertEqual(process.stderr, "")

    def test_contract_is_root_free_and_action_help_is_discoverable(self):
        process = subprocess.run([sys.executable, str(RUNTIME), "contract"], cwd=self.root,
                                 capture_output=True, text=True)
        value = json.loads(process.stdout)
        self.assertTrue(value["ok"])
        self.assertEqual(value["result"]["actions"], list(tram.ACTIONS))
        self.assertEqual(len(value["result"]["review_example"]["axes"]), 5)
        process = subprocess.run([sys.executable, str(RUNTIME), "transition", "--help"],
                                 capture_output=True, text=True)
        self.assertIn("implementation-defect", process.stdout)


if __name__ == "__main__":
    unittest.main()
