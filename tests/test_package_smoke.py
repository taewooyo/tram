"""Actual packaged runtime on two fixture stacks; not native agent E2E evidence."""
import json
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackageSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Exercise candidate sources, independent of stale checked-in build outputs.
        spec = importlib.util.spec_from_file_location("package_smoke_build", ROOT / "scripts/build.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        cls.package_temp = tempfile.TemporaryDirectory()
        cls.packages = Path(cls.package_temp.name)
        for host in ("codex", "claude"):
            builder.write_tree(cls.packages / host, builder.inputs(ROOT, host), False)

    @classmethod
    def tearDownClass(cls):
        cls.package_temp.cleanup()

    def call(self, package, project, *args):
        result = subprocess.run([sys.executable, str(package / "runtime/tram.py"),
                                 *args, "--project", str(project)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)["result"]

    def observe(self, package, project, *args):
        result = subprocess.run([sys.executable, str(package / "scripts/harness.py"),
                                 *args, "--project", str(project)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)["result"]

    def test_both_packages_ship_provenance_and_complex_plan_contracts(self):
        for host in ("codex", "claude"):
            with self.subTest(host=host):
                package = self.packages / host
                prd = (package / "skills/prd/SKILL.md").read_text()
                reviewer = (package / "agents/reviewer.md").read_text()
                plan = (package / "skills/plan/SKILL.md").read_text()
                experience = (package / "context/start-experience.md").read_text()
                self.assertIn("원 요청 요약·결정·가정·근거·미결정", prd)
                self.assertIn("[의도 출처와 판단 근거]", reviewer)
                self.assertIn("전체 대화 원문", reviewer)
                self.assertIn("복잡한 구현의 실행 정합성", plan)
                self.assertIn("공유 자원이 병렬 처리로 충돌", plan)
                self.assertIn("Reviewer에게 전달할 의도 근거", experience)

    def test_packaged_finishing_entrypoint_and_cards(self):
        if not shutil.which("git"):
            self.skipTest("Git required for finish-status fixture")
        for host in ("codex", "claude"):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as temp:
                package = self.packages / host
                project = Path(temp) / "source with spaces"
                project.mkdir()
                for argv in (("git", "init", "-b", "main"),
                             ("git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                              "commit", "--allow-empty", "-m", "fixture")):
                    result = subprocess.run(argv, cwd=project, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project,
                                        capture_output=True, text=True, check=True).stdout
                result = subprocess.run(
                    [sys.executable, str(package / "scripts/worktree.py"),
                     "finish-status", "--project", str(project)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                envelope = json.loads(result.stdout)
                self.assertTrue(envelope["ok"])
                state = envelope["result"]
                self.assertEqual(state["command"], "finish-status")
                self.assertEqual(state["source"]["path"], str(project.resolve()))
                self.assertEqual(state["source"]["head"], before.strip())
                self.assertIsNone(state["target"])
                self.assertEqual(set(state["options"]), {"merge", "pr", "keep"})
                self.assertEqual(state["options"]["merge"]["status"], "unknown")
                self.assertEqual(state["options"]["keep"]["status"], "available")
                self.assertEqual(state["options"]["pr"]["authentication"], "unknown")
                for option in state["options"].values():
                    self.assertTrue(option["reason"])
                    self.assertTrue(option["next_action"])
                self.assertFalse(state["executed"])
                self.assertFalse((project / ".tram").exists())
                after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project,
                                       capture_output=True, text=True, check=True).stdout
                self.assertEqual(before, after)
                for skill, anchor in (("init", "#선택형-프로젝트-도입-조사"),
                                      ("start", "#worktree-마무리와-재개"),
                                      ("impl", "#변경-관련-문서-점검과-보고"),
                                      ("quick", "#변경-관련-문서-점검과-보고"),
                                      ("verify", "#변경-관련-문서-점검과-보고")):
                    self.assertIn(anchor, (package / "skills" / skill / "SKILL.md").read_text())
                self.assertIn("## worktree 마무리와 재개",
                              (package / "context/start-experience.md").read_text())
                self.assertIn("## 선택형 프로젝트 도입 조사",
                              (package / "context/project-experience.md").read_text())

    def test_two_packages_two_project_stacks(self):
        for host in ("codex", "claude"):
            for stack in ("python", "node"):
                with self.subTest(host=host, stack=stack), tempfile.TemporaryDirectory() as temp:
                    project = Path(temp) / "project with spaces"
                    shutil.copytree(ROOT / "tests/fixtures" / stack, project)
                    package = self.packages / host
                    context = subprocess.run(
                        [sys.executable, str(package / "scripts/project-context.py"),
                         "workspace", "--project", str(project)],
                        capture_output=True, text=True)
                    self.assertEqual(context.returncode, 0, context.stdout + context.stderr)
                    self.assertEqual(json.loads(context.stdout)["result"]["project_root"], str(project.resolve()))
                    self.assertFalse((package / "runtime/__pycache__").exists())
                    worktree_help = subprocess.run(
                        [sys.executable, str(package / "scripts/worktree.py"), "--help"],
                        capture_output=True, text=True)
                    self.assertEqual(worktree_help.returncode, 0,
                                     worktree_help.stdout + worktree_help.stderr)
                    self.assertIn("Git worktree lifecycle", worktree_help.stdout)
                    linked = self.call(package, project, "init")
                    self.assertEqual(linked["installation"]["adapter"], host)
                    argv = [sys.executable, "-m", "unittest", "discover"] if stack == "python" else ["node", "--test"]
                    if stack == "node" and not shutil.which("node"):
                        self.skipTest("Node required for Node fixture, unavailable in this environment")
                    config = project / "config.json"
                    config.write_text(json.dumps({"commands": [{"id": "test", "argv": argv,
                        "cwd": ".", "confirmed": True, "required": True}]}))
                    self.call(package, project, "configure", "--file", str(config))
                    self.call(package, project, "start", "--slug", "smoke", "--route", "quick")
                    # Optional observation must not mutate task/profile or weaken gates.
                    before_observation = self.call(package, project, "status", "--slug", "smoke")
                    tracked = [project / ".tram/project.json", project / ".tram/tasks/smoke.json"]
                    old_bytes = [(p.read_bytes(), p.stat().st_mtime_ns) for p in tracked]
                    recommendation = self.observe(package, project, "recommend", "--slug", "smoke",
                                                  "--request", "작은 문구 변경", "--omit", "test")
                    self.assertIn("REQUIRED_CHECK_OMISSION_PROPOSED", json.dumps(recommendation))
                    self.observe(package, project, "show", "--slug", "smoke")
                    self.assertEqual(old_bytes, [(p.read_bytes(), p.stat().st_mtime_ns) for p in tracked])
                    after_observation = self.call(package, project, "status", "--slug", "smoke")
                    self.assertEqual(before_observation["completion_issues"], after_observation["completion_issues"])
                    self.assertEqual(before_observation["snapshot"], after_observation["snapshot"])
                    self.call(package, project, "transition", "--slug", "smoke", "--action", "verify")
                    evidence = self.call(package, project, "verify-run", "--slug", "smoke", "--command", "test")
                    self.assertEqual(evidence["exit_code"], 0)
                    result = self.call(package, project, "transition", "--slug", "smoke", "--action", "complete")
                    self.assertEqual(result["effective_phase"], "complete")
                    before = {p.relative_to(project): (p.read_bytes(), p.stat().st_mtime_ns) for p in project.rglob("*") if p.is_file()}
                    self.call(package, project, "status", "--slug", "smoke")
                    after = {p.relative_to(project): (p.read_bytes(), p.stat().st_mtime_ns) for p in project.rglob("*") if p.is_file()}
                    self.assertEqual(before, after)
                    # Changed code invalidates even an already-completed task.
                    app = project / ("app.py" if stack == "python" else "app.js")
                    app.write_text(app.read_text() + "\n")
                    changed = self.call(package, project, "status", "--slug", "smoke")
                    self.assertNotEqual(changed["effective_phase"], "complete")
                    # Full route uses actual packaged CLI and real fixture tests.
                    # No fabricated review is submitted; independent review remains required.
                    state = self.call(package, project, "start", "--slug", "full-smoke")
                    self.assertEqual(state["next_action"], "prd")
                    for scope, next_action in (("prd", "plan"), ("plan", "impl")):
                        document = project / "docs" / scope / "full-smoke.md"
                        document.parent.mkdir(parents=True, exist_ok=True)
                        document.write_text("# Package smoke fixture document\n")
                        state = self.call(package, project, "transition", "--slug", "full-smoke",
                                          "--action", "submit-" + scope)
                        self.assertEqual(state["next_action"], "approve-" + scope)
                        self.call(package, project, "approve", "--slug", "full-smoke", "--scope", scope,
                                  "--quote", "Fixture approval", "--session", "fixture-user-session")
                        state = self.call(package, project, "start", "--slug", "full-smoke")
                        self.assertEqual(state["next_action"], next_action)
                        self.assertTrue(state["approvals_valid"][scope])
                    task_path = project / ".tram/tasks/full-smoke.json"
                    before_resume = task_path.read_bytes()
                    self.call(package, project, "start", "--slug", "full-smoke")
                    self.assertEqual(task_path.read_bytes(), before_resume)
                    self.call(package, project, "transition", "--slug", "full-smoke", "--action", "verify")
                    evidence = self.call(package, project, "verify-run", "--slug", "full-smoke", "--command", "test")
                    self.assertEqual(evidence["exit_code"], 0)
                    self.assertEqual(evidence["strength"], "full")
                    state = self.call(package, project, "status", "--slug", "full-smoke")
                    self.assertEqual(state["effective_phase"], "verifying")
                    self.assertIn("INDEPENDENT_REVIEW_REQUIRED", state["completion_issues"])
                    self.assertEqual(state["task"]["reviews"], [])
                    self.call(package, project, "unlink")
                    self.assertTrue((project / ".tram/tasks/smoke.json").exists())


if __name__ == "__main__":
    unittest.main()
