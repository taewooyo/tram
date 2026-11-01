#!/usr/bin/env python3
"""Read-only project context inspection and explicit file digest baselines."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "runtime"))
sys.dont_write_bytecode = True
import tram  # noqa: E402

SCHEMA = 1
MAX_OUTPUT = 2_000_000
SENSITIVE_NAMES = (
    ".env*", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "*.pem", "*.key", "*.p12", "*.pfx", "*credential*", "*secret*", "*token*",
)


def git(root: Path, *args: str, timeout: int = 5) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          timeout=timeout, shell=False)


def run_git(root: Path, *args: str, timeout: int = 5) -> subprocess.CompletedProcess | None:
    if not shutil.which("git"):
        return None
    try:
        return git(root, *args, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def safe_relative(root: Path, value: str) -> tuple[str, Path]:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("프로젝트 내부 상대 경로가 필요합니다")
    if PurePosixPath(value).anchor or ".." in PurePosixPath(value).parts:
        raise ValueError("정규화된 프로젝트 상대 경로가 필요합니다")
    path = tram.inside(root, value)
    return PurePosixPath(value).as_posix(), path


def git_roots(root: Path) -> tuple[Path | None, list[str]]:
    warnings = []
    result = run_git(root, "rev-parse", "--show-toplevel")
    if result is None:
        warnings.append("Git을 실행할 수 없어 저장소 상태를 확인하지 못했습니다")
        return None, warnings
    if result.returncode:
        warnings.append("프로젝트가 Git 저장소에 없습니다")
        return None, warnings
    try:
        return Path(os.fsdecode(result.stdout.strip())).resolve(), warnings
    except OSError:
        warnings.append("Git 저장소 경로를 확인하지 못했습니다")
        return None, warnings


def parse_porcelain(data: bytes, git_root: Path, project: Path) -> list[dict]:
    fields = data.split(b"\0")
    entries = []
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            raise ValueError("Git porcelain 상태 결과를 해석할 수 없습니다")
        status = os.fsdecode(record[:2])
        current = os.fsdecode(record[3:])
        previous = None
        if "R" in status or "C" in status:
            if index >= len(fields) or not fields[index]:
                raise ValueError("Git rename 원본 경로가 없습니다")
            previous = os.fsdecode(fields[index])
            index += 1
        current_abs = (git_root / current).resolve()
        previous_abs = (git_root / previous).resolve() if previous is not None else None
        in_project = current_abs.is_relative_to(project) or (
            previous_abs is not None and previous_abs.is_relative_to(project))
        if current_abs.is_relative_to(project):
            current = current_abs.relative_to(project).as_posix()
        if previous_abs is not None and previous_abs.is_relative_to(project):
            previous = previous_abs.relative_to(project).as_posix()
        entries.append({"status": status, "path": current, "previous_path": previous,
                        "in_project": in_project})
    return entries


def workspace(args) -> dict:
    root = tram.root_for(args.project)
    git_root, warnings = git_roots(root)
    if git_root is None:
        return {"command": "workspace", "project_root": str(root), "git_available": bool(shutil.which("git")),
                "git_root": None, "branch": None, "head": None, "unborn": False,
                "detached": False, "dirty": None, "entries": [], "overlaps": [], "warnings": warnings}
    branch_result = run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    head_result = run_git(root, "rev-parse", "--verify", "HEAD")
    status_result = run_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", timeout=15)
    if status_result is None or status_result.returncode:
        warnings.append("Git 작업 트리 상태를 확인하지 못했습니다")
        entries = []
    else:
        entries = parse_porcelain(status_result.stdout, git_root, root)
    branch = os.fsdecode(branch_result.stdout.strip()) if branch_result and branch_result.returncode == 0 else None
    head = os.fsdecode(head_result.stdout.strip()) if head_result and head_result.returncode == 0 else None
    if head_result is None or branch_result is None:
        warnings.append("HEAD 또는 브랜치 상태를 확인하지 못했습니다")
    selected = []
    if args.all:
        selected = entries
    elif args.path:
        requested = [safe_relative(root, item)[0] for item in args.path]
        for entry in entries:
            if not entry["in_project"]:
                continue
            paths = [entry["path"], entry["previous_path"]]
            if any(path and Path(path).is_absolute() is False and
                   any(path == item or path.startswith(item.rstrip("/") + "/") or
                       item.startswith(path.rstrip("/") + "/") for item in requested)
                   for path in paths):
                selected.append(entry)
    unborn = head is None and branch is not None
    if head is None and branch is None:
        warnings.append("HEAD가 없지만 unborn 브랜치인지 확인할 수 없습니다")
    return {"command": "workspace", "project_root": str(root), "git_root": str(git_root),
            "project_is_repository_root": git_root == root, "git_available": True,
            "branch": branch, "head": head, "unborn": unborn,
            "detached": branch is None and head is not None,
            "dirty": any(entry["in_project"] for entry in entries) if status_result and status_result.returncode == 0 else None,
            "repository_dirty": bool(entries) if status_result and status_result.returncode == 0 else None,
            "entry_count": len(entries), "entries": selected, "overlaps": selected,
            "entries_truncated": bool(entries and not args.all and not args.path), "warnings": warnings}


def read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 객체가 아닙니다: {path.name}")
    return value


def mappings(root: Path) -> tuple[str, list[dict], list[dict], list[str]]:
    tram_profile = tram.inside(root, ".tram/project.json")
    legacy_profile = tram.inside(root, ".codex/project-profile.json")
    profile_path = tram_profile if tram_profile.is_file() else legacy_profile
    profile = read_json(profile_path) if profile_path.is_file() else {}
    profile_state = "missing" if not profile_path.is_file() else (
        "null" if profile.get("territories") is None else
        "empty" if profile.get("territories") == [] else "list")
    warnings = []
    profile_entries = profile.get("territories")
    normalized = []
    if profile_entries is not None:
        if not isinstance(profile_entries, list):
            warnings.append("territories가 배열이 아닙니다")
            profile_entries = []
        for entry in profile_entries:
            if not isinstance(entry, dict):
                warnings.append("territories에 객체가 아닌 항목이 있습니다")
                continue
            pattern, slug = entry.get("path"), entry.get("slug")
            if (not isinstance(pattern, str) or not pattern or any(c.isspace() for c in pattern)
                    or PurePosixPath(pattern).is_absolute() or ".." in PurePosixPath(pattern).parts
                    or not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug)):
                warnings.append("잘못된 territories 경로 또는 slug가 있습니다")
                continue
            normalized.append({"path": pattern, "slug": slug, "source": "profile"})
    tsv = tram.inside(root, "docs/domain/_territory.tsv")
    legacy_entries = []
    if tsv.is_file():
        for number, line in enumerate(tsv.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 2 or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", parts[1]):
                warnings.append(f"territory TSV {number}행 형식/slug 오류")
                continue
            legacy_entries.append({"path": parts[0], "slug": parts[1], "source": "tsv"})
    return profile_state, normalized, legacy_entries, warnings


def first_match(path: str, entries: list[dict]) -> dict | None:
    return next((entry for entry in entries if fnmatch.fnmatchcase(path, entry["path"])), None)


def knowledge(args) -> dict:
    root = tram.root_for(args.project)
    state, profile_entries, legacy_entries, warnings = mappings(root)
    requested = [safe_relative(root, item)[0] for item in (args.path or [])]
    matches, legacy_candidates, conflicts, missing = [], [], [], []
    for path in requested:
        profile_match = first_match(path, profile_entries)
        legacy_match = first_match(path, legacy_entries)
        selected = profile_match if profile_match is not None else (
            legacy_match if state in ("missing", "null") else None)
        if profile_match and legacy_match and profile_match["slug"] != legacy_match["slug"]:
            conflicts.append({"path": path, "profile_slug": profile_match["slug"],
                              "legacy_slug": legacy_match["slug"]})
        if legacy_match:
            legacy_candidates.append({"path": path, **legacy_match,
                                      "applied": selected is legacy_match})
        if selected is None:
            missing.append(path)
            continue
        slug = selected["slug"]
        doc = f"docs/domain/{slug}.md"
        doc_path = tram.inside(root, doc)
        nested_index = f"docs/domain/{slug}/README.md"
        try:
            nested_index_path = tram.inside(root, nested_index)
            index = nested_index if nested_index_path.is_file() else None
        except tram.TramError:
            warnings.append(f"심볼릭 링크 domain 색인은 무시합니다: {nested_index}")
            index = None
        if index is None:
            root_index = "docs/domain/README.md"
            try:
                tram.inside(root, root_index)
                index = root_index
            except tram.TramError:
                warnings.append(f"심볼릭 링크 domain 색인은 무시합니다: {root_index}")
        if not doc_path.is_file():
            warnings.append(f"관련 domain 문서가 없습니다: {doc}")
        matches.append({"path": path, **selected, "document": doc, "index": index,
                        "document_exists": doc_path.is_file()})
    return {"command": "knowledge", "project_root": str(root), "profile_state": state,
            "profile_mappings": profile_entries, "legacy_mappings": legacy_entries,
            "matches": matches, "legacy_candidates": legacy_candidates,
            "document_paths": list(dict.fromkeys(item["document"] for item in matches)),
            "index_paths": list(dict.fromkeys(item["index"] for item in matches if item["index"])),
            "conflicts": conflicts, "missing": missing, "warnings": warnings}


def baseline_path(root: Path, slug: str) -> Path:
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        raise ValueError("kebab-case slug가 필요합니다")
    return tram.inside(root, f".tram/local/workspaces/{slug}.json")


def is_sensitive(relative: str) -> bool:
    return any(fnmatch.fnmatchcase(part.lower(), pattern) for part in PurePosixPath(relative).parts
               for pattern in SENSITIVE_NAMES)


def file_facts(root: Path, names: list[str]) -> dict:
    facts = {}
    for name in names:
        relative, path = safe_relative(root, name)
        if any(part in (".git", ".tram") for part in PurePosixPath(relative).parts):
            raise ValueError(f"Git 내부 또는 Tram 작업 기록은 기준선에 포함할 수 없습니다: {relative}")
        if is_sensitive(relative):
            raise ValueError(f"민감 파일은 기준선에 포함할 수 없습니다: {relative}")
        facts[relative] = {"exists": path.is_file(),
                           "sha256": tram.digest(path.read_bytes()) if path.is_file() else None,
                           "executable": bool(path.stat().st_mode & 0o111) if path.is_file() else False}
    return facts


def capture(args) -> dict:
    root = tram.root_for(args.project)
    target = baseline_path(root, args.slug)
    if target.exists():
        raise ValueError("기준선이 이미 있습니다. 기존 파일을 덮어쓰지 않습니다")
    if target.is_symlink() or target.exists():
        raise ValueError("기준선 경로가 이미 사용 중입니다")
    git_root, warnings = git_roots(root)
    if git_root is None:
        raise ValueError("Git 저장소와 ignore 상태를 확인할 수 없어 기준선을 저장하지 않았습니다")
    ignored = run_git(git_root, "check-ignore", "--quiet", "--no-index",
                      str(target.relative_to(git_root)))
    if ignored is None or ignored.returncode != 0:
        raise ValueError("기준선 파일의 Git ignore 적용을 확인하지 못해 저장하지 않았습니다")
    facts = file_facts(root, args.path)
    head_result = run_git(root, "rev-parse", "--verify", "HEAD")
    branch_result = run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    payload = {"schema_version": SCHEMA, "project_root": str(root), "slug": args.slug,
               "captured_at": tram.now(), "git_root": str(git_root),
               "branch": os.fsdecode(branch_result.stdout.strip()) if branch_result and not branch_result.returncode else None,
               "head": os.fsdecode(head_result.stdout.strip()) if head_result and not head_result.returncode else None,
               "files": facts}
    target.parent.mkdir(parents=True, exist_ok=True)
    target = tram.inside(root, f".tram/local/workspaces/{args.slug}.json")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError("기준선 경로가 이미 사용 중입니다")
    with os.fdopen(fd, "wb") as stream:
        stream.write((json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"))
        stream.flush()
        os.fsync(stream.fileno())
    return {"command": "capture", "baseline": target.relative_to(root).as_posix(),
            "file_count": len(facts), "head": payload["head"], "warnings": warnings}


def compare(args) -> dict:
    root = tram.root_for(args.project)
    path = baseline_path(root, args.slug)
    value = read_json(path)
    schema_version = value.get("schema_version")
    if (type(schema_version) is not int or schema_version != SCHEMA
            or value.get("slug") != args.slug or value.get("project_root") != str(root)):
        raise ValueError("기준선 schema 또는 프로젝트 경로가 일치하지 않습니다")
    before = value.get("files")
    if not isinstance(before, dict):
        raise ValueError("기준선 files 항목이 손상되었습니다")
    for name, fact in before.items():
        if not isinstance(fact, dict):
            raise ValueError(f"기준선 파일 항목이 객체가 아닙니다: {name!r}")
        relative, _ = safe_relative(root, name)
        if relative != name or any(part in (".git", ".tram") for part in PurePosixPath(relative).parts):
            raise ValueError(f"기준선 파일 경로가 안전하지 않습니다: {name!r}")
        if is_sensitive(relative):
            raise ValueError(f"기준선에 민감 파일이 포함되어 있습니다: {relative}")
        exists, digest, executable = fact.get("exists"), fact.get("sha256"), fact.get("executable")
        valid_digest = digest is None or (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest))
        if (type(exists) is not bool or type(executable) is not bool or not valid_digest
                or (exists and digest is None) or (not exists and (digest is not None or executable))):
            raise ValueError(f"기준선 파일 항목 형식이 잘못되었습니다: {name!r}")
    requested = [safe_relative(root, item)[0] for item in args.path] if args.path else list(before)
    selected = [name for name in requested if name in before]
    unknown = [name for name in requested if name not in before]
    after = file_facts(root, selected)
    changed, added, deleted, unchanged = [], [], [], []
    for name in selected:
        old, new = before[name], after[name]
        if not old.get("exists") and new["exists"]:
            added.append(name)
        elif old.get("exists") and not new["exists"]:
            deleted.append(name)
        elif old != new:
            changed.append(name)
        else:
            unchanged.append(name)
    return {"command": "compare", "baseline": path.relative_to(root).as_posix(),
            "changed": changed, "added": added, "deleted": deleted, "unchanged": unchanged,
            "untracked_by_baseline": unknown, "not_in_baseline": unknown,
            "warnings": ["해시는 변경 확인용이며 diff·소유권·승인·복원·동시 편집 보호를 제공하지 않습니다"]}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subs = result.add_subparsers(dest="command", required=True)
    for name in ("workspace", "knowledge", "capture", "compare"):
        sub = subs.add_parser(name)
        sub.add_argument("--project", required=True)
        sub.add_argument("--path", action="append", default=[], required=name == "capture")
        if name == "workspace":
            sub.add_argument("--all", action="store_true")
        if name in ("capture", "compare"):
            sub.add_argument("--slug", required=True)
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        result = {"schema_version": SCHEMA, "ok": True, "result": globals()[args.command](args)}
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8", "backslashreplace").decode("utf-8")
        if len(encoded.encode("utf-8")) > MAX_OUTPUT:
            raise ValueError("출력이 너무 큽니다. --path로 범위를 좁히세요")
        print(encoded)
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, tram.TramError) as exc:
        code = exc.code if isinstance(exc, tram.TramError) else "PROJECT_CONTEXT_ERROR"
        message = str(exc)
        error = json.dumps({"schema_version": SCHEMA, "ok": False,
                            "errorCode": code, "message": message}, ensure_ascii=False)
        print(error.encode("utf-8", "backslashreplace").decode("utf-8"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
