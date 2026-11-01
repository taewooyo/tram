import importlib.util
import hashlib
import io
import json
import shutil
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tram_build", ROOT / "scripts/build.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuildTests(unittest.TestCase):
    def copy_source(self, root):
        for name in ("src", "platform", "release", "docs"):
            shutil.copytree(ROOT / name, root / name)
        for name in (*builder.PACKAGE_DOCS, "pyproject.toml"):
            if "/" not in name:
                shutil.copyfile(ROOT / name, root / name)

    def test_reproducible_self_contained_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "build"
            for host in ("codex", "claude"):
                files = builder.inputs(ROOT, host)
                builder.write_tree(output / host, files, False)
                self.assertEqual(builder.write_tree(output / host, files, True), [])
            for host in ("codex", "claude"):
                package = output / host
                manifest = json.loads((package / f".{host}-plugin/plugin.json").read_text())
                self.assertEqual(manifest["name"], "tram")
                release = json.loads((package / "release.json").read_text())
                self.assertEqual(manifest["version"], release["version"])
                self.assertEqual((release["schemaVersion"], release["schemaMin"], release["schemaMax"]), (2, 2, 2))
                self.assertEqual(release["validatedHosts"], [])
                for name in builder.PACKAGE_DOCS:
                    self.assertTrue((package / name).is_file(), name)
                # Developer-only approval records and one-time sync logs do not ship.
                self.assertFalse((package / 'docs/local-sync-preview.md').exists())
                self.assertFalse((package / 'docs/prd').exists())
                self.assertFalse((package / 'docs/plan').exists())
                self.assertTrue((package / "runtime/tram.py").is_file())
                self.assertFalse(any(p.is_symlink() for p in package.rglob("*")))
                hooks = (package / "hooks/hooks.json").read_text()
                self.assertIn("PLUGIN_ROOT", hooks)
                self.assertNotIn(str(ROOT), hooks)

    def test_package_identity_matches_candidate_tree_and_detects_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "codex-package"
            files = builder.inputs(ROOT, "codex")
            builder.write_tree(package, files, False)
            before = builder.package_identity(ROOT, "codex", package)
            self.assertTrue(before["identical"])
            self.assertEqual(before["candidate"]["version"], "0.0.1")
            self.assertEqual(before["candidate"]["schemaVersion"], 2)
            self.assertEqual(before["candidate"]["packageSha256"],
                             before["installed"]["packageSha256"])
            self.assertEqual(before["candidate"]["fileCount"], len(files))

            (package / "skills/start/SKILL.md").write_text("edited cache")
            (package / "user-added.txt").write_text("extra")
            drift = builder.package_identity(ROOT, "codex", package)
            self.assertFalse(drift["identical"])
            self.assertIn("skills/start/SKILL.md", drift["differences"]["changed"])
            self.assertIn("user-added.txt", drift["differences"]["extra"])

    def test_package_identity_refuses_symlink_comparison_root(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            target = directory / "target"
            target.mkdir()
            link = directory / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "real directory"):
                builder.package_identity(ROOT, "codex", link)

    def test_rejects_broken_links_and_placeholders(self):
        for content in (b"[bad](../../escape.md)", b"{{VERSION}}", b"[bad](missing.md)"):
            with self.assertRaises(ValueError):
                builder.validate({"skills/start/SKILL.md": content})

    def test_marketplace_resolves_from_repository_root(self):
        codex = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        claude = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
        self.assertEqual(codex["name"], "tram")
        self.assertEqual(claude["name"], "tram")
        self.assertEqual(codex["plugins"][0]["source"]["path"], "./build/codex")
        self.assertEqual(claude["plugins"][0]["source"], "./build/claude")

    def test_unknown_generated_file_is_preserved_without_partial_write(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "user.txt").write_text("keep")
            with self.assertRaises(ValueError):
                builder.write_tree(folder, {"new.txt": b"generated"}, False)
            self.assertEqual((folder / "user.txt").read_text(), "keep")
            self.assertFalse((folder / "new.txt").exists())

    def test_local_sync_preserves_user_changed_generated_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.copy_source(root)
            builder.sync_local(root, bootstrap=True)
            path = root / ".codex/skills/start/SKILL.md"
            path.write_text("user edited")
            with self.assertRaises(ValueError):
                builder.sync_local(root)
            self.assertEqual(path.read_text(), "user edited")

    def test_bootstrap_backs_up_exact_overwritten_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.copy_source(root)
            old = root / ".codex/skills/start/SKILL.md"
            old.parent.mkdir(parents=True)
            old.write_text("original workspace instructions")
            builder.sync_local(root, bootstrap=True)
            backups = list((root / ".tram/local/backups").glob("tram-local-*/skills/start/SKILL.md"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), "original workspace instructions")
            self.assertNotEqual(old.read_text(), "original workspace instructions")

    def test_third_adapter_seam_does_not_change_common_flow(self):
        # Synthetic adapter proves packaging separation, not real Grok support.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.copy_source(root)
            shutil.copytree(root / "platform/codex", root / "platform/fake")
            (root / "platform/fake/adapter.md").write_text("# Synthetic adapter\nNo real host support.\n")
            first, third = builder.inputs(root, "codex"), builder.inputs(root, "fake")
            for name in first:
                if name.startswith(("skills/", "runtime/", "context/")):
                    self.assertEqual(first[name], third[name])
            self.assertNotEqual(first["adapter.md"], third["adapter.md"])

    def test_rejects_release_version_or_schema_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.copy_source(root)
            path = root / "pyproject.toml"
            original = path.read_text()
            path.write_text(original.replace('version = "0.0.1"', 'version = "0.1.0"'))
            with self.assertRaisesRegex(ValueError, "version mismatch"):
                builder.inputs(root, "codex")
            path.write_text(original)
            release = root / "release/version.json"
            value = json.loads(release.read_text())
            value["schemaMax"] = 1
            release.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "schema range"):
                builder.inputs(root, "codex")

    def test_candidate_archives_have_real_checksums_and_no_operational_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "candidate"
            builder.candidate_artifacts(ROOT, output)
            first = {p.name: p.read_bytes() for p in output.iterdir()}
            builder.candidate_artifacts(ROOT, output)
            self.assertEqual(first, {p.name: p.read_bytes() for p in output.iterdir()})
            for line in first["SHA256SUMS"].decode().splitlines():
                digest, name = line.split("  ")
                self.assertEqual(digest, hashlib.sha256(first[name]).hexdigest())
                self.assertIn("0.0.1", name)
                with zipfile.ZipFile(io.BytesIO(first[name])) as archive:
                    host = "codex" if "codex" in name else "claude"
                    prefix = f"tram-{host}/"
                    metadata = json.loads(archive.read(prefix + "release.json"))
                    self.assertIn(metadata["version"], name)
                    self.assertIn(prefix + "docs/operations.md", archive.namelist())
            readiness = json.loads(first["readiness.json"])
            self.assertEqual(readiness["operationalStatus"], "unverified")
            self.assertEqual(readiness["validatedHosts"], [])
            self.assertEqual(readiness["publicReadiness"], json.loads((ROOT / "release/version.json").read_text())["publicReadiness"])
            self.assertFalse(readiness["published"])


if __name__ == "__main__":
    unittest.main()
