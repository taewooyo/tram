"""Safety contracts for Tram's opt-in Git worktree helper."""
import json
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/scripts/worktree.py"
SPEC = importlib.util.spec_from_file_location("worktree_helper", SCRIPT)
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


class WorktreeCli(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.test")
        (self.repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (self.repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "--all")
        self.git("commit", "-m", "base")

    def git(self, *args, cwd=None, check=True):
        result = subprocess.run(["git", "-C", str(cwd or self.repo), *args],
                                capture_output=True, text=True, check=False)
        if check:
            self.assertEqual(0, result.returncode, result.stderr)
        return result

    def call(self, command, *args, project=None, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPT), command, "--project",
                                 str(project or self.repo), *args], capture_output=True,
                                text=True, check=False)
        output = result.stdout if result.returncode == 0 else result.stderr
        payload = json.loads(output)
        self.assertEqual(0 if ok else 2, result.returncode, payload)
        self.assertEqual(1, payload["schema_version"])
        return payload

    def create_worktree(self, branch="tram/task", name="linked"):
        path = self.base / name
        return path, self.call("create", "--path", str(path), "--branch", branch)["result"]

    def test_create_from_commit_preserves_dirty_original_and_reports_missing_tram_state(self):
        (self.repo / "tracked.txt").write_text("user change\n", encoding="utf-8")
        (self.repo / "untracked.txt").write_text("keep local\n", encoding="utf-8")
        (self.repo / "ignored.txt").write_text("private local\n", encoding="utf-8")
        before = self.git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
        before_files = {name: (self.repo / name).read_bytes()
                        for name in ("tracked.txt", "untracked.txt", "ignored.txt")}
        path, result = self.create_worktree()
        after = self.git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
        self.assertEqual(before, after)
        self.assertEqual(before_files, {name: (self.repo / name).read_bytes()
                                        for name in before_files})
        self.assertEqual("base\n", (path / "tracked.txt").read_text())
        self.assertFalse((path / "untracked.txt").exists())
        self.assertFalse((path / "ignored.txt").exists())
        self.assertFalse((path / ".tram").exists())
        self.assertTrue(result["original_dirty_preserved"])
        self.assertEqual({"project_config_exists": False, "tasks_directory_exists": False,
                          "task_records": [],
                          "installation_exists": False, "local_directory_exists": False},
                         result["tram_state"])
        self.assertFalse(result["tram_state_migrated"])
        self.assertIn(str(path), result["resume"])

    def test_create_reports_committed_tram_state_without_migrating_it(self):
        tram = self.repo / ".tram"
        (tram / "tasks").mkdir(parents=True)
        (tram / "local").mkdir()
        (tram / "project.json").write_text('{"schema_version":1}\n', encoding="utf-8")
        (tram / "tasks/demo.json").write_text('{"slug":"demo"}\n', encoding="utf-8")
        (tram / "installation.json").write_text('{"adapter":"fixture"}\n', encoding="utf-8")
        (tram / "local/note.txt").write_text("tracked local note\n", encoding="utf-8")
        self.git("add", ".tram")
        self.git("commit", "-m", "track project metadata fixture")

        path, result = self.create_worktree()
        self.assertTrue((path / ".tram/project.json").is_file())
        self.assertTrue((path / ".tram/tasks/demo.json").is_file())
        self.assertEqual({"project_config_exists": True,
                          "tasks_directory_exists": True,
                          "task_records": [".tram/tasks/demo.json"],
                          "installation_exists": True, "local_directory_exists": True},
                         result["tram_state"])
        self.assertFalse(result["tram_state_migrated"])

    def test_create_rejects_non_git_unborn_detached_and_existing_branch(self):
        unborn = self.base / "unborn"
        unborn.mkdir()
        subprocess.run(["git", "-C", str(unborn), "init", "--initial-branch=main"],
                       capture_output=True, check=True)
        args = ("--path", str(self.base / "unborn-linked"), "--branch", "task")
        result = self.call("create", *args, project=unborn, ok=False)
        self.assertIn("committed HEAD", result["message"])

        result = self.call("create", "--path", str(self.base / "non-git-linked"),
                           "--branch", "task", project=self.base, ok=False)
        self.assertIn("Git 저장소", result["message"])

        detached = self.base / "detached"
        self.git("worktree", "add", "--detach", str(detached), "HEAD")
        self.addCleanup(lambda: self.git("worktree", "remove", "--force", str(detached), check=False))
        result = self.call("create", "--path", str(self.base / "detached-linked"),
                           "--branch", "task", project=detached, ok=False)
        self.assertIn("detached", result["message"])

        self.git("branch", "already-there")
        result = self.call("create", "--path", str(self.base / "taken"),
                           "--branch", "already-there", ok=False)
        self.assertIn("이미 존재", result["message"])

    def test_create_rejects_symlink_and_path_inside_repository(self):
        outside = self.base / "outside"
        outside.mkdir()
        link = self.base / "linked-parent"
        link.symlink_to(outside, target_is_directory=True)
        result = self.call("create", "--path", str(link / "worktree"),
                           "--branch", "task", ok=False)
        self.assertIn("심볼릭 링크", result["message"])
        result = self.call("create", "--path", str(self.repo / "nested"),
                           "--branch", "task", ok=False)
        self.assertIn("바깥", result["message"])

    def test_list_connect_disconnect_and_remove_safely(self):
        path, _ = self.create_worktree()
        listed = self.call("list")["result"]["worktrees"]
        self.assertTrue(any(Path(item["worktree"]).resolve() == path.resolve() for item in listed))
        connected = self.call("connect", "--path", str(path))["result"]
        self.assertEqual(str(path.resolve()), connected["project_root"])
        self.assertIn("저장되지 않습니다", connected["resume"])
        disconnected = self.call("disconnect", "--to", str(self.repo), project=path)["result"]
        self.assertFalse(disconnected["removed"])
        self.assertEqual(str(self.repo.resolve()), disconnected["project_root"])

        (path / "untracked.txt").write_text("keep", encoding="utf-8")
        result = self.call("remove", "--path", str(path), ok=False)
        self.assertIn("삭제하지 않았습니다", result["message"])
        self.assertTrue(path.exists())
        (path / "untracked.txt").unlink()
        (path / "ignored.txt").write_text("keep ignored", encoding="utf-8")
        result = self.call("remove", "--path", str(path), ok=False)
        self.assertIn("삭제하지 않았습니다", result["message"])
        self.assertTrue((path / "ignored.txt").exists())
        (path / "ignored.txt").unlink()
        self.call("remove", "--path", str(path))
        self.assertFalse(path.exists())

    def test_merge_only_suggests_after_clean_preflight_and_never_executes(self):
        path, _ = self.create_worktree()
        (path / "tracked.txt").write_text("feature\n", encoding="utf-8")
        self.git("-C", str(path), "add", "tracked.txt")
        self.git("-C", str(path), "commit", "-m", "feature")
        head = self.git("rev-parse", "HEAD").stdout.strip()
        source_head = self.git("rev-parse", "HEAD", cwd=path).stdout.strip()
        result = self.call("suggest-merge", "--source", str(path), "--expected-branch", "main",
                           "--expected-head", head)["result"]
        self.assertFalse(result["executed"])
        self.assertIn("git -C", result["suggested_command"])
        self.assertIn(source_head, result["suggested_command"])
        self.assertEqual(head, self.git("rev-parse", "HEAD").stdout.strip())

        (self.repo / "other.txt").write_text("dirty\n", encoding="utf-8")
        result = self.call("suggest-merge", "--source", str(path), "--expected-branch", "main",
                           "--expected-head", head, ok=False)
        self.assertIn("tracked 또는 untracked", result["message"])
        self.assertEqual(source_head, self.git("rev-parse", "HEAD", cwd=path).stdout.strip())

    def test_merge_conflict_preflight_never_changes_either_worktree(self):
        path, _ = self.create_worktree()
        (path / "tracked.txt").write_text("feature version\n", encoding="utf-8")
        self.git("-C", str(path), "add", "tracked.txt")
        self.git("-C", str(path), "commit", "-m", "feature")
        (self.repo / "tracked.txt").write_text("main version\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.git("commit", "-m", "main change")
        target_head = self.git("rev-parse", "HEAD").stdout.strip()
        source_head = self.git("rev-parse", "HEAD", cwd=path).stdout.strip()
        target_content = (self.repo / "tracked.txt").read_text()
        source_content = (path / "tracked.txt").read_text()
        result = self.call("suggest-merge", "--source", str(path), "--expected-branch", "main",
                           "--expected-head", target_head, ok=False)
        self.assertIn("포함하지 않거나", result["message"])
        self.assertEqual(target_head, self.git("rev-parse", "HEAD").stdout.strip())
        self.assertEqual(source_head, self.git("rev-parse", "HEAD", cwd=path).stdout.strip())
        self.assertEqual(target_content, (self.repo / "tracked.txt").read_text())
        self.assertEqual(source_content, (path / "tracked.txt").read_text())

    def test_merge_blocks_ignored_path_conflicts_and_stale_expected_head(self):
        path, _ = self.create_worktree()
        (path / "ignored.txt").write_text("feature", encoding="utf-8")
        self.git("-C", str(path), "add", "-f", "ignored.txt")
        self.git("-C", str(path), "commit", "-m", "ignored path")
        (self.repo / "ignored.txt").write_text("local", encoding="utf-8")
        head = self.git("rev-parse", "HEAD").stdout.strip()
        result = self.call("suggest-merge", "--source", str(path), "--expected-branch", "main",
                           "--expected-head", head, ok=False)
        self.assertIn("ignored 파일", result["message"])
        result = self.call("suggest-merge", "--source", str(path), "--expected-branch", "main",
                           "--expected-head", "0" * 40, ok=False)
        self.assertIn("HEAD가 예상값", result["message"])

    def finish(self, source, target=None):
        return HELPER.finish_status(argparse.Namespace(project=str(source),
                                                      target=str(target) if target else None))

    def test_finish_clean_options_preserve_files_refs_heads_index_and_runtime(self):
        path, _ = self.create_worktree()
        (path / "tracked.txt").write_text("feature\n")
        self.git("add", "tracked.txt", cwd=path)
        self.git("commit", "-m", "feature", cwd=path)
        self.git("remote", "add", "origin", "https://example.invalid/private.git")
        (path / ".tram").mkdir()
        (path / ".tram/runtime.json").write_text("preserve runtime")
        self.git("add", ".tram/runtime.json", cwd=path)
        self.git("commit", "-m", "runtime fixture", cwd=path)

        def snapshot():
            states = []
            for root in (self.repo, path):
                index = Path(self.git("rev-parse", "--path-format=absolute", "--git-path", "index", cwd=root).stdout.strip())
                states.append((self.git("rev-parse", "HEAD", cwd=root).stdout,
                               self.git("status", "--porcelain=v1", "--ignored", cwd=root).stdout,
                               {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
                                if p.is_file() and ".git" not in p.relative_to(root).parts},
                               index.read_bytes()))
            return self.git("show-ref").stdout, states

        before = snapshot()
        actual_git = HELPER.git
        calls = []

        def observe_git(root, *args, **kwargs):
            calls.append(args)
            return actual_git(root, *args, **kwargs)

        with mock.patch.object(HELPER, "git", side_effect=observe_git), \
                mock.patch.object(HELPER.shutil, "which", return_value="/fixture/tool"):
            result = self.finish(path, self.repo)
        self.assertEqual(before, snapshot())
        self.assertEqual("available", result["options"]["merge"]["status"])
        self.assertEqual("available", result["options"]["keep"]["status"])
        self.assertEqual("unknown", result["options"]["pr"]["status"])
        self.assertEqual("available", result["options"]["pr"]["local_readiness"])
        self.assertEqual("unknown", result["options"]["pr"]["authentication"])
        self.assertEqual(0, result["source"]["ignored"])
        self.assertIn("Git 객체", result["read_only_note"])
        allowed = {"worktree", "status", "remote", "rev-parse", "diff", "ls-files", "merge-base", "merge-tree"}
        self.assertTrue(calls)
        for args in calls:
            self.assertIn(args[0], allowed)
            if args[0] == "worktree":
                self.assertEqual("list", args[1])
        # Full CLI entry point preserves the existing envelope too.
        result = self.call("finish-status", "--target", str(self.repo), project=path)["result"]
        self.assertEqual("finish-status", result["command"])

    def test_finish_absent_invalid_or_other_repository_target_keeps_other_options(self):
        path, _ = self.create_worktree()
        for target in (None, self.base / "missing"):
            with self.subTest(target=target):
                result = self.finish(path, target)
                self.assertEqual("unknown", result["options"]["merge"]["status"])
                self.assertEqual("available", result["options"]["keep"]["status"])
                self.assertEqual("blocked", result["options"]["pr"]["status"])
        other = self.base / "other"
        self.git("clone", str(self.repo), str(other))
        result = self.finish(path, other)
        self.assertEqual("blocked", result["options"]["merge"]["status"])
        self.assertIn("같은 저장소", result["options"]["merge"]["reason"])

    def test_finish_dirty_untracked_ignored_and_merge_collision(self):
        path, _ = self.create_worktree()
        (path / "tracked.txt").write_text("dirty\n")
        (path / "untracked.txt").write_text("untracked\n")
        (path / "ignored.txt").write_text("ignored\n")
        result = self.finish(path, self.repo)
        self.assertTrue(result["source"]["dirty"])
        self.assertEqual((1, 1, 1), tuple(result["source"][k] for k in ("tracked", "untracked", "ignored")))
        self.assertEqual("blocked", result["options"]["merge"]["status"])
        self.assertIn("미커밋", result["options"]["pr"]["reason"])
        self.assertEqual("available", result["options"]["keep"]["status"])
        self.git("add", "tracked.txt", "untracked.txt", cwd=path)
        self.git("add", "-f", "ignored.txt", cwd=path)
        self.git("commit", "-m", "feature", cwd=path)
        (self.repo / "ignored.txt").write_text("target local\n")
        result = self.finish(path, self.repo)
        self.assertEqual(1, result["target"]["ignored"])
        self.assertFalse(result["target"]["dirty"])
        self.assertIn("ignored 파일", result["options"]["merge"]["reason"])
        (self.repo / "tracked.txt").write_text("target dirty\n")
        result = self.finish(path, self.repo)
        self.assertTrue(result["target"]["dirty"])
        self.assertIn("tracked 또는 untracked", result["options"]["merge"]["reason"])

    def test_finish_pr_missing_remote_tool_and_detached(self):
        path, _ = self.create_worktree()
        actual_which = HELPER.shutil.which
        with mock.patch.object(HELPER.shutil, "which", side_effect=lambda tool: None if tool == "gh" else actual_which(tool)):
            result = self.finish(path)
        self.assertIn("remote 없음", result["options"]["pr"]["reason"])
        self.assertIn("gh 도구 없음", result["options"]["pr"]["reason"])
        self.assertFalse(result["options"]["pr"]["gh_available"])
        self.git("checkout", "--detach", cwd=path)
        result = self.finish(path, self.repo)
        self.assertIsNone(result["source"]["branch"])
        self.assertIn("detached", result["options"]["merge"]["reason"])
        self.assertIn("detached", result["options"]["pr"]["reason"])
        self.assertEqual("available", result["options"]["keep"]["status"])

    def test_finish_failures_nested_symlink_unregistered_never_report_clean(self):
        path, _ = self.create_worktree()
        nested = path / "nested"
        nested.mkdir()
        link = self.base / "alias"
        link.symlink_to(path, target_is_directory=True)
        for source in (nested, link, self.base / "missing"):
            with self.subTest(source=source):
                result = self.finish(source, self.repo)
                self.assertEqual("unknown", result["source"]["status"])
                self.assertIsNone(result["source"]["dirty"])
                self.assertEqual("unknown", result["options"]["keep"]["status"])
        with mock.patch.object(HELPER, "status_entries", side_effect=HELPER.WorktreeError("status failed")):
            result = self.finish(path, self.repo)
        self.assertIsNone(result["source"]["dirty"])
        self.assertIn("status failed", result["options"]["merge"]["reason"])
        with mock.patch.object(HELPER, "listed_worktrees", return_value=[]):
            result = self.finish(path)
        self.assertFalse(result["source"]["registered"])
        self.assertIsNone(result["source"]["dirty"])

    def test_finish_reuses_ancestry_and_preflight_errors(self):
        path, _ = self.create_worktree()
        (self.repo / "tracked.txt").write_text("main advanced\n")
        self.git("add", "tracked.txt")
        self.git("commit", "-m", "advance main")
        result = self.finish(path, self.repo)
        self.assertIn("포함하지 않거나", result["options"]["merge"]["reason"])
        self.git("merge", "main", cwd=path)
        actual_git = HELPER.git

        def failed_preflight(root, *args, **kwargs):
            if args[0] == "merge-tree":
                return subprocess.CompletedProcess(args, 1, b"", b"preflight failed")
            return actual_git(root, *args, **kwargs)

        with mock.patch.object(HELPER, "git", side_effect=failed_preflight):
            result = self.finish(path, self.repo)
        self.assertEqual("blocked", result["options"]["merge"]["status"])
        self.assertIn("preflight", result["options"]["merge"]["reason"])
        with mock.patch.object(HELPER, "merge_suggestion", side_effect=subprocess.TimeoutExpired("git", 10)):
            result = self.finish(path, self.repo)
        self.assertEqual("blocked", result["options"]["merge"]["status"])
        self.assertEqual("available", result["options"]["keep"]["status"])

    def test_finish_remote_failure_does_not_discard_source_or_claim_readiness(self):
        path, _ = self.create_worktree()
        actual_git = HELPER.git

        def failed_remote(root, *args, **kwargs):
            if args[0] == "remote":
                return subprocess.CompletedProcess(args, 1, b"", b"cannot read remote")
            return actual_git(root, *args, **kwargs)

        with mock.patch.object(HELPER, "git", side_effect=failed_remote):
            result = self.finish(path, self.repo)
        self.assertFalse(result["source"]["dirty"])
        self.assertEqual("available", result["options"]["merge"]["status"])
        self.assertEqual("unknown", result["options"]["pr"]["status"])
        self.assertIn("cannot read remote", result["options"]["pr"]["reason"])
        self.assertNotIn("local_readiness", result["options"]["pr"])


if __name__ == "__main__":
    unittest.main()
