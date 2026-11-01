"""Managed project text preserves user content and records conflicts."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("tram_install", Path(__file__).resolve().parents[1] / "src/runtime/tram.py")
tram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tram)


class InstallationCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_init_preserves_existing_text_and_is_content_idempotent(self):
        for name in ("AGENTS.md", "CLAUDE.md", ".gitignore"):
            (self.root / name).write_text("사용자 원문\n")
        tram.init(self.root)
        texts = {name: (self.root / name).read_bytes() for name in ("AGENTS.md", "CLAUDE.md", ".gitignore")}
        result = tram.init(self.root)
        self.assertTrue(result["installation"]["linked"])
        for name, text in texts.items():
            self.assertEqual((self.root / name).read_bytes(), text)
            self.assertTrue(text.startswith("사용자 원문\n".encode()))
            self.assertEqual(text.count(tram.BEGIN.encode()), 1)

    def test_candidates_are_not_commands_and_adapters_unconfigured(self):
        (self.root / "package.json").write_text('{"scripts":{"test":"node --test"}}')
        result = tram.init(self.root)["project"]
        self.assertEqual(result["commands"], [])
        self.assertFalse(result["command_candidates"][0]["confirmed"])
        self.assertFalse(result["coverage"]["configured"])
        self.assertFalse(result["perf"]["configured"])
        self.assertFalse(result["reviewer"]["configured"])
        self.assertEqual(result["conventions"], [])

    def test_managed_instructions_locate_plugin_flow_and_release_version(self):
        result = tram.init(self.root)
        block = (self.root / "AGENTS.md").read_text()
        self.assertIn("SKILL.md", block)
        self.assertIn("adapter.md·OS.md·context/flow-rules.md", block)
        self.assertIn("/tram:start", block)
        self.assertEqual(result["installation"]["version"], tram.release_version())
        self.assertEqual(result["installation"]["version"], tram.release_version())
        files = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        tram.init(self.root)
        self.assertEqual(files, {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_modified_block_preserved_on_update_and_unlink(self):
        tram.init(self.root)
        path = self.root / "AGENTS.md"
        text = path.read_text().replace("Tram 플러그인", "사용자가 고친 플러그인")
        path.write_text(text)
        result = tram.init(self.root)
        self.assertFalse(result["installation"]["linked"])
        self.assertIn({"path": "AGENTS.md", "errorCode": "MANAGED_CONFLICT"}, result["installation"]["conflicts"])
        result = tram.unlink(self.root)
        self.assertTrue(result["conflicts"])
        self.assertEqual(path.read_text(), text)

    def test_damaged_duplicate_and_unknown_blocks_preserved(self):
        for text in (tram.BEGIN, tram.END, tram.LINK_BLOCK * 2, tram.LINK_BLOCK):
            with self.subTest(text=text):
                with tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    (root / "AGENTS.md").write_text(text)
                    result = tram.init(root)
                    self.assertTrue(result["installation"]["conflicts"])
                    self.assertEqual((root / "AGENTS.md").read_text(), text)

    def test_unlink_removes_only_intact_link_blocks_and_keeps_state_ignore_docs(self):
        (self.root / "AGENTS.md").write_text("# 사용자의 지침\n")
        tram.init(self.root)
        tram.start(self.root, "work")
        docs = self.root / "docs/prd/work.md"
        docs.parent.mkdir(parents=True)
        docs.write_text("내용")
        ignore = (self.root / ".gitignore").read_bytes()
        task = (self.root / ".tram/tasks/work.json").read_bytes()
        result = tram.unlink(self.root)
        self.assertEqual(result["conflicts"], [])
        self.assertEqual((self.root / "AGENTS.md").read_text(), "# 사용자의 지침\n")
        self.assertEqual((self.root / ".gitignore").read_bytes(), ignore)
        self.assertEqual((self.root / ".tram/tasks/work.json").read_bytes(), task)
        self.assertEqual(docs.read_text(), "내용")
        self.assertEqual(tram.unlink(self.root)["removed_blocks"], [])
        self.assertTrue(tram.init(self.root)["installation"]["linked"])

    def test_ignore_conflict_does_not_persist_raw_output(self):
        (self.root / ".gitignore").write_text(tram.BEGIN + "\nuser rule\n")
        result = tram.init(self.root)
        self.assertIn({"path": ".gitignore", "errorCode": "MANAGED_CONFLICT"}, result["installation"]["conflicts"])
        self.assertFalse(result["project"]["retain_raw_output"])
        self.assertFalse((self.root / ".tram/local/logs").exists())

    def test_legacy_profile_is_preserved(self):
        legacy = self.root / ".codex/project-profile.json"
        legacy.parent.mkdir()
        legacy.write_text('{"coverage":{"adapter":"kover"}}')
        before = legacy.read_bytes()
        result = tram.init(self.root)
        self.assertTrue(result["legacy_profile"])
        self.assertEqual(legacy.read_bytes(), before)
        self.assertFalse(result["project"]["coverage"]["configured"])

    def test_incompatible_schema_update_does_not_touch_user_text(self):
        tram.init(self.root)
        path = self.root / ".tram/installation.json"
        value = json.loads(path.read_text())
        value["schema_version"] = 999
        path.write_text(json.dumps(value))
        text = (self.root / "AGENTS.md").read_bytes()
        with self.assertRaises(tram.TramError) as caught:
            tram.init(self.root)
        self.assertEqual(caught.exception.code, "SCHEMA_INCOMPATIBLE")
        self.assertEqual((self.root / "AGENTS.md").read_bytes(), text)

    def test_symlink_managed_file_is_never_followed(self):
        with tempfile.TemporaryDirectory() as folder:
            outside = Path(folder) / "outside"
            outside.write_text("keep")
            (self.root / "AGENTS.md").symlink_to(outside)
            with self.assertRaises(tram.TramError) as caught:
                tram.init(self.root)
            self.assertEqual(caught.exception.code, "SYMLINK")
            self.assertEqual(outside.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
