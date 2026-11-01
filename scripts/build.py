#!/usr/bin/env python3
"""Deterministic, dependency-free Tram package builder. Never edits target projects."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TREES = ("skills", "context", "agents", "runtime", "hooks", "scripts", "templates")
PACKAGE_DOCS = ("OS.md", "README.md", "docs/setup.md", "docs/support.md",
                "docs/release-validation.md",
                "docs/operations.md", "CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md", "LICENSE")


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def tree_identity(files):
    """Return a stable identity for a package tree, independent of filesystem metadata."""
    entries = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    digest = hashlib.sha256(encoded(entries)).hexdigest()
    return {"sha256": digest, "fileCount": len(entries), "files": entries}


def package_identity(root, host, compare_directory=None):
    """Identify a generated package and optionally compare an installed package directory."""
    expected = inputs(root, host)
    release = json.loads(expected["release.json"])
    identity = tree_identity(expected)
    candidate = {
        "host": host,
        "version": release["version"],
        "schemaVersion": release["schemaVersion"],
        "packageSha256": identity["sha256"],
        "fileCount": identity["fileCount"],
        "pluginManifestSha256": identity["files"][f".{host}-plugin/plugin.json"],
    }
    if compare_directory is None:
        return {"candidate": candidate, "identical": None}

    directory = Path(compare_directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"comparison directory must be a real directory: {directory}")
    actual = {}
    symlinks = []
    for path in directory.rglob("*"):
        if path.is_symlink():
            symlinks.append(path.relative_to(directory).as_posix())
        elif path.is_file():
            actual[path.relative_to(directory).as_posix()] = path.read_bytes()
    actual_identity = tree_identity(actual)
    expected_hashes = identity["files"]
    actual_hashes = actual_identity["files"]
    missing = sorted(set(expected_hashes) - set(actual_hashes))
    extra = sorted(set(actual_hashes) - set(expected_hashes))
    changed = sorted(name for name in set(expected_hashes) & set(actual_hashes)
                     if expected_hashes[name] != actual_hashes[name])
    installed_release = {}
    installed_manifest = {}
    try:
        installed_release = json.loads((directory / "release.json").read_text())
    except (OSError, json.JSONDecodeError):
        pass
    try:
        installed_manifest = json.loads(
            (directory / f".{host}-plugin/plugin.json").read_text())
    except (OSError, json.JSONDecodeError):
        pass
    identical = not (missing or extra or changed or symlinks)
    return {
        "candidate": candidate,
        "installed": {
            "path": str(directory.resolve()),
            "version": installed_release.get("version", installed_manifest.get("version")),
            "packageSha256": actual_identity["sha256"],
            "fileCount": actual_identity["fileCount"],
        },
        "identical": identical,
        "differences": {"missing": missing, "changed": changed, "extra": extra,
                        "symlinks": sorted(symlinks)},
    }


def inputs(root, host):
    files = {}
    for tree in TREES:
        source = root / "src" / tree
        if not source.is_dir():
            raise ValueError(f"missing source: src/{tree}")
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"source symlink forbidden: {path.relative_to(root)}")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                files[path.relative_to(root / "src").as_posix()] = path.read_bytes()
    if "runtime/tram.py" not in files or "skills/start/SKILL.md" not in files:
        raise ValueError("runtime and public skills required")
    release = json.loads((root / "release/version.json").read_text())
    version = release["version"]
    project = (root / "pyproject.toml").read_text()
    section = re.search(r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)", project)
    declared = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', section[1] if section else "")
    if not declared or declared[1] != version:
        raise ValueError("pyproject/release version mismatch")
    if any(release.get(key) != 2 for key in ("schemaVersion", "schemaMin", "schemaMax")):
        raise ValueError("candidate schema range must be 2")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?", version):
        raise ValueError("invalid release version")
    manifest = json.loads((root / f"platform/{host}/plugin.json").read_text())
    manifest["version"] = version
    files[f".{host}-plugin/plugin.json"] = encoded(manifest)
    files["hooks/hooks.json"] = (root / f"platform/{host}/hooks.json").read_bytes()
    files["adapter.md"] = (root / f"platform/{host}/adapter.md").read_bytes()
    for name in PACKAGE_DOCS:
        text = (root / name).read_text()
        # Repository documentation targets src/, installed packages strip that layer.
        text = re.sub(r"(\]\((?:\.\./)*)src/", r"\1", text)
        if name == "README.md":
            # Images/marketplaces belong to the source repository, not installed roots.
            text = re.sub(r"<picture>.*?</picture>", "", text, flags=re.S)
            text = re.sub(r"\[([^\]]+)\]\(((?:docs/diagrams/|build/|\.agents/|\.claude-plugin/)[^)]+)\)",
                          r"\1 (`\2`, 소스 저장소 전용)", text)
        files[name] = text.encode()
    files["release.json"] = encoded({**release, "host": host})
    validate(files)
    return files


def validate(files):
    """Validate local Markdown file links and JSON; reject forgotten build placeholders."""
    for name, data in files.items():
        if name.endswith(".json"):
            json.loads(data)
        if not name.endswith((".md", ".sh", ".json", ".yaml", ".py")):
            continue
        content = data.decode("utf-8")
        if re.search(r"\{\{(?:PLUGIN_ROOT|VERSION|HOST)\}\}|@@(?:PLUGIN_ROOT|VERSION|HOST)@@", content):
            raise ValueError(f"unresolved placeholder: {name}")
        if name.endswith(".md"):
            prose = re.sub(r"```.*?```|`[^`\n]*`", "", content, flags=re.S)
            for target in re.findall(r"\[[^\]\n]*\]\(([^)\s]+)\)", prose):
                if target.startswith(("http:", "https:", "#", "mailto:")):
                    continue
                target = target.split("#")[0]
                # Target-project artifacts are intentionally not bundled.
                if not target or "<" in target or "*" in target:
                    continue
                resolved = Path(name).parent / target
                parts = []
                for part in resolved.parts:
                    if part == "..":
                        if not parts:
                            raise ValueError(f"link escapes package: {name}: {target}")
                        parts.pop()
                    elif part != ".":
                        parts.append(part)
                canonical = "/".join(parts)
                if canonical not in files and not any(p.startswith(canonical + "/") for p in files):
                    raise ValueError(f"broken package link: {name}: {target}")


def write_tree(directory, files, check):
    differences = []
    if directory.is_symlink() or any(p.is_symlink() for p in directory.rglob("*")):
        raise ValueError(f"generated output symlink forbidden: {directory}")
    existing = {p.relative_to(directory).as_posix(): p for p in directory.rglob("*") if p.is_file()} if directory.exists() else {}
    extras = set(existing) - set(files)
    if extras and not check:
        raise ValueError(f"unexpected files in generated output; inspect before removal: {sorted(extras)}")
    for name, data in files.items():
        path = directory / name
        if not path.exists() or path.read_bytes() != data:
            differences.append(str(path))
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
    differences.extend(str(existing[n]) for n in sorted(extras))
    return differences


def build(root=ROOT, output=None, check=False):
    output = output or root / "build"
    output = Path(output)
    if output.is_symlink():
        raise ValueError("output symlink forbidden")
    output = output.resolve()
    if output == root.resolve() or output == root.parent.resolve() or output == Path("/"):
        raise ValueError("output must be a dedicated generated directory")
    if output.is_symlink():
        raise ValueError("output symlink forbidden")
    differences, checksums = [], {}
    for host in ("codex", "claude"):
        files = inputs(root, host)
        differences.extend(write_tree(output / host, files, check))
        checksums.update({f"build/{host}/{name}": hashlib.sha256(data).hexdigest() for name, data in files.items()})
    source_paths = [root / name for name in PACKAGE_DOCS] + [root / "scripts/build.py", root / "release/version.json", root / "pyproject.toml"]
    for folder in (root / "src", root / "platform"):
        source_paths.extend(p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    checksums.update({p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths})
    digest = root / "release/checksums.json"
    payload = encoded({"algorithm": "sha256", "files": checksums})
    if not digest.exists() or digest.read_bytes() != payload:
        differences.append(str(digest))
        if not check:
            digest.write_bytes(payload)
    return differences


def sync_local(root=ROOT, check=False, bootstrap=False):
    """Explicit workspace-only view; retain unowned files and detect edited generated files."""
    directory = root / ".codex"
    inventory = directory / "tram-generated.json"
    if directory.is_symlink() or inventory.is_symlink():
        raise ValueError("local generated view symlink forbidden")
    old = json.loads(inventory.read_text()) if inventory.exists() else {}
    if not old and not bootstrap:
        raise ValueError("local view needs explicit --bootstrap-local on first extraction")
    files = inputs(root, "codex")
    files.pop(".codex-plugin/plugin.json")
    # Local registrations use a concrete project-relative path, not plugin-only env vars.
    hooks = files.pop("hooks/hooks.json").decode().replace("${PLUGIN_ROOT}", "${CODEX_PROJECT_DIR:-.}/.codex")
    files["hooks.json"] = hooks.encode()
    files["project-profile.json"] = encoded({"version": 1, "contextMappings": [
        {"path": "docs/**", "card": ".codex/context/doc-conventions.md"}],
        "coverage": {"adapter": "python-pytest-cov", "target": 85, "source": "src", "testPaths": ["tests"]}})
    differences = []
    for name, data in files.items():
        path = directory / name
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent.is_relative_to(directory)):
            raise ValueError(f"local symlink forbidden: {name}")
        actual = path.read_bytes() if path.exists() else None
        if actual == data:
            continue
        if name in old and actual is not None and hashlib.sha256(actual).hexdigest() != old[name]:
            raise ValueError(f"user changed generated local file; preserve and resolve: {name}")
        if name not in old and actual is not None and not bootstrap:
            raise ValueError(f"unowned local file: {name}")
        differences.append(str(path))
    if not check:
        overwritten = [directory / name for name, data in files.items()
                       if (directory / name).exists() and (directory / name).read_bytes() != data]
        if overwritten:
            backup_root = root / ".tram/local/backups"
            if any(path.is_symlink() for path in (root / ".tram", root / ".tram/local", backup_root)):
                raise ValueError("local backup symlink forbidden")
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = Path(tempfile.mkdtemp(prefix="tram-local-", dir=backup_root))
            for original in overwritten:
                saved = backup / original.relative_to(directory)
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, saved)
            (backup / "checksums.json").write_bytes(encoded({
                p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in overwritten}))
        for name, data in files.items():
            path = directory / name
            if not path.exists() or path.read_bytes() != data:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        inventory.write_bytes(encoded({name: hashlib.sha256(data).hexdigest() for name, data in files.items()}))
    return differences


def candidate_artifacts(root, directory):
    """Produce reviewable archives, without publishing or claiming host completion."""
    release = json.loads((root / "release/version.json").read_text())
    artifacts = {}
    for host in ("codex", "claude"):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(inputs(root, host).items()):
                entry = zipfile.ZipInfo(f"tram-{host}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, data)
        artifacts[f"tram-{release['version']}-{host}-candidate.zip"] = payload.getvalue()
    artifacts["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(artifacts.items())).encode()
    artifacts["readiness.json"] = encoded({
        "version": release["version"], "schemaMin": release["schemaMin"], "schemaMax": release["schemaMax"],
        "operationalStatus": "unverified", "validatedHosts": [],
        "reason": "No complete native lifecycle manifest is bundled with this candidate.",
        "publicReadiness": release["publicReadiness"], "published": False})
    write_tree(Path(directory), artifacts, False)
    return sorted(artifacts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check checked-in outputs without writing")
    parser.add_argument("--output", type=Path, help="dedicated package output directory")
    parser.add_argument("--local", action="store_true", help="also refresh this repository's .codex generated view")
    parser.add_argument("--bootstrap-local", action="store_true", help="explicitly replace approved legacy workspace assets on first extraction")
    parser.add_argument("--archive-dir", type=Path, help="write versioned candidate ZIPs, SHA256SUMS and unverified readiness report; never publish")
    parser.add_argument("--identity", action="store_true", help="print candidate package version and deterministic SHA-256 identity without writing")
    parser.add_argument("--host", choices=("codex", "claude"), help="host package to identify or compare")
    parser.add_argument("--compare-package", type=Path, help="compare a candidate with an existing unpacked plugin package directory")
    args = parser.parse_args()
    try:
        if args.identity or args.compare_package:
            if args.local or args.bootstrap_local or args.archive_dir or args.output or args.check:
                raise ValueError("identity comparison cannot be combined with build/write options")
            if args.compare_package and not args.host:
                raise ValueError("--compare-package requires --host codex|claude")
            if args.compare_package:
                result = package_identity(ROOT, args.host, args.compare_package)
            elif args.host:
                result = package_identity(ROOT, args.host)
            else:
                result = {host: package_identity(ROOT, host)["candidate"]
                          for host in ("codex", "claude")}
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        differences = build(output=args.output, check=args.check)
        if args.local or args.bootstrap_local:
            differences += sync_local(check=args.check, bootstrap=args.bootstrap_local)
        if args.archive_dir:
            if args.check:
                raise ValueError("--archive-dir cannot be combined with --check")
            candidate_artifacts(ROOT, args.archive_dir)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return 1
    if args.check and differences:
        print("generated outputs differ:\n" + "\n".join(differences), file=sys.stderr)
        return 1
    print("Tram packages checked" if args.check else "Tram packages built")
    return 0


if __name__ == "__main__":
    sys.exit(main())
