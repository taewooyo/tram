"""CLI contracts for read-only project discovery and explicit digest baselines."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/scripts/project-context.py"


class ProjectContextCli(unittest.TestCase):
    def test_optional_policy_search_preserves_explicit_empty_mapping(self):
        runtime = ROOT / "src/runtime/tram.py"
        result = subprocess.run([sys.executable, str(runtime), "init", "--project", str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        folder = self.root / "docs/domain"
        folder.mkdir(parents=True)
        (folder / "legacy.md").write_text("로그인 정책", encoding="utf-8")
        (folder / "_territory.tsv").write_text("app/* legacy\n", encoding="utf-8")
        before = self.call("knowledge", "--path", "app/login.py")["result"]
        self.assertEqual(before["profile_state"], "empty")
        self.assertEqual(before["matches"], [])
        profile = self.root / ".tram/project.json"
        profile_before = (profile.read_bytes(), profile.stat().st_mtime_ns)
        search = subprocess.run([sys.executable, str(ROOT / "src/scripts/harness.py"), "search",
                                 "--project", str(self.root), "--query", "로그인", "--path", "app/login.py"],
                                capture_output=True, text=True)
        self.assertEqual(search.returncode, 0, search.stdout + search.stderr)
        self.assertEqual(profile_before, (profile.read_bytes(), profile.stat().st_mtime_ns))
        self.assertEqual(before, self.call("knowledge", "--path", "app/login.py")["result"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()

    def call(self, command, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPT), command, "--project", str(self.root), *args],
                                capture_output=True, text=True, check=False)
        stream = result.stdout if result.returncode == 0 else result.stderr
        payload = json.loads(stream)
        self.assertEqual(result.returncode == 0, ok, payload)
        self.assertEqual(payload["schema_version"], 1)
        return payload

    def run_git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, check=True)

    def init_git(self, ignore=True):
        self.run_git("init", "--initial-branch=main")
        if ignore:
            (self.root / ".gitignore").write_text(".tram/local/\n", encoding="utf-8")

    def commit_git(self, message="fixture"):
        self.run_git("add", "--all")
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.test", "commit", "-m", message],
                       capture_output=True, check=True)

    def test_non_git_workspace_reports_unknown_without_writing(self):
        source = self.root / "feature" / "module.py"
        source.parent.mkdir()
        source.write_text("pass\n", encoding="utf-8")
        before = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        result = self.call("workspace", "--path", "feature/module.py")["result"]
        after = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        self.assertIsNone(result["git_root"])
        self.assertIsNone(result["dirty"])
        self.assertEqual([], result["overlaps"])
        self.assertTrue(result["warnings"])
        self.assertEqual(before, after)

    def test_unborn_workspace_and_newline_path_are_read_only(self):
        self.init_git()
        relative = "module/line\nbreak.py"
        file = self.root / relative
        file.parent.mkdir()
        file.write_text("pass\n", encoding="utf-8")
        before = self.run_git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
        result = self.call("workspace", "--path", relative)["result"]
        after = self.run_git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
        self.assertIsNone(result["head"])
        self.assertTrue(result["unborn"])
        self.assertEqual("main", result["branch"])
        self.assertEqual(relative, result["entries"][0]["path"])
        self.assertEqual(result["entries"], result["overlaps"])
        self.assertEqual(before, after)

    def test_workspace_does_not_show_unrelated_parent_repository_changes(self):
        parent = self.root.parent / "parent"
        project = parent / "nested"
        project.mkdir(parents=True)
        self.root = project
        subprocess.run(["git", "-C", str(parent), "init", "--initial-branch=main"],
                       capture_output=True, check=True)
        (parent / "outside.txt").write_text("outside\n", encoding="utf-8")
        (project / "inside.txt").write_text("inside\n", encoding="utf-8")
        result = self.call("workspace", "--path", "inside.txt")["result"]
        self.assertNotEqual(result["git_root"], result["project_root"])
        self.assertTrue(result["dirty"])
        self.assertTrue(result["repository_dirty"])
        self.assertEqual(["inside.txt"], [entry["path"] for entry in result["entries"]])

    def test_workspace_reports_both_paths_for_rename(self):
        self.init_git()
        (self.root / "before.txt").write_text("tracked\n", encoding="utf-8")
        self.commit_git()
        self.run_git("mv", "before.txt", "after.txt")
        result = self.call("workspace", "--path", "after.txt")["result"]
        self.assertEqual(1, len(result["entries"]))
        self.assertEqual("after.txt", result["entries"][0]["path"])
        self.assertEqual("before.txt", result["entries"][0]["previous_path"])

    def test_workspace_reports_detached_head_and_linked_worktree(self):
        self.init_git()
        (self.root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        self.commit_git()
        self.run_git("checkout", "--detach", "HEAD")
        detached = self.call("workspace")["result"]
        self.assertTrue(detached["detached"])
        self.assertIsNone(detached["branch"])

        linked = self.root.parent / "linked-worktree"
        subprocess.run(["git", "-C", str(self.root), "worktree", "add", "--detach",
                        str(linked), "HEAD"], capture_output=True, check=True)
        self.addCleanup(lambda: subprocess.run(["git", "-C", str(self.root), "worktree",
                                                "remove", "--force", str(linked)],
                                               capture_output=True, check=False))
        process = subprocess.run([sys.executable, str(SCRIPT), "workspace", "--project", str(linked)],
                                 capture_output=True, text=True, check=True)
        result = json.loads(process.stdout)["result"]
        self.assertEqual(str(linked.resolve()), result["project_root"])
        self.assertEqual(str(linked.resolve()), result["git_root"])
        self.assertTrue(result["project_is_repository_root"])

    def test_knowledge_respects_profile_states_and_reports_legacy_conflict(self):
        source = "app/auth/login.py"
        (self.root / "docs/domain").mkdir(parents=True)
        (self.root / "docs/domain/legacy.md").write_text("legacy", encoding="utf-8")
        (self.root / "docs/domain/current.md").write_text("current", encoding="utf-8")
        tsv = self.root / "docs/domain/_territory.tsv"
        tsv.write_text("app/* legacy\n", encoding="utf-8")

        result = self.call("knowledge", "--path", source)["result"]
        self.assertEqual("missing", result["profile_state"])
        self.assertEqual("legacy", result["matches"][0]["slug"])
        self.assertEqual(["docs/domain/legacy.md"], result["document_paths"])
        self.assertEqual(["docs/domain/README.md"], result["index_paths"])

        profile = self.root / ".tram/project.json"
        profile.parent.mkdir()
        profile.write_text(json.dumps({"territories": []}), encoding="utf-8")
        result = self.call("knowledge", "--path", source)["result"]
        self.assertEqual("empty", result["profile_state"])
        self.assertEqual([], result["matches"])
        self.assertEqual("legacy", result["legacy_candidates"][0]["slug"])
        self.assertFalse(result["legacy_candidates"][0]["applied"])

        profile.write_text(json.dumps({"territories": [{"path": "app/*", "slug": "current"}]}), encoding="utf-8")
        result = self.call("knowledge", "--path", source)["result"]
        self.assertEqual("current", result["matches"][0]["slug"])
        self.assertEqual("legacy", result["conflicts"][0]["legacy_slug"])

        nested = self.root / "docs/domain/current"
        nested.mkdir(parents=True)
        outside_index = self.root.parent / "outside-index.md"
        outside_index.write_text("outside", encoding="utf-8")
        (nested / "README.md").symlink_to(outside_index)
        result = self.call("knowledge", "--path", source)["result"]
        self.assertEqual(["docs/domain/README.md"], result["index_paths"])

        (nested / "README.md").unlink()
        nested.rmdir()
        outside_dir = self.root.parent / "outside-domain"
        outside_dir.mkdir()
        (outside_dir / "README.md").write_text("outside", encoding="utf-8")
        (self.root / "docs/domain/current").symlink_to(outside_dir, target_is_directory=True)
        result = self.call("knowledge", "--path", source)["result"]
        self.assertEqual(["docs/domain/README.md"], result["index_paths"])

        (self.root / "docs/domain/current").unlink()
        root_index = self.root / "docs/domain/README.md"
        root_index.symlink_to(outside_index)
        result = self.call("knowledge", "--path", source)["result"]
        self.assertEqual([], result["index_paths"])
        self.assertTrue(any("심볼릭 링크" in warning for warning in result["warnings"]))

    def test_invalid_mappings_and_missing_domain_are_reported(self):
        profile = self.root / ".tram/project.json"
        profile.parent.mkdir()
        profile.write_text(json.dumps({"territories": [{"path": "../outside/*", "slug": "bad"}, None]}),
                           encoding="utf-8")
        result = self.call("knowledge", "--path", "src/app.py")["result"]
        self.assertEqual([], result["matches"])
        self.assertEqual("src/app.py", result["missing"][0])
        self.assertGreaterEqual(len(result["warnings"]), 2)

    def test_capture_and_compare_detect_changes_additions_and_deletions(self):
        self.init_git()
        (self.root / ".tram/local").mkdir(parents=True)
        source = self.root / "source.py"
        source.write_text("before\n", encoding="utf-8")
        deleted = self.root / "deleted.py"
        deleted.write_text("remove\n", encoding="utf-8")
        captured = self.call("capture", "--slug", "feature", "--path", "source.py",
                             "--path", "deleted.py", "--path", "later.py")
        self.assertEqual(3, captured["result"]["file_count"])
        source.write_text("after\n", encoding="utf-8")
        deleted.unlink()
        (self.root / "later.py").write_text("new\n", encoding="utf-8")
        compared = self.call("compare", "--slug", "feature")["result"]
        self.assertEqual(["source.py"], compared["changed"])
        self.assertEqual(["later.py"], compared["added"])
        self.assertEqual(["deleted.py"], compared["deleted"])
        self.assertEqual([], compared["untracked_by_baseline"])
        self.assertNotIn("diff", compared)

    def test_compare_detects_executable_bit_changes(self):
        self.init_git()
        (self.root / ".tram/local").mkdir(parents=True)
        target = self.root / "script.sh"
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o644)
        self.call("capture", "--slug", "mode", "--path", "script.sh")
        target.chmod(0o755)
        result = self.call("compare", "--slug", "mode")["result"]
        self.assertEqual(["script.sh"], result["changed"])

    def test_capture_refuses_unignored_storage_sensitive_and_overwrite(self):
        self.init_git(ignore=False)
        (self.root / ".tram/local").mkdir(parents=True)
        (self.root / "source.py").write_text("pass\n", encoding="utf-8")
        result = self.call("capture", "--slug", "feature", "--path", "source.py", ok=False)
        self.assertIn("ignore", result["message"])
        self.assertFalse((self.root / ".tram/local/workspaces/feature.json").exists())

        self.init_git(ignore=True)
        result = self.call("capture", "--slug", "feature", "--path", ".env.local", ok=False)
        self.assertIn("민감", result["message"])
        for unsafe in (".git/config", ".tram/tasks/private.json", ".env/private-key",
                       "token.txt", ".aws/credentials", "keys/server.pem", "keys/client.key",
                       "id_ecdsa", "backup/secrets-prod.json"):
            with self.subTest(path=unsafe):
                result = self.call("capture", "--slug", "blocked", "--path", unsafe, ok=False)
                self.assertTrue(any(word in result["message"] for word in ("민감", "내부", "기록")))
        self.call("capture", "--slug", "feature", "--path", "source.py")
        result = self.call("capture", "--slug", "feature", "--path", "source.py", ok=False)
        self.assertIn("이미", result["message"])

    def test_capture_rejects_symlinks_and_compare_validates_paths(self):
        self.init_git()
        (self.root / ".tram/local").mkdir(parents=True)
        external = self.root.parent / "external.py"
        external.write_text("pass", encoding="utf-8")
        (self.root / "alias.py").symlink_to(external)
        result = self.call("capture", "--slug", "feature", "--path", "alias.py", ok=False)
        self.assertIn("심볼릭 링크", result["message"])
        result = self.call("capture", "--slug", "../escape", "--path", "source.py", ok=False)
        self.assertIn("slug", result["message"])

    def test_compare_rejects_malformed_baseline_file_entries(self):
        self.init_git()
        (self.root / ".tram/local/workspaces").mkdir(parents=True)
        path = self.root / ".tram/local/workspaces/feature.json"
        base = {"schema_version": 1, "project_root": str(self.root.resolve()), "slug": "feature",
                "files": {"source.py": {"exists": True, "sha256": "a" * 64, "executable": False}}}
        for files in ({"source.py": []}, {"../outside.py": base["files"]["source.py"]},
                      {"source.py": {"exists": True, "sha256": None, "executable": False}}):
            with self.subTest(files=files):
                base["files"] = files
                path.write_text(json.dumps(base), encoding="utf-8")
                result = self.call("compare", "--slug", "feature", ok=False)
                self.assertNotIn("Traceback", result["message"])

        base["files"] = {}
        base["schema_version"] = True
        path.write_text(json.dumps(base), encoding="utf-8")
        result = self.call("compare", "--slug", "feature", ok=False)
        self.assertIn("schema", result["message"])

        base["schema_version"] = 1
        base["files"] = {".aws/credentials": {"exists": True, "sha256": "a" * 64,
                                               "executable": False}}
        path.write_text(json.dumps(base), encoding="utf-8")
        result = self.call("compare", "--slug", "feature", ok=False)
        self.assertIn("민감", result["message"])


if __name__ == "__main__":
    unittest.main()
