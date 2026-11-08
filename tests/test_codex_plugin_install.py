"""Exercise Codex's local marketplace installation without touching user settings."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("codex"), "Codex CLI is not installed")
class CodexPluginInstallCase(unittest.TestCase):
    def test_local_marketplace_install_registers_current_package(self):
        local = ROOT / ".tram/local"
        local.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="codex-install-", dir=local) as folder:
            env = os.environ.copy()
            env["CODEX_HOME"] = str(Path(folder) / "codex-home")
            Path(env["CODEX_HOME"]).mkdir()

            def run(*args):
                return subprocess.run(
                    ["codex", *args], cwd=ROOT, env=env, text=True,
                    capture_output=True, check=True, timeout=60,
                )

            marketplace = json.loads(run("plugin", "marketplace", "add", str(ROOT), "--json").stdout)
            self.assertEqual(marketplace["marketplaceName"], "tram")
            installed = json.loads(run("plugin", "add", "tram@tram", "--json").stdout)
            self.assertEqual(installed["pluginId"], "tram@tram")

            listing = json.loads(run("plugin", "list", "--json").stdout)
            self.assertTrue(any(item["pluginId"] == "tram@tram" and item["installed"]
                                and item["enabled"] for item in listing["installed"]))

            version = json.loads((ROOT / "release/version.json").read_text())["version"]
            cached = Path(env["CODEX_HOME"]) / f"plugins/cache/tram/tram/{version}/skills/init/SKILL.md"
            expected = ROOT / "build/codex/skills/init/SKILL.md"
            self.assertTrue(cached.is_file())
            self.assertEqual(cached.read_bytes(), expected.read_bytes())


if __name__ == "__main__":
    unittest.main()
