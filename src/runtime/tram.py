#!/usr/bin/env python3
"""Tram project-local state runtime (Python 3.10+, no dependencies).

Approval quotes and native review references are caller attestations, not identity
authentication. Only this runtime executes and records test command evidence.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fnmatch
import ctypes
import struct
try:
    import fcntl
except ImportError:  # Read-only diagnosis remains available on non-POSIX hosts.
    fcntl = None
import selectors
import signal
import time
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

SCHEMA = 2
READ_LEGACY = False
CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv", "node_modules"}
DIAGNOSTICS = {"enabled": False, "max_bytes_per_stream": 262144, "retention_days": 7, "max_project_bytes": 52428800}
METRICS = {"enabled": True, "retention_days": 30, "max_project_bytes": 10485760}
ROUTES = ("full", "quick", "coverage", "perf")
ROUND_LIMITS = {"full": 5, "quick": 5, "coverage": 8, "perf": 100}
REVIEW_AXES = ("correctness", "tests", "reuse", "simplicity", "conventions")
ACTIONS = ("submit-prd", "submit-plan", "implement", "verify", "complete",
           "implementation-defect", "design-problem", "requirements-problem", "escalate")
PHASES = ("prd_draft", "prd_review", "plan_draft", "plan_review",
          "implementing", "verifying", "complete")
BEGIN = "<!-- tram:begin -->"
END = "<!-- tram:end -->"
LINK_BLOCK = (BEGIN + "\n이 프로젝트는 설치된 Tram 플러그인의 개발 흐름을 사용합니다.\n"
              "에이전트의 설치된 스킬 목록에서 Tram start/status 스킬을 찾아 SKILL.md를 읽으세요.\n"
              "Claude Code에서는 /tram:start·/tram:status, Codex에서는 설치된 Tram start/status 스킬을 사용합니다.\n"
              "스킬 파일 위치로 플러그인 root를 찾고 adapter.md·OS.md·context/flow-rules.md를 읽으세요.\n"
              "프로젝트별 설정은 .tram/project.json, 작업 기록은 .tram/tasks/에 있습니다.\n"
              "새 기능·고위험·설계 변경은 PRD 확정과 Plan 승인 후 구현하고, 동작 변경은 테스트와 함께 검증합니다.\n"
              + END + "\n")
IGNORE_BLOCK = BEGIN + "\n.tram/local/\n" + END + "\n"


class TramError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def fail(code, message, **details):
    raise TramError(code, message, **details)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def release_version():
    tool_root = Path(__file__).resolve().parent.parent
    for path in (tool_root / "release.json", tool_root.parent / "release/version.json"):
        if path.is_file():
            try:
                version = json.loads(path.read_text())["version"]
            except (ValueError, KeyError, TypeError):
                fail("INVALID_RELEASE", "릴리스 메타데이터 version이 잘못되었습니다")
            if isinstance(version, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version):
                return version
            fail("INVALID_RELEASE", "릴리스 version 형식이 잘못되었습니다")
    fail("RELEASE_NOT_FOUND", "패키지 release.json 또는 소스 release/version.json이 필요합니다")


def release_adapter():
    path = Path(__file__).resolve().parent.parent / "release.json"
    if not path.is_file():
        return "unconfigured"
    value = json.loads(path.read_text()).get("host")
    if not isinstance(value, str) or not value:
        fail("INVALID_RELEASE", "패키지 host 정보가 없습니다")
    return value


def contract():
    """Root-free examples are documentation, never execution evidence."""
    command = {"id": "test", "argv": ["python3", "-m", "unittest", "discover"],
               "cwd": ".", "confirmed": True, "required": True, "timeout": 300}
    return {"schema_version": SCHEMA, "actions": list(ACTIONS), "routes": list(ROUTES), "round_limits": ROUND_LIMITS,
            "verification_strength": "transition --action verify --strength light|full; --manual-full-continuation permits one explicitly requested extra full round on the full route; perf light requires --reason; once full, never downgrade",
            "configuration_example": {"commands": [command], "inputs": ["src", "tests", "pyproject.toml"],
                                      "exclude": ["**/__pycache__/**", "reports/**"],
                                      "coverage": {"configured": False, "adapter": None},
                                      "perf": {"configured": False, "adapter": None},
                                      "reviewer": {"configured": True}, "retain_raw_output": False,
                                      "diagnostics": dict(DIAGNOSTICS), "metrics": dict(METRICS)},
            "command_fields": {"id": "unique string", "argv": "nonempty string array; shell=False",
                               "cwd": "project-relative directory", "confirmed": "explicit boolean",
                               "required": "explicit boolean", "timeout": "optional seconds, 0 < value <= 86400"},
            "review_example": {"reviewer": "REPLACE_WITH_FRESH_REVIEWER_ID", "reference": "REPLACE_WITH_NATIVE_EXECUTION_REF",
                               "adapter": "codex", "implementer_reference": "REPLACE_WITH_IMPLEMENTER_REF", "fresh": True,
                               "snapshot": {"copy": "status.result.snapshot object verbatim"}, "round": 1,
                               "axes": [{"name": name, "level": 2, "evidence": "REPLACE_WITH_FILE_LINE_OR_TEST_EVIDENCE"}
                                        for name in REVIEW_AXES],
                               "score": 100, "blocking": [], "unmet": [], "verdict": "pass"},
            "review_constraints": {"verdict": ["pass", "implementation-defect", "design-problem"],
                                   "score": "sum of five integer levels (0,1,2) times 10",
                                   "pass": "score >= 90, no zero axes, no blocking, no unmet; runtime tests separately required",
                                   "fresh": "unique reviewer and execution reference per task, separate from implementer",
                                   "snapshot": "exact current status snapshot", "round": "current task.round"},
            "coverage": {"configured": "explicit boolean", "adapter": [None, "python-pytest-cov", "kotlin-kover"],
                         "note": "선택 adapter의 세부 설정·도구 검사는 coverage 스킬 계약도 충족해야 합니다"},
            "verify_run": {"exit": {"success": 0, "failure": 1, "input_or_state": 2, "cancelled": 130},
                           "fields": ["ok", "recorded", "execution_status", "errorCode", "result"]},
            "migration": {"supported": [1, 2], "read_only_legacy": ["status", "doctor", "migration-preview"]},
            "evidence": "예시는 실행 증거가 아닙니다. 외부 테스트 종료 코드 등록 명령은 제공하지 않습니다"}


def root_for(project=None):
    if project is not None:
        root = Path(project).resolve()
        if not root.is_dir():
            fail("PROJECT_NOT_FOUND", "프로젝트 디렉터리가 없습니다")
        return root
    for path in (Path.cwd(), *Path.cwd().parents):
        if (path / ".tram/project.json").is_file():
            return path.resolve()
    fail("NOT_INITIALIZED", "--project 또는 연결된 프로젝트가 필요합니다")


def inside(root, relative):
    root = Path(root).resolve()
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        fail("INVALID_PATH", "프로젝트 상대 경로가 필요합니다")
    path = root / relative
    # Do not follow symlinks, even internal ones, for managed data or evidence.
    current = root
    for part in Path(relative).parts:
        if part == "..":
            fail("INVALID_PATH", "상위 경로는 허용되지 않습니다")
        current = current / part
        if current.is_symlink():
            fail("SYMLINK", "심볼릭 링크 경로는 허용되지 않습니다", path=relative)
    if not path.resolve().is_relative_to(root):
        fail("INVALID_PATH", "프로젝트 밖 경로입니다")
    return path


def load(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail("NOT_FOUND", "필수 기록이 없습니다", path=str(path.name))
    except (ValueError, UnicodeError):
        fail("INVALID_JSON", "손상된 JSON 기록입니다", path=str(path.name))
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] not in ((1, SCHEMA) if READ_LEGACY else (SCHEMA,)):
        fail("SCHEMA_MIGRATION_REQUIRED" if isinstance(value, dict) and value.get("schema_version") == 1 else "SCHEMA_INCOMPATIBLE", "schema 호환 확인과 명시적 migration이 필요합니다")
    if type(value.get("revision")) is not int or value["revision"] < 0:
        fail("INVALID_STATE", "유효한 revision이 필요합니다")
    return value


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".tram-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save(path, value, expected=None):
    if expected is not None and load(path)["revision"] != expected:
        fail("REVISION_CONFLICT", "동시 변경으로 저장을 거부했습니다")
    value["revision"] += 1
    atomic(path, canonical(value) + b"\n")


@contextmanager
def maintenance(root):
    if fcntl is None:
        fail('PROCESS_CONTROL_UNSUPPORTED', 'POSIX maintenance 잠금을 지원하지 않습니다')
    path = inside(root, ".tram/local/maintenance.lock")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextmanager
def locked(root):
    # The short maintenance lock serializes lock acquisition/removal with recovery.
    path = inside(root, ".tram/local/write.lock")
    token = {"pid": os.getpid(), "start_id": process_identity(os.getpid()),
             "token": uuid.uuid4().hex, "timestamp": now()}
    with maintenance(root):
        pp = inside(root, ".tram/project.json")
        if pp.exists():
            try:
                raw = json.loads(pp.read_text())
            except (ValueError, UnicodeError):
                fail("INVALID_JSON", "손상된 project 기록입니다")
            if raw.get("schema_version") == 1:
                fail("SCHEMA_MIGRATION_REQUIRED", "명시적 schema migration이 필요합니다")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                owner = json.loads(path.read_text())
            except (ValueError, OSError):
                owner = {"unreadable": True}
            fail("LOCKED", "doctor와 recover preview로 소유자를 확인하세요", owner=owner)
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(token))
    try:
        yield
    finally:
        with maintenance(root):
            try:
                if json.loads(path.read_text()) == token:
                    path.unlink()
            except (FileNotFoundError, ValueError):
                pass


def slug_path(root, slug):
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        fail("INVALID_SLUG", "kebab-case slug가 필요합니다")
    return inside(root, f".tram/tasks/{slug}.json")


def profile(root):
    value = load(inside(root, ".tram/project.json"))
    validate_profile(root, value)
    return value


def validate_profile(root, value):
    for key in ("commands", "inputs", "exclude"):
        if not isinstance(value.get(key), list):
            fail("INVALID_PROFILE", f"{key} 배열이 필요합니다")
    if not value["inputs"]:
        fail("INVALID_PROFILE", "검증 입력 경로가 필요합니다")
    for item in value["inputs"]:
        inside(root, item)
    if any(not isinstance(x, str) or not x for x in value["exclude"]):
        fail("INVALID_PROFILE", "exclude는 경로 패턴 배열입니다")
    ids = set()
    for cmd in value["commands"]:
        if not isinstance(cmd, dict) or not isinstance(cmd.get("id"), str) or not cmd["id"] or cmd["id"] in ids:
            fail("INVALID_PROFILE", "명령 id는 고유해야 합니다")
        ids.add(cmd["id"])
        if not isinstance(cmd.get("argv"), list) or not cmd["argv"] or any(not isinstance(x, str) or not x or "\0" in x for x in cmd["argv"]):
            fail("INVALID_PROFILE", "명령은 비어 있지 않은 argv 배열입니다")
        inside(root, cmd.get("cwd"))
        if type(cmd.get("confirmed")) is not bool or type(cmd.get("required")) is not bool:
            fail("INVALID_PROFILE", "confirmed/required를 명시하세요")
        timeout = cmd.get("timeout", 300)
        if type(timeout) not in (int, float) or not 0 < timeout <= 86400:
            fail("INVALID_PROFILE", "timeout 범위는 0 초과 86400 이하입니다")
    for name in ("coverage", "perf", "reviewer"):
        if not isinstance(value.get(name), dict) or type(value[name].get("configured")) is not bool:
            fail("INVALID_PROFILE", f"{name}.configured를 명시하세요")
    for name, defaults in (("diagnostics", DIAGNOSTICS), ("metrics", METRICS)):
        options = value.get(name, defaults)
        if not isinstance(options, dict) or set(options) != set(defaults) or type(options.get("enabled")) is not bool:
            fail("INVALID_PROFILE", name + " 설정 필드가 잘못되었습니다")
        for key, default in defaults.items():
            if key != "enabled" and (type(options[key]) is not int or not 0 < options[key] <= default):
                fail("INVALID_PROFILE", name + "." + key + " 범위가 잘못되었습니다")
    for item in value["inputs"]:
        if item != "." and any(part in CACHE_DIRS for part in Path(item).parts):
            for pattern in value["exclude"]:
                if fnmatch.fnmatchcase(item, pattern) or fnmatch.fnmatchcase(item + "/", pattern):
                    fail("INPUT_EXCLUDE_CONFLICT", "명시적 입력과 제외 규칙이 충돌합니다", path=item)
    if value.get("retain_raw_output") is not False:
        fail("RAW_OUTPUT_DISABLED", "retain_raw_output은 false여야 합니다")


def managed_text(text, block, baseline=None, remove=False):
    starts, ends = text.count(BEGIN), text.count(END)
    if starts == ends == 0:
        if remove:
            return text
        if baseline is not None:
            fail("MANAGED_CONFLICT", "관리 block이 삭제되었습니다")
        return text + ("\n" if text and not text.endswith("\n") else "") + block
    if starts != 1 or ends != 1 or text.index(END) < text.index(BEGIN):
        fail("MANAGED_CONFLICT", "관리 block 경계가 손상되거나 중복되었습니다")
    start = text.index(BEGIN)
    end = text.index(END) + len(END)
    if text[end:end + 1] == "\n":
        end += 1
    existing = text[start:end]
    if baseline is None or digest(existing.encode()) != baseline:
        fail("MANAGED_CONFLICT", "사용자 관리 block 변경을 보존했습니다")
    return text[:start] + ("" if remove else block) + text[end:]


def init(project):
    root = root_for(project)
    with locked(root):
        pp = inside(root, ".tram/project.json")
        ip = inside(root, ".tram/installation.json")
        existing = profile(root) if pp.exists() else None
        install = load(ip) if ip.exists() else {"schema_version": SCHEMA, "revision": 0,
            "version": release_version(), "adapter": "unconfigured", "schema_min": SCHEMA, "schema_max": SCHEMA,
            "managed": {}, "conflicts": [], "linked": False}
        conflicts, updates = [], []
        for name, block in (("AGENTS.md", LINK_BLOCK), ("CLAUDE.md", LINK_BLOCK), (".gitignore", IGNORE_BLOCK)):
            path = inside(root, name)
            text = path.read_text() if path.exists() else ""
            baseline = install["managed"].get(name, {}).get("checksum")
            try:
                updated = managed_text(text, block, baseline)
                updates.append((path, text, updated, block))
            except TramError as error:
                conflicts.append({"path": name, "errorCode": error.code})
        if existing is None:
            candidates, stack = [], []
            for marker, label, argv in (("pyproject.toml", "python", ["python3", "-m", "unittest", "discover"]),
                                        ("package.json", "node", ["npm", "test"]),
                                        ("gradlew", "gradle", ["./gradlew", "test"])):
                if inside(root, marker).is_file():
                    stack.append({"stack": label, "evidence": marker})
                    candidates.append({"id": label + "-test", "argv": argv, "cwd": ".", "confirmed": False, "required": False})
            existing = {"schema_version": SCHEMA, "revision": 0, "stack": stack,
                        "command_candidates": candidates, "commands": [], "inputs": ["."],
                        "exclude": [pattern for name in sorted(CACHE_DIRS) for pattern in (name + "/**", "**/" + name + "/**")],
                        "conventions": [], "territories": [],
                        "coverage": {"configured": False, "adapter": None}, "perf": {"configured": False, "adapter": None},
                        "reviewer": {"configured": False}, "retain_raw_output": False,
                        "diagnostics": dict(DIAGNOSTICS), "metrics": dict(METRICS)}
            save(pp, existing)
        # Record an incomplete connection before changing project text.
        current_version = release_version()
        current_adapter = release_adapter()
        if (install["linked"] and not conflicts and install["version"] == current_version and install["adapter"] == current_adapter
                and all(text == updated for _, text, updated, _ in updates)):
            return {"project": existing, "installation": install,
                    "legacy_profile": inside(root, ".codex/project-profile.json").exists(),
                    "warning": "legacy 설정은 자동 변경하지 않으며 .tram/project.json이 우선합니다"}
        install["version"] = current_version
        install["adapter"] = current_adapter
        install["conflicts"], install["linked"] = conflicts, False
        save(ip, install, install["revision"] if ip.exists() else None)
        for path, text, updated, block in updates:
            if text != updated:
                atomic(path, updated.encode())
            install["managed"][path.name] = {"checksum": digest(block.encode()), "block": block}
            save(ip, install, install["revision"])
        install["linked"] = not conflicts
        save(ip, install, install["revision"])
        return {"project": existing, "installation": install,
                "legacy_profile": inside(root, ".codex/project-profile.json").exists(),
                "warning": "legacy 설정은 자동 변경하지 않으며 .tram/project.json이 우선합니다"}


def configure(project, file):
    root = root_for(project)
    with locked(root):
        old = profile(root)
        try:
            changes = json.loads(Path(file).read_text())
        except (ValueError, UnicodeError):
            fail("INVALID_JSON", "설정 JSON이 잘못되었습니다")
        allowed = {"commands", "inputs", "exclude", "coverage", "perf", "reviewer", "conventions", "territories", "retain_raw_output", "diagnostics", "metrics"}
        if not isinstance(changes, dict) or set(changes) - allowed:
            fail("INVALID_PROFILE", "알 수 없는 설정 필드입니다")
        new = dict(old, **changes)
        validate_profile(root, new)
        if new.get("retain_raw_output") is not False:
            fail("RAW_OUTPUT_DISABLED", "retain_raw_output은 false여야 합니다")
        save(inside(root, ".tram/project.json"), new, old["revision"])
        result = dict(new)
        if old.get('metrics', METRICS)['enabled'] != new.get('metrics', METRICS)['enabled']:
            try:
                append_event(root, {'type': 'collection_enabled' if new['metrics']['enabled'] else 'collection_disabled'})
                result['metrics_recorded'] = True
            except (OSError, TramError):
                result.update({'metrics_recorded': False, 'metrics_warning': 'METRICS_APPEND_FAILED'})
        return result


def task(root, slug):
    return validate_task(load(slug_path(root, slug)), slug)


def validate_task(value, slug):
    if value.get("verification_strength") not in (None, "light", "full") or type(value.get("full_required", False)) is not bool:
        fail("INVALID_STATE", "검증 강도 기록이 잘못되었습니다")
    if value.get("slug") != slug or value.get("route") not in ROUTES or value.get("phase") not in PHASES:
        fail("INVALID_STATE", "작업 상태가 잘못되었습니다")
    for key in ("approvals", "verification", "reviews"):
        if not isinstance(value.get(key), list) or any(not isinstance(x, dict) for x in value[key]):
            fail("INVALID_STATE", f"{key} 배열이 필요합니다")
    round_limit = None if value.get("route") == "full" else ROUND_LIMITS.get(value.get("route"))
    if (type(value.get("round")) is not int or value["round"] < 0
            or (round_limit is not None and value["round"] > round_limit)):
        fail("INVALID_STATE", "검증 round 범위가 잘못되었습니다")
    if value.get("documents") != {"prd": f"docs/prd/{slug}.md", "plan": f"docs/plan/{slug}.md"}:
        fail("INVALID_STATE", "문서 경로가 잘못되었습니다")
    return value


def doc_digests(root, state):
    result = {}
    for scope, name in state["documents"].items():
        path = inside(root, name)
        result[scope] = digest(path.read_bytes()) if path.is_file() else None
    return result


def approval_validity(root, state):
    docs = doc_digests(root, state)
    result = {}
    for scope in ("prd", "plan"):
        records = [x for x in state["approvals"] if x.get("scope") == scope]
        record = records[-1] if records else {}
        result[scope] = bool(docs[scope] and record.get("digest") == docs[scope]
                             and not record.get("invalidated") and record.get("quote") and record.get("session")
                             and (scope != "plan" or (result["prd"] and record.get("upstream_digest") == docs["prd"])))
    return result


def reconcile(root, state):
    valid = approval_validity(root, state)
    for record in state["approvals"]:
        if not valid.get(record.get("scope"), False):
            record["invalidated"] = True
    if state["route"] == "full":
        if not valid["prd"] and state["phase"] not in ("prd_draft", "prd_review"):
            state["phase"], state["blocked"] = "prd_draft", "PRD 승인 부재 또는 변경"
        elif valid["prd"] and not valid["plan"] and state["phase"] in ("implementing", "verifying", "complete"):
            state["phase"], state["blocked"] = "plan_draft", "Plan 승인 부재 또는 변경"
    return valid


def reconcile_write(root, config, state):
    before = canonical(state)
    reconcile(root, state)
    if state["phase"] == "complete" and completion_issues(root, config, state):
        state["phase"], state["blocked"] = "verifying", "검증 증거가 낡았습니다"
    if canonical(state) != before:
        save(slug_path(root, state["slug"]), state, state["revision"])


def fingerprint(root, config, state):
    files = {}
    document_paths = set(state["documents"].values())
    def excluded(relative):
        parts = Path(relative).parts
        return (".git" in parts or ".tram" in parts or relative in document_paths
                or any(fnmatch.fnmatchcase(relative, pattern) for pattern in config["exclude"]))
    def stream_hash(path):
        result = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                result.update(chunk)
        return result.hexdigest()
    for name in config["inputs"]:
        path = inside(root, name)
        candidates = []
        if path.is_dir():
            def walk_error(error):
                fail("INPUT_UNREADABLE", "검증 입력을 읽을 수 없습니다")
            for folder, dirs, names in os.walk(path, followlinks=False, onerror=walk_error):
                kept = []
                for directory in dirs:
                    candidate = Path(folder) / directory
                    relative = candidate.relative_to(root).as_posix()
                    if excluded(relative) or excluded(relative + "/"):
                        continue
                    if candidate.is_symlink():
                        fail("SYMLINK", "검증 입력에 심볼릭 링크가 있습니다", path=relative)
                    kept.append(directory)
                dirs[:] = kept
                for filename in names:
                    item = Path(folder) / filename
                    relative = item.relative_to(root).as_posix()
                    if excluded(relative):
                        continue
                    if item.is_symlink():
                        fail("SYMLINK", "검증 입력에 심볼릭 링크가 있습니다", path=relative)
                    if item.is_file():
                        files[relative] = {"digest": stream_hash(item), "executable": bool(item.stat().st_mode & 0o111)}
        else:
            candidates = [path]
        for item in candidates:
            relative = item.relative_to(root).as_posix()
            if not excluded(relative) and item.is_file():
                files[relative] = {"digest": stream_hash(item), "executable": bool(item.stat().st_mode & 0o111)}
    head = None
    try:
        run = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, timeout=5, shell=False)
        if run.returncode == 0:
            head = run.stdout.decode().strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"digest": digest(canonical({"files": files, "head": head})), "head": head,
            "files": files, "documents": doc_digests(root, state),
            "profile_digest": digest(canonical(config))}


def specialized(root, config, route, entry=True):
    if route not in ("coverage", "perf"):
        return
    if not config[route]["configured"]:
        fail("ADAPTER_UNCONFIGURED", f"{route} adapter가 미설정입니다")
    if route == "coverage":
        try:
            branch = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=root, capture_output=True, timeout=5)
            dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            fail("COVERAGE_PREREQUISITE", "Git 저장소와 깨끗한 비기본 브랜치가 필요합니다")
        defaults = config[route].get("default_branches", ["main", "master"])
        if branch.returncode or dirty.returncode or (entry and dirty.stdout) or branch.stdout.decode().strip() in defaults:
            fail("COVERAGE_PREREQUISITE", "비기본 Git 브랜치가 필요하며 최초 진입에는 깨끗한 작업 트리가 필요합니다")


def start(project, slug, route=None):
    root = root_for(project)
    with locked(root):
        config = profile(root)
        path = slug_path(root, slug)
        if path.exists():
            state = task(root, slug)
            if route is not None and state["route"] != route:
                fail("ROUTE_CONFLICT", "기존 작업 경로는 escalate로 변경하세요")
            reconcile_write(root, config, state)
        else:
            route = route or "full"
            if route not in ROUTES:
                fail("INVALID_ROUTE", "지원하지 않는 경로입니다")
            specialized(root, config, route)
            state = {"schema_version": SCHEMA, "revision": 0, "slug": slug, "route": route,
                     "phase": "prd_draft" if route == "full" else "implementing", "blocked": None,
                     "documents": {"prd": f"docs/prd/{slug}.md", "plan": f"docs/plan/{slug}.md"},
                     "approvals": [], "verification": [], "reviews": [], "round": 0,
                     "verification_strength": None, "full_required": route in ("full", "coverage"),
                     "finishing": {"commit": None, "push": None, "pr": None}}
            save(path, state)
        result = view(root, config, state)
        if state['phase'] != 'complete':
            result.update(metrics_action(root, config, state, 'start'))
        return result


def require_approvals(root, state):
    if state["route"] == "full" and not all(approval_validity(root, state).values()):
        fail("APPROVAL_REQUIRED", "현재 PRD와 Plan의 명시적 승인이 필요합니다")


def approve(project, slug, scope, quote, session):
    root = root_for(project)
    if scope not in ("prd", "plan") or not isinstance(quote, str) or not quote.strip() or len(quote) > 500 or not session.strip() or len(session) > 500:
        fail("INVALID_APPROVAL", "최소 승인 인용(500자 이하)과 session reference가 필요합니다")
    with locked(root):
        config = profile(root)
        state = task(root, slug)
        reconcile_write(root, config, state)
        if state["route"] != "full" or state["phase"] != scope + "_review":
            fail("INVALID_TRANSITION", "해당 문서 검토 단계에서만 승인할 수 있습니다")
        if scope == "plan" and not approval_validity(root, state)["prd"]:
            fail("APPROVAL_REQUIRED", "PRD 승인이 필요합니다")
        path = inside(root, state["documents"][scope])
        if not path.is_file():
            fail("ARTIFACT_REQUIRED", "승인할 문서가 없습니다")
        text = path.read_text()
        marker = f"> 상태: {'확정' if scope == 'prd' else '승인'} · {now()[:7]} (스냅샷 — 코드 변경에 맞춰 최신화 안 함)"
        text = re.sub(r"(?m)^> 상태:.*$", lambda m: marker, text, count=1) if re.search(r"(?m)^> 상태:", text) else marker + "\n\n" + text
        atomic(path, text.encode())
        docs = doc_digests(root, state)
        state["approvals"].append({"scope": scope, "path": state["documents"][scope],
            "digest": docs[scope], "upstream_digest": docs["prd"] if scope == "plan" else None,
            "quote": quote.strip(), "session": session.strip(), "timestamp": now()})
        state["phase"] = "plan_draft" if scope == "prd" else "implementing"
        state["blocked"] = None
        save(slug_path(root, slug), state, state["revision"])
        return {**state, **metrics_action(root, profile(root), state, 'approve')}


def completion_issues(root, config, state, snapshot=None):
    issues = []
    if state["route"] == "full" and not all(approval_validity(root, state).values()):
        issues.append("APPROVAL_REQUIRED")
    snapshot = snapshot or fingerprint(root, config, state)
    required = [x for x in config["commands"] if x["required"]]
    if not required:
        issues.append("REQUIRED_COMMANDS_MISSING")
    for cmd in required:
        records = [x for x in state["verification"] if x.get("command_id") == cmd["id"] and x.get("round") == state["round"]]
        if not cmd["confirmed"] or not records or records[-1].get("snapshot") != snapshot or records[-1].get("exit_code") != 0 or records[-1].get("stale") or records[-1].get("execution_status") != "succeeded":
            issues.append("COMMAND_EVIDENCE_MISSING:" + cmd["id"])
    strength = state.get("verification_strength") or ("light" if state["route"] == "quick" else "full")
    if strength == "full" or state["route"] in ("full", "coverage") or state.get("full_required"):
        reviews = [x for x in state["reviews"] if x.get("round") == state["round"]]
        if not config["reviewer"]["configured"] or not reviews or reviews[-1].get("snapshot") != snapshot or reviews[-1].get("verdict") != "pass":
            issues.append("INDEPENDENT_REVIEW_REQUIRED")
    return issues


def transition(project, slug, action, strength=None, reason=None, manual_full_continuation=False):
    if (strength is not None or reason is not None or manual_full_continuation) and action != "verify":
        fail("INVALID_ARGUMENT", "검증 강도·근거는 verify 행동에만 사용합니다")
    if type(manual_full_continuation) is not bool:
        fail("INVALID_ARGUMENT", "수동 full 연장 값은 boolean이어야 합니다")
    root = root_for(project)
    with locked(root):
        config, state = profile(root), task(root, slug)
        reconcile_write(root, config, state)
        phase = state["phase"]
        if action in ("submit-prd", "submit-plan"):
            scope = action.removeprefix("submit-")
            if state["route"] != "full" or phase != scope + "_draft":
                fail("INVALID_TRANSITION", "문서 초안 단계가 아닙니다")
            if scope == "plan" and not approval_validity(root, state)["prd"]:
                fail("APPROVAL_REQUIRED", "PRD 승인이 필요합니다")
            if not inside(root, state["documents"][scope]).is_file():
                fail("ARTIFACT_REQUIRED", "필수 문서가 없습니다")
            state["phase"] = scope + "_review"
        elif action == "implement":
            require_approvals(root, state)
            if phase != "implementing":
                fail("INVALID_TRANSITION", "구현 단계가 아닙니다")
        elif action == "verify":
            require_approvals(root, state)
            specialized(root, config, state["route"], entry=False)
            if phase != "implementing":
                fail("INVALID_TRANSITION", "구현 후 검증을 시작하세요")
            selected = strength or state.get("verification_strength") or ("light" if state["route"] == "quick" else "full")
            if selected not in ("light", "full"):
                fail("INVALID_ARGUMENT", "검증 강도는 light 또는 full입니다")
            if manual_full_continuation and (state["route"] != "full" or selected != "full"):
                fail("INVALID_ARGUMENT", "수동 연장은 full route의 full 검증에서만 사용할 수 있습니다")
            if selected == "light" and (state["route"] in ("full", "coverage") or state.get("full_required")):
                fail("FULL_REQUIRED", "full 검증이 필요한 작업은 light로 낮출 수 없습니다")
            if selected == "light" and state["route"] == "perf" and not state.get("light_reason"):
                if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
                    fail("LIGHT_REASON_REQUIRED", "perf light의 저위험·동작 보존 테스트 근거를 기록하세요")
                state["light_reason"] = reason.strip()
            limit = ROUND_LIMITS[state["route"]]
            if state["round"] >= limit and not manual_full_continuation:
                fail("ROUND_LIMIT", f"검증 라운드 상한({limit})에 도달했습니다")
            # Specialized skills own their metric-specific stagnation guards.
            reviews = state["reviews"] if state["route"] in ("full", "quick") else []
            if not manual_full_continuation and len(reviews) >= 3 and max(x["score"] for x in reviews[:-2]) >= max(x["score"] for x in reviews[-2:]):
                fail("NO_PROGRESS", "두 라운드 연속 최고 점수 개선이 없습니다")
            if not manual_full_continuation and len(reviews) >= 2:
                previous = {canonical(x) for x in reviews[-2]["blocking"] + reviews[-2]["unmet"]}
                recent = {canonical(x) for x in reviews[-1]["blocking"] + reviews[-1]["unmet"]}
                if previous & recent:
                    fail("NO_PROGRESS", "동일 인용 결함이 두 라운드 연속 남았습니다")
            state["verification_strength"] = selected
            state["full_required"] = state.get("full_required", False) or selected == "full"
            state["phase"], state["round"] = "verifying", state["round"] + 1
        elif action == "complete":
            if phase != "verifying":
                fail("INVALID_TRANSITION", "검증 단계가 아닙니다")
            issues = completion_issues(root, config, state)
            if issues:
                fail("VERIFICATION_REQUIRED", "완료 전제조건이 충족되지 않았습니다", issues=issues)
            state["phase"] = "complete"
        elif action in ("implementation-defect", "design-problem", "requirements-problem"):
            if phase != "verifying":
                fail("INVALID_TRANSITION", "검증 결과 분기는 검증 단계에서만 가능합니다")
            if action == "implementation-defect":
                state["phase"] = "implementing"
            else:
                scope = "prd" if action == "requirements-problem" else "plan"
                state["route"], state["phase"] = "full", scope + "_draft"
                state["verification_strength"], state["full_required"] = None, True
                for record in state["approvals"]:
                    if scope == "prd" or record["scope"] == "plan":
                        record["invalidated"] = True
        elif action == "escalate":
            if state["route"] == "full" or phase == "complete":
                fail("INVALID_TRANSITION", "예외 경로의 진행 작업만 승격할 수 있습니다")
            state["route"], state["phase"] = "full", "prd_draft"
            state["verification_strength"], state["full_required"] = None, True
        else:
            fail("INVALID_ACTION", "지원하지 않는 전이입니다")
        state["blocked"] = None
        save(slug_path(root, slug), state, state["revision"])
        result = view(root, config, state)
        result.update(metrics_action(root, config, state, 'transition'))
        return result


def verify_run(project, slug, command):
    root = root_for(project)
    with locked(root):
        config, state = profile(root), task(root, slug)
        reconcile_write(root, config, state)
        require_approvals(root, state)
        if state["phase"] != "verifying":
            fail("INVALID_TRANSITION", "먼저 verify 전이를 실행하세요")
        matches = [x for x in config["commands"] if x["id"] == command]
        if not matches or not matches[0]["confirmed"]:
            fail("COMMAND_UNCONFIRMED", "프로필에 확인된 명령이 필요합니다")
        cmd = matches[0]
        if not inside(root, cmd["cwd"]).is_dir():
            fail("INVALID_PATH", "명령 cwd가 없습니다")
        if os.name != 'posix':
            fail('PROCESS_CONTROL_UNSUPPORTED', 'POSIX 실행만 지원합니다')
        if any(r['command_id'] == command for r in active_runs(root, slug)):
            fail('EXECUTION_ACTIVE', '동일 task와 command의 실행이 종료되지 않았습니다')
        snapshot = fingerprint(root, config, state)
        revision, config_revision = state["revision"], config["revision"]
        run_id = uuid.uuid4().hex
        reservation = {'id': run_id, 'slug': slug, 'command_id': command,
                       'state': 'reserved', 'token': uuid.uuid4().hex, 'timestamp': now(),
                       'parent': {'pid': os.getpid(), 'start_id': process_identity(os.getpid())},
                       'revision': revision, 'round': state['round'], 'snapshot_digest': digest(canonical(snapshot)),
                       'command_digest': digest(canonical(cmd)), 'recorded': False}
        path = local_path(root, 'runs/' + run_id + '.json')
        atomic(path, canonical(reservation))
    execution = execute_owned(root, cmd, reservation, path, config.get('diagnostics', DIAGNOSTICS))
    record = {"id": run_id, "run_id": run_id, "command_id": command, "command_digest": digest(canonical(cmd)),
              "cwd": cmd["cwd"], "snapshot": snapshot, "round": state["round"],
              "strength": state.get("verification_strength"), "timestamp": now(), **execution,
              'recorded': False}
    # Persist the result before task registration, allowing inspected recovery after a crash.
    reservation['result'] = record
    reservation['state'] = 'finished' if execution['cleanup']['confirmed'] else 'stopping'
    atomic(path, canonical(reservation))
    try:
        with locked(root):
            current_config, current = profile(root), task(root, slug)
            after = fingerprint(root, current_config, current)
            stale = current["revision"] != revision or current_config["revision"] != config_revision or after != snapshot
            record.update({'stale': stale, 'changes': snapshot_changes(snapshot, after), 'recorded': True})
            current["verification"].append(record)
            if stale:
                current["blocked"] = "검증 중 입력 또는 revision 변경: 다시 검증하세요"
            save(slug_path(root, slug), current, current["revision"])
            reservation.update({'recorded': True, 'result': record})
            atomic(path, canonical(reservation))
            record.update(metrics_action(root, current_config, current, 'verification', run_id=run_id,
                           outcome='stale' if stale else record['execution_status'], duration_ms=record['elapsed_ms']))
            return record
    except (TramError, OSError) as exc:
        record.update({'recorded': False, 'registration_error': getattr(exc, 'code', 'IO_ERROR')})
        return record


def review(project, slug, file):
    root = root_for(project)
    try:
        result = json.loads(Path(file).read_text())
    except (ValueError, UnicodeError):
        fail("INVALID_JSON", "review JSON이 잘못되었습니다")
    with locked(root):
        config, state = profile(root), task(root, slug)
        reconcile_write(root, config, state)
        require_approvals(root, state)
        if state["phase"] != "verifying" or not config["reviewer"]["configured"]:
            fail("REVIEW_UNAVAILABLE", "독립 reviewer 설정과 검증 단계가 필요합니다")
        if not isinstance(result, dict):
            fail("INVALID_REVIEW", "review 객체가 필요합니다")
        for key in ("reviewer", "reference", "adapter", "implementer_reference"):
            if not isinstance(result.get(key), str) or not result[key].strip() or len(result[key]) > 500:
                fail("INVALID_REVIEW", f"{key} reference가 필요합니다")
        if result.get("fresh") is not True or result["reference"] == result["implementer_reference"]:
            fail("INVALID_REVIEW", "fresh 독립 실행 reference가 필요합니다")
        if any(x["reference"] == result["reference"] or x["reviewer"] == result["reviewer"] for x in state["reviews"]):
            fail("REVIEW_REUSED", "매 라운드 새 reviewer가 필요합니다")
        snapshot = fingerprint(root, config, state)
        if result.get("snapshot") != snapshot or result.get("round") != state["round"]:
            fail("STALE_REVIEW", "검토 입력 snapshot/round가 현재 상태와 다릅니다")
        axes = result.get("axes")
        if not isinstance(axes, list) or len(axes) != 5 or len({x.get("name") for x in axes if isinstance(x, dict)}) != 5:
            fail("INVALID_REVIEW", "서로 다른 5축 평가가 필요합니다")
        for axis in axes:
            if not isinstance(axis, dict) or type(axis.get("level")) is not int or axis["level"] not in (0, 1, 2) or not isinstance(axis.get("evidence"), str) or not axis["evidence"].strip():
                fail("INVALID_REVIEW", "각 축의 레벨과 인용 근거가 필요합니다")
        if {axis["name"] for axis in axes} != set(REVIEW_AXES):
            fail("INVALID_REVIEW", "정해진 코드 리뷰 5축 이름을 사용하세요")
        for key in ("blocking", "unmet"):
            if not isinstance(result.get(key), list):
                fail("INVALID_REVIEW", f"{key} 배열이 필요합니다")
        score = sum(x["level"] for x in axes) * 10
        passing = score >= 90 and all(x["level"] for x in axes) and not result["blocking"] and not result["unmet"]
        verdict = result.get("verdict")
        if result.get("score") != score or verdict not in ("pass", "implementation-defect", "design-problem") or (verdict == "pass") != bool(passing):
            fail("INVALID_REVIEW", "점수·블로킹·판정이 모순됩니다")
        record = {k: result[k] for k in ("reviewer", "reference", "adapter", "implementer_reference", "fresh", "axes", "blocking", "unmet", "score", "verdict", "snapshot", "round")}
        record["timestamp"] = now()
        state["reviews"].append(record)
        save(slug_path(root, slug), state, state["revision"])
        return record


def view(root, config, state):
    valid = approval_validity(root, state)
    effective = json.loads(json.dumps(state))
    reconcile(root, effective)
    snapshot = fingerprint(root, config, state)
    issues = completion_issues(root, config, state, snapshot)
    if effective["phase"] == "complete" and issues:
        effective["phase"], effective["blocked"] = "verifying", "검증 증거가 낡았습니다"
    return {"task": state, "effective_phase": effective["phase"], "blocked": effective["blocked"],
            "approvals_valid": valid, "completion_issues": issues, "snapshot": snapshot,
            "changes": snapshot_changes(state["verification"][-1].get("snapshot", {}), snapshot) if state["verification"] else None,
            "next_action": {"prd_draft": "prd", "prd_review": "approve-prd", "plan_draft": "plan",
                            "plan_review": "approve-plan", "implementing": "impl", "verifying": "verify", "complete": "finishing"}[effective["phase"]],
            "limitations": ["승인 인용과 reviewer reference는 신원 인증이 아닙니다", "native host 실행 지원은 별도 검증이 필요합니다"]}


def status(project=None, slug=None):
    global READ_LEGACY
    previous = READ_LEGACY
    READ_LEGACY = True
    try:
        return _status(project, slug)
    finally:
        READ_LEGACY = previous


def _status(project=None, slug=None):
    root = root_for(project)
    config = profile(root)
    if slug:
        return view(root, config, task(root, slug))
    folder = inside(root, ".tram/tasks")
    names = sorted(p.stem for p in folder.glob("*.json")) if folder.exists() else []
    return {"tasks": [view(root, config, task(root, name)) for name in names],
            "selection_required": len(names) > 1, "project": config}


def unlink(project):
    root = root_for(project)
    with locked(root):
        profile(root)
        path = inside(root, ".tram/installation.json")
        install = load(path)
        removed, conflicts = [], []
        for name in ("AGENTS.md", "CLAUDE.md"):
            entry = install["managed"].get(name)
            if not entry:
                continue
            target = inside(root, name)
            if not target.exists():
                continue
            text = target.read_text()
            try:
                updated = managed_text(text, entry["block"], entry["checksum"], remove=True)
            except TramError as error:
                conflicts.append({"path": name, "errorCode": error.code})
                continue
            if updated != text:
                atomic(target, updated.encode())
                removed.append(name)
            del install["managed"][name]
        install["linked"], install["conflicts"] = False, conflicts
        save(path, install, install["revision"])
        return {"removed_blocks": removed, "conflicts": conflicts, "preserved": [".tram/", "docs/", ".gitignore"]}


def migration_preview(project=None):
    root = root_for(project)
    results = []
    for relative in state_paths(root):
        try:
            value = raw_json(root, relative)
            results.append({'path': relative, 'compatible': value.get('schema_version') in (1, 2),
                            'schema_version': value.get('schema_version')})
        except (ValueError, OSError, TramError) as exc:
            results.append({'path': relative, 'compatible': False, 'errorCode': getattr(exc, 'code', 'INVALID_JSON')})
    return {'schema_version': SCHEMA, 'files': results, 'writes': False,
            'migration': 'migrate preview/apply --from 1 --to 2 또는 --from 2 --to 1'}


def process_table():
    """Observe identities and ancestry only, never argv or environment."""
    result = {}
    if Path('/proc').is_dir():
        for path in Path('/proc').glob('[0-9]*/stat'):
            try:
                raw = path.read_text()
                pid = int(raw[:raw.index(' ')])
                fields = raw[raw.rindex(')') + 2:].split()
                if fields[0] == 'Z':
                    continue
                result[pid] = {"pid": pid, "ppid": int(fields[1]), "pgid": int(fields[2]),
                               "sid": int(fields[3]), "start_id": 'proc:' + Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' + fields[19]}
            except (OSError, ValueError, IndexError):
                continue
        return result
    run = subprocess.run(['ps', '-axo', 'pid=,ppid=,pgid=,stat='],
                         capture_output=True, timeout=5)
    if run.returncode:
        fail('PROCESS_OBSERVATION_FAILED', 'OS 프로세스 표를 확인할 수 없습니다')
    for line in run.stdout.decode().splitlines():
        fields = line.split()
        if len(fields) != 4 or fields[3].startswith('Z'):
            continue
        try:
            pid, ppid, pgid = map(int, fields[:3])
            # Darwin proc_bsdinfo (SDK sys/proc_info.h): microsecond OS start identity.
            # A seconds-only ps lstart is insufficient against rapid PID reuse.
            buffer = ctypes.create_string_buffer(136)
            libproc = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
            if libproc.proc_pidinfo(pid, 3, 0, buffer, 136) != 136:
                continue
            seconds, micros = struct.unpack_from('QQ', buffer.raw, 120)
            result[pid] = {"pid": pid, "ppid": ppid, "pgid": pgid,
                           "sid": os.getsid(pid), "start_id": 'darwin:' + str(seconds) + ':' + str(micros)}
        except (OSError, ValueError):
            continue
    return result


def process_identity(pid):
    try:
        return process_table().get(pid, {}).get('start_id')
    except (OSError, TramError, subprocess.TimeoutExpired):
        return None


def owner_state(owner):
    if not isinstance(owner, dict) or type(owner.get('pid')) is not int or not owner.get('start_id'):
        return 'unknown'
    try:
        table = process_table()
        entry = table.get(owner['pid'])
        if entry:
            return 'live' if entry['start_id'] == owner['start_id'] else 'dead'
        try:
            os.kill(owner['pid'], 0)
        except ProcessLookupError:
            return 'dead'
        return 'unknown'
    except (OSError, TramError, subprocess.TimeoutExpired):
        return 'unknown'


def local_path(root, relative):
    path = inside(root, '.tram/local/' + relative)
    # Require an installed ignore rule, and check Git's effective ignore if available.
    ignore = inside(root, '.gitignore')
    if not ignore.is_file():
        fail('LOCAL_NOT_IGNORED', '.tram/local/ 제외 설정이 필요합니다')
    git = subprocess.run(['git', 'rev-parse', '--git-dir'], cwd=root, capture_output=True)
    if git.returncode == 0:
        checked = subprocess.run(['git', 'check-ignore', '--no-index', '-q', '--',
                                  path.relative_to(root).as_posix()], cwd=root, capture_output=True)
        if checked.returncode != 0:
            fail('LOCAL_NOT_IGNORED', '로컬 자료가 Git에서 제외되지 않았습니다')
    elif not any(line.strip() in ('.tram/', '/.tram/', '.tram/local/', '/.tram/local/') for line in ignore.read_text().splitlines()):
        fail('LOCAL_NOT_IGNORED', '.tram/local/ 제외 설정이 필요합니다')
    current = inside(root, '.tram/local')
    current.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(current, 0o700)
    for part in Path(relative).parts[:-1]:
        current = current / part
        current.mkdir(exist_ok=True, mode=0o700)
        os.chmod(current, 0o700)
    return path


def run_records(root):
    folder = inside(root, '.tram/local/runs')
    return [(p, json.loads(inside(root, p.relative_to(root).as_posix()).read_text()))
            for p in sorted(folder.glob('*.json'))] if folder.exists() else []


def active_runs(root, slug=None):
    return [r for _, r in run_records(root) if r.get('state') != 'finished'
            and (slug is None or r.get('slug') == slug)]


def snapshot_changes(before, after):
    changes = []
    old, new = before.get('files', {}), after.get('files', {})
    for path in sorted(old.keys() | new.keys()):
        if path not in old:
            changes.append({'path': path, 'reason': 'added'})
        elif path not in new:
            changes.append({'path': path, 'reason': 'removed'})
        else:
            for key, reason in (('digest', 'content'), ('executable', 'executable')):
                if old[path].get(key) != new[path].get(key):
                    changes.append({'path': path, 'reason': reason})
    for key, reason in (('documents', 'documents'), ('profile_digest', 'profile'), ('head', 'head')):
        if before.get(key) != after.get(key):
            changes.append({'path': key, 'reason': reason})
    return {'paths': changes[:100], 'total': len(changes), 'truncated': len(changes) > 100}


def child_entry():
    # A dead parent closes the pipe; no authorization means no command execution.
    line = sys.stdin.buffer.readline(1048576)
    if not line or not line.endswith(b'\n'):
        return 2
    try:
        permit = json.loads(line)
        if permit['token'] != sys.argv[2] or not isinstance(permit['argv'], list):
            return 2
        os.chdir(permit['cwd'])
        sys.stdin.close()
        fd = os.open(os.devnull, os.O_RDONLY)
        os.dup2(fd, 0)
        os.close(fd)
        os.execvp(permit['argv'][0], permit['argv'])
    except (OSError, ValueError, KeyError):
        return 127


def mask_output(data):
    text = data.decode('utf-8', errors='replace')
    text = re.sub(r'(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\r\n]+', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)((?:token|password|passwd|secret|api[_-]?key)\s*["\x27]?\s*[:=]\s*["\x27]?)[^\s,"\x27;]+', r'\1[REDACTED]', text)
    text = re.sub(r'\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,})', '[REDACTED]', text)
    return text.encode()


class OutputMasker:
    """Streaming redaction with at most an 8KiB uncommitted suffix."""
    patterns = (
        (re.compile(rb'(?i)authorization\s*[:=]\s*(?:bearer\s+)?[^\r\n]+'), b'\r\n'),
        (re.compile(rb'(?i)(?:token|password|passwd|secret|api[_-]?key)\s*["\x27]?\s*[:=]\s*["\x27]?[^\s,"\x27;]+'), b' \t\r\n,"\x27;'),
        (re.compile(rb'(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,})'), b' \t\r\n,"\x27;'),
    )

    def __init__(self):
        self.pending = b''
        self.continuation = None

    def feed(self, chunk, final=False):
        output = bytearray()
        for offset in range(0, len(chunk), 8192):
            data = chunk[offset:offset + 8192]
            if self.continuation is not None:
                end = next((i for i, value in enumerate(data) if value in self.continuation), None)
                if end is None:
                    continue
                data = data[end:]
                self.continuation = None
            self.pending += data
            cut = max(0, len(self.pending) - 8192)
            if not cut:
                continue
            for pattern, delimiters in self.patterns:
                match = next((m for m in pattern.finditer(self.pending) if m.start() < cut < m.end()), None)
                if match:
                    cut = match.end()
                    if cut == len(self.pending) and self.pending[-1] not in delimiters:
                        self.continuation = delimiters
                    break
            output.extend(mask_output(self.pending[:cut]))
            self.pending = self.pending[cut:]
        if final:
            output.extend(mask_output(self.pending))
            self.pending = b''
        return bytes(output)


def diagnostics_prune(root, options):
    folder = inside(root, '.tram/local/diagnostics')
    manifests = []
    if not folder.exists():
        return {'removed': []}
    active = {r['id'] for r in active_runs(root)}
    for directory in folder.iterdir():
        if directory.is_symlink() or not directory.is_dir() or directory.name in active:
            continue
        manifest = directory / 'manifest.json'
        if manifest.is_symlink() or not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text())
            children = list(directory.iterdir())
            if any(p.is_symlink() or not p.is_file() for p in children):
                continue
            manifests.append((data['created_epoch'], sum(p.stat().st_size for p in children), directory))
        except (OSError, ValueError, KeyError):
            continue
    total = sum(x[1] for x in manifests)
    removed = []
    for created, size, directory in sorted(manifests):
        if created < time.time() - options['retention_days'] * 86400 or total > options['max_project_bytes']:
            for path in directory.iterdir():
                path.unlink()
            directory.rmdir()
            total -= size
            removed.append(directory.name)
    return {'removed': removed}


def execute_owned(root, cmd, reservation, path, options):
    if os.name != 'posix':
        fail('PROCESS_CONTROL_UNSUPPORTED', 'POSIX 프로세스 제어만 지원합니다')
    started = time.monotonic()
    streams = {name: {'hash': hashlib.sha256(), 'bytes': 0, 'saved': bytearray(), 'masker': OutputMasker(), 'complete': False, 'drain_reason': None}
               for name in ('stdout', 'stderr')}
    diagnostic_status, diagnostic_error = 'disabled', None
    enabled = options['enabled']
    if enabled:
        try:
            local_path(root, 'diagnostics/' + reservation['id'] + '/manifest.json')
            diagnostic_status = 'available'
        except (TramError, OSError) as exc:
            enabled, diagnostic_status = False, 'unavailable'
            diagnostic_error = getattr(exc, 'code', 'IO_ERROR')
    error, proc, observed = None, None, {}
    cleanup = {'confirmed': False, 'unresolved': [],
               'scope': 'owned group and descendants observed at 100ms intervals; unobserved escape is not covered'}
    def observe():
        table = process_table()
        if proc is None:
            return table
        descendants = {proc.pid}
        descendants.update(pid for pid, entry in observed.items()
                           if table.get(pid, {}).get('start_id') == entry['start_id'])
        changed = True
        while changed:
            changed = False
            for pid, entry in table.items():
                if entry['ppid'] in descendants and pid not in descendants:
                    descendants.add(pid)
                    changed = True
        for pid in descendants:
            if pid in table:
                observed.setdefault(pid, table[pid])
        if reservation.get('state') in ('running', 'stopping'):
            reservation['observed'] = list(observed.values())
            atomic(path, canonical(reservation))
        return table
    def remaining(table):
        group = [entry for entry in table.values() if entry['pgid'] == proc.pid]
        escaped = [entry for pid, entry in observed.items()
                   if table.get(pid, {}).get('start_id') == entry['start_id']
                   and table[pid]['pgid'] != proc.pid]
        return group, escaped
    def stop():
        reservation['state'] = 'stopping'
        atomic(path, canonical(reservation))
        unresolved = []
        for sig in (signal.SIGTERM, signal.SIGKILL):
            table = observe()
            group, escaped = remaining(table)
            unresolved = escaped
            if not group:
                break
            # Current child was created by this Popen in an isolated session.
            if any(x['sid'] != proc.pid or (x['pid'] in observed and x['start_id'] != observed[x['pid']]['start_id']) for x in group):
                cleanup['unresolved'] = [x['pid'] for x in group + escaped]
                return
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                proc.poll()
                table = observe()
                group, escaped = remaining(table)
                unresolved = escaped
                if not group:
                    break
                time.sleep(.05)
        proc.poll()
        table = observe()
        group, escaped = remaining(table)
        cleanup['unresolved'] = [x['pid'] for x in group + escaped]
        cleanup['confirmed'] = not cleanup['unresolved']
        if proc.poll() is not None:
            proc.wait()
    try:
        token = reservation['token']
        if not process_identity(os.getpid()):
            fail('PROCESS_OBSERVATION_FAILED', 'OS 시작 식별값을 확인할 수 없습니다')
        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_child', token],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, cwd=root)
        identity = None
        for _ in range(20):
            table = observe()
            identity = table.get(proc.pid)
            if identity:
                break
            time.sleep(.01)
        if not identity or identity['sid'] != proc.pid or identity['pgid'] != proc.pid:
            fail('PROCESS_OWNERSHIP_UNKNOWN', '시작된 child의 격리를 확인하지 못했습니다')
        reservation.update({'state': 'running', 'child': identity})
        atomic(path, canonical(reservation))
        proc.stdin.write(canonical({'token': token, 'argv': cmd['argv'], 'cwd': str(inside(root, cmd['cwd']))}) + b'\n')
        proc.stdin.close()
        selector = selectors.DefaultSelector()
        for name in streams:
            pipe = getattr(proc, name)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        next_observation = 0
        stop_time = None
        while selector.get_map() or proc.poll() is None:
            elapsed = time.monotonic() - started
            if elapsed >= cmd.get('timeout', 300) and error is None:
                error = 'TIMEOUT'
                stop()
                stop_time = time.monotonic()
            if time.monotonic() >= next_observation:
                observe()
                next_observation = time.monotonic() + .1
            if proc.poll() is not None and stop_time is None:
                stop()
                stop_time = time.monotonic()
            if stop_time is not None and time.monotonic() - stop_time > .3:
                break  # An escaped process may still hold a pipe; never wait indefinitely.
            for key, _ in selector.select(.05):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    streams[key.data]['complete'] = True
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                stream = streams[key.data]
                stream['hash'].update(chunk)
                stream['bytes'] += len(chunk)
                if enabled:
                    masked = stream['masker'].feed(chunk)
                    room = options['max_bytes_per_stream'] - len(stream['saved'])
                    stream['saved'].extend(masked[:max(0, room)])
        selector.close()
        if not cleanup['confirmed']:
            stop()
    except KeyboardInterrupt:
        error = 'CANCELLED'
        if proc:
            stop()
    except (OSError, TramError, subprocess.TimeoutExpired) as exc:
        error = getattr(exc, 'code', 'EXECUTION_FAILED')
        if proc:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
            stop()
    finally:
        if proc:
            for name in streams:
                pipe = getattr(proc, name)
                if pipe and not pipe.closed:
                    os.set_blocking(pipe.fileno(), False)
                    deadline = time.monotonic() + .2
                    remaining_bytes = 1048576
                    while remaining_bytes > 0 and time.monotonic() < deadline:
                        try:
                            chunk = os.read(pipe.fileno(), min(65536, remaining_bytes))
                        except BlockingIOError:
                            streams[name]['drain_reason'] = 'pipe_open_without_eof'
                            break
                        if not chunk:
                            streams[name]['complete'] = True
                            break
                        remaining_bytes -= len(chunk)
                        stream = streams[name]
                        stream['hash'].update(chunk)
                        stream['bytes'] += len(chunk)
                        if enabled:
                            masked = stream['masker'].feed(chunk)
                            room = options['max_bytes_per_stream'] - len(stream['saved'])
                            stream['saved'].extend(masked[:max(0, room)])
                    if not streams[name]['complete'] and streams[name]['drain_reason'] is None:
                        streams[name]['drain_reason'] = 'byte_limit' if remaining_bytes <= 0 else 'time_limit'
                    pipe.close()
    if proc is None:
        for stream in streams.values():
            stream['complete'] = True
        cleanup['confirmed'] = True
    if not all(stream['complete'] for stream in streams.values()):
        cleanup.update({'confirmed': False, 'output_incomplete': True})
    if not cleanup['confirmed']:
        error = 'PROCESS_CLEANUP_FAILED'
    code = proc.poll() if proc else None
    if code == 127 and error is None:
        code, error = None, 'EXECUTION_FAILED'
    if enabled:
        try:
            for name, stream in streams.items():
                room = options['max_bytes_per_stream'] - len(stream['saved'])
                stream['saved'].extend(stream['masker'].feed(b'', final=True)[:max(0, room)])
                atomic(local_path(root, 'diagnostics/' + reservation['id'] + '/' + name + '.log'), bytes(stream['saved']))
            atomic(local_path(root, 'diagnostics/' + reservation['id'] + '/manifest.json'), canonical({'id': reservation['id'], 'created_epoch': time.time()}))
            diagnostics_prune(root, options)
        except (OSError, TramError) as exc:
            diagnostic_status, diagnostic_error = 'unavailable', getattr(exc, 'code', 'IO_ERROR')
    status = ('cancelled' if error == 'CANCELLED' else 'timed_out' if error == 'TIMEOUT'
              else 'cleanup_failed' if error == 'PROCESS_CLEANUP_FAILED'
              else 'failed' if error or code != 0 else 'succeeded')
    return {'exit_code': code, 'error': error, 'execution_status': status, 'cleanup': cleanup,
            'elapsed_ms': round((time.monotonic() - started) * 1000),
            'diagnostics_status': diagnostic_status, 'diagnostics_error': diagnostic_error,
            'output_complete': all(data['complete'] for data in streams.values()),
            'stream_complete': {name: data['complete'] for name, data in streams.items()},
            'output_incomplete_reason': {name: data['drain_reason'] for name, data in streams.items() if not data['complete']},
            **{name + '_digest': data['hash'].hexdigest() if data['complete'] else None for name, data in streams.items()},
            'partial_output_digests': {name: data['hash'].hexdigest() for name, data in streams.items() if not data['complete']},
            'output': {name: {'bytes': data['bytes'], 'truncated': data['bytes'] > options['max_bytes_per_stream']}
                       for name, data in streams.items()}}


def raw_json(root, relative):
    return json.loads(inside(root, relative).read_text())


def state_paths(root):
    paths = ['.tram/project.json', '.tram/installation.json']
    folder = inside(root, '.tram/tasks')
    if folder.exists():
        paths += [p.relative_to(root).as_posix() for p in sorted(folder.glob('*.json'))]
    return paths


def file_manifest(root, paths):
    result = {}
    for relative in paths:
        path = inside(root, relative)
        result[relative] = digest(path.read_bytes()) if path.exists() else None
    return result


def doctor(project=None):
    root = root_for(project)
    files, active, lock, issues = [], [], None, []
    observed, missing = {}, set()

    def issue(priority, code, severity, evidence, message, action):
        issues.append((priority, {'code': code, 'severity': severity, 'evidence': evidence,
                                 'message': message, 'next_action': action}))

    def owner_issue(evidence, states):
        if any(state in ('live', 'unknown') for state in states):
            issue(0, 'OWNER_ACTIVE_OR_UNKNOWN', 'blocked', evidence,
                  '진행 중이거나 소유권을 확인하지 못한 실행이 있어 쓰기 전에 확인이 필요합니다.',
                  '소유 실행 상태를 확인하세요 (status/doctor 읽기 조회).')
        else:
            issue(2, 'DEAD_OWNER', 'blocked', evidence,
                  '종료된 소유자의 기록이 남아 있습니다. 복구 가능 여부는 아직 확인하지 않았습니다.',
                  'recover preview로 복구 가능 여부를 확인하세요.')

    paths = state_paths(root)
    folder = inside(root, '.tram/local/runs')
    if folder.exists():
        paths += [p.relative_to(root).as_posix() for p in sorted(folder.glob('*.json'))]
    if inside(root, '.tram/local/write.lock').exists():
        paths.append('.tram/local/write.lock')
    for relative in paths:
        try:
            value = raw_json(root, relative)
            if not isinstance(value, dict):
                fail('INVALID_STATE', '객체가 필요합니다')
            observed[relative] = value
            entry = {'path': relative, 'readable': True, 'digest': digest(canonical(value))}
            if relative.endswith('write.lock'):
                lock = {'owner': value, 'liveness': owner_state(value)}
                owner_issue({'path': relative, 'liveness': lock['liveness']}, [lock['liveness']])
            elif '/runs/' in relative:
                # Run reservations have no persistent schema_version, including finished runs.
                if value.get('state') != 'finished':
                    run = {'id': value.get('id'), 'state': value.get('state'),
                           'parent_liveness': owner_state(value.get('parent')),
                           'child_liveness': owner_state(value.get('child')) if value.get('child') else 'absent'}
                    active.append(run)
                    owner_issue({'path': relative, **run}, [run['parent_liveness'], run['child_liveness']])
                if (value.get('state') not in ('reserved', 'running', 'stopping', 'finished')
                        or value.get('id') != Path(relative).stem
                        or not isinstance(value.get('slug'), str) or not value['slug']
                        or not isinstance(value.get('command_id'), str) or not value['command_id']
                        or type(value.get('recorded')) is not bool):
                    fail('INVALID_STATE', '실행 기록이 잘못되었습니다')
                if value.get('state') == 'finished' and value.get('result') and not value['recorded']:
                    issue(2, 'UNRECORDED_RESULT', 'blocked', {'path': relative, 'id': value['id']},
                          '종료된 실행 결과가 작업에 기록되지 않았습니다.', 'recover preview로 기록 상태를 확인하세요.')
            else:
                entry['schema_version'] = value.get('schema_version')
                if type(value.get('schema_version')) is not int or value['schema_version'] not in (1, SCHEMA):
                    fail('SCHEMA_INCOMPATIBLE', '지원하지 않는 schema입니다')
                if type(value.get('revision')) is not int or value['revision'] < 0:
                    fail('INVALID_STATE', '유효한 revision이 필요합니다')
                if relative == '.tram/installation.json':
                    if (type(value.get('linked')) is not bool or not isinstance(value.get('managed'), dict)
                            or not isinstance(value.get('conflicts'), list)
                            or any(not isinstance(value.get(k), str) or not value[k] for k in ('version', 'adapter'))):
                        fail('INVALID_STATE', '연결 기록 필드가 잘못되었습니다')
                if relative == '.tram/project.json':
                    validate_profile(root, value)
                if relative.startswith('.tram/tasks/'):
                    validate_task(value, Path(relative).stem)
                    entry.update({'phase': value.get('phase'), 'round': value.get('round')})
                    try:
                        entry['approvals_valid'] = approval_validity(root, value)
                    except (TramError, OSError, KeyError, TypeError) as exc:
                        entry['approval_status'] = 'unknown'
                        issue(1, 'APPROVAL_STATUS_UNKNOWN', 'unknown', {'path': relative, 'errorCode': getattr(exc, 'code', 'IO_ERROR')},
                              '작업 승인 근거를 읽지 못했습니다.', '해당 작업의 status 오류와 문서 경로를 확인하세요.')
                if value['schema_version'] == 1:
                    issue(4, 'LEGACY_SCHEMA', 'blocked', {'path': relative, 'schema_version': 1},
                          'schema 1은 읽기 진단이 가능하지만 쓰기가 제한됩니다.', 'migrate preview로 schema 2 전환 내용을 확인하세요.')
            files.append(entry)
        except (TramError, OSError, ValueError, UnicodeError, TypeError, KeyError, AttributeError) as exc:
            code = getattr(exc, 'code', 'INVALID_JSON' if isinstance(exc, (ValueError, UnicodeError)) else
                           'INVALID_STATE' if isinstance(exc, (TypeError, KeyError, AttributeError)) else 'IO_ERROR')
            files.append({'path': relative, 'readable': False, 'errorCode': code})
            if isinstance(exc, FileNotFoundError) and relative in ('.tram/project.json', '.tram/installation.json'):
                missing.add(relative)
            else:
                issue(1, 'STATE_UNREADABLE', 'blocked', {'path': relative, 'errorCode': code},
                      '기록을 해석하거나 검증하지 못해 사용 가능 여부를 확인할 수 없습니다.',
                      f'{relative}의 {code} 오류를 확인하세요. migration 가능 여부는 미확인입니다.')
    if '.tram/project.json' in missing:
        issue(3, 'PROJECT_NOT_CONNECTED', 'blocked', {'path': '.tram/project.json', 'state': 'missing'},
              '프로젝트 연결 설정이 없습니다.', 'init으로 프로젝트를 연결하세요.')
    elif '.tram/installation.json' in missing:
        issue(3, 'INSTALLATION_MISSING', 'blocked', {'path': '.tram/installation.json', 'state': 'missing'},
              '프로젝트 설정은 있으나 연결 기록이 누락된 부분 연결 상태입니다.', 'init으로 연결 기록을 확인하세요.')
    install = observed.get('.tram/installation.json', {})
    if install and (install.get('linked') is not True or install.get('conflicts')):
        issue(3, 'CONNECTION_INCOMPLETE', 'blocked', {'path': '.tram/installation.json', 'linked': install.get('linked'),
                                                 'conflicts': install.get('conflicts')},
              '프로젝트 연결이 완료되지 않았거나 충돌이 남아 있습니다.', 'init 결과와 관리 block 충돌을 확인하세요.')
    config = observed.get('.tram/project.json', {})
    if any(e['path'] == '.tram/project.json' and e['readable'] for e in files):
        commands = config['commands']
        if not commands or any(not c['confirmed'] for c in commands):
            issue(5, 'VERIFICATION_UNCONFIRMED', 'attention', {'path': '.tram/project.json',
                  'unconfirmed_commands': [c['id'] for c in commands if not c['confirmed']]},
                  '검증 명령이 없거나 미확정입니다. 검증 실행 전 설정이 필요합니다.', 'configure로 검증 명령을 확인하세요.')
    runtime = {'version': 'unknown', 'adapter': 'unknown', 'project_schema': config.get('schema_version') if type(config.get('schema_version')) is int else 'unknown',
               'package_identity': 'unknown', 'host_validation': 'unknown'}
    for name, reader in (('version', release_version), ('adapter', release_adapter)):
        try:
            value = reader()
            if value == 'unconfigured':
                fail('RELEASE_NOT_FOUND', '실행 패키지 host 메타데이터가 없습니다')
            runtime[name] = value
        except (TramError, OSError, ValueError, TypeError, AttributeError) as exc:
            issue(6, 'RUNTIME_METADATA_UNKNOWN', 'attention', {'field': name, 'errorCode': getattr(exc, 'code', 'INVALID_RELEASE')},
                  '실행 패키지 메타데이터를 확인하지 못했습니다. 프로젝트 진단은 유지합니다.',
                  '실행 패키지의 release 메타데이터를 확인하세요.')
    ordered = [item for _, item in sorted(issues, key=lambda item: (item[0], item[1]['code'], canonical(item[1]['evidence'])))]
    severity = {item['severity'] for item in ordered}
    readiness = {'status': 'blocked' if 'blocked' in severity else 'unknown' if 'unknown' in severity else 'attention' if ordered else 'ready',
                 'summary': ordered[0]['message'] if ordered else '관측한 프로젝트 진단 범위에서 작업 시작이 가능합니다. 호스트 전체 검증은 미확인입니다.',
                 'issues': ordered,
                 'next_action': ordered[0]['next_action'] if ordered else 'start로 작업을 시작하거나 status로 기존 작업을 확인하세요.'}
    return {'files': files, 'lock': lock, 'active_runs': active, 'writes': False,
            'recommendations': {'new_default_exclude': sorted(CACHE_DIRS),
                                'requires_explicit_configure': True, 'invalidates_evidence': True},
            'readiness': readiness, 'runtime': runtime, 'next_action': readiness['next_action']}


def invalidate_restored(value):
    if 'phase' not in value:
        return
    if value.get('phase') not in PHASES:
        fail('ROLLBACK_UNSAFE', '알 수 없는 완료 상태를 무효화할 수 없습니다')
    for key in ('verification', 'reviews'):
        for record in value.get(key, []):
            record['stale'] = True
            if key == 'reviews':
                record['verdict'] = 'implementation-defect'
    if value['phase'] == 'complete':
        value['phase'] = 'verifying'
    value['blocked'] = 'migration/restore 이후 재검증 필요'


def make_backup(root, category, changes):
    backup_id = uuid.uuid4().hex
    prefix = 'backups/' + category + '/' + backup_id
    entries = {}
    for index, (relative, after) in enumerate(changes.items()):
        target = inside(root, relative)
        data = target.read_bytes() if target.exists() else None
        stored = prefix + '/original-' + str(index)
        if data is not None:
            atomic(local_path(root, stored), data)
        entries[relative] = {'before': digest(data) if data is not None else None,
                             'after': digest(after) if after is not None else None,
                             'original': stored if data is not None else None}
    manifest = {'id': backup_id, 'category': category, 'created_at': now(), 'entries': entries,
                'journal': {relative: 'pending' for relative in entries}}
    manifest_path = local_path(root, prefix + '/manifest.json')
    atomic(manifest_path, canonical(manifest))
    return manifest, manifest_path


def apply_changes(root, category, changes):
    manifest, path = make_backup(root, category, changes)
    try:
        for relative, data in changes.items():
            target = inside(root, relative)
            expected = manifest['entries'][relative]['before']
            actual = digest(target.read_bytes()) if target.exists() else None
            if actual != expected:
                fail('RESTORE_CONFLICT', '기록이 변경되어 적용을 중단했습니다', path=relative)
            if data is None:
                if target.exists():
                    target.unlink()
            else:
                atomic(target, data)
            manifest['journal'][relative] = 'applied'
            atomic(path, canonical(manifest))
    except BaseException:
        manifest['status'] = 'partial'
        atomic(path, canonical(manifest))
        raise
    manifest['status'] = 'complete'
    atomic(path, canonical(manifest))
    return {'backup': manifest['id'], 'journal': manifest['journal'], 'status': 'complete'}


def migrate(project=None, mode='preview', from_schema=1, to_schema=2, expected_digest=None):
    root = root_for(project)
    if (from_schema, to_schema) not in ((1, 2), (2, 1)):
        fail('INVALID_ARGUMENT', '1↔2 명시적 migration만 지원합니다')
    def preview():
        values = {}
        for relative in state_paths(root):
            value = raw_json(root, relative)
            if not isinstance(value, dict) or value.get('schema_version') != from_schema:
                fail('SCHEMA_INCOMPATIBLE', '대상 schema가 일치하지 않습니다', path=relative)
            if type(value.get('revision')) is not int or value['revision'] < 0:
                fail('INVALID_STATE', '유효한 revision이 필요합니다', path=relative)
            values[relative] = value
        manifest = file_manifest(root, values)
        lock = inside(root, '.tram/local/write.lock')
        if lock.exists() or active_runs(root):
            fail('EXECUTION_ACTIVE', '잠금과 active run을 먼저 복구하세요')
        return values, {'from': from_schema, 'to': to_schema, 'files': manifest,
                        'digest': digest(canonical(manifest)), 'writes': False}
    if mode == 'preview':
        return preview()[1]
    if mode != 'apply' or not expected_digest:
        fail('INVALID_ARGUMENT', 'apply에는 expected digest가 필요합니다')
    with maintenance(root):
        values, report = preview()
        if report['digest'] != expected_digest:
            fail('DIGEST_CONFLICT', 'preview 이후 기록이 변경되었습니다')
        changes = {}
        for relative, value in values.items():
            value['schema_version'] = to_schema
            value['revision'] += 1
            if relative == '.tram/project.json':
                if to_schema == 2:
                    value.update({'diagnostics': dict(DIAGNOSTICS), 'metrics': dict(METRICS)})
                else:
                    value.pop('diagnostics', None)
                    value.pop('metrics', None)
            elif relative == '.tram/installation.json':
                value['schema_min'] = value['schema_max'] = to_schema
            else:
                invalidate_restored(value)
            changes[relative] = canonical(value) + b'\n'
        return {**apply_changes(root, 'migration', changes), 'from': from_schema, 'to': to_schema}


def recovery_report(root):
    lock_path = inside(root, '.tram/local/write.lock')
    owner = raw_json(root, '.tram/local/write.lock') if lock_path.exists() else None
    runs = [r for _, r in run_records(root) if r.get('state') != 'finished' or (r.get('result') and not r.get('recorded'))]
    targets = ['.tram/local/write.lock'] if owner else []
    targets += ['.tram/local/runs/' + r['id'] + '.json' for r in runs]
    manifest = file_manifest(root, targets)
    return {'digest': digest(canonical(manifest)), 'targets': manifest,
            'token': owner.get('token') if owner else 'no-lock',
            'start_id': owner.get('start_id') if owner else None,
            'liveness': owner_state(owner) if owner else 'absent', 'runs': runs, 'writes': False}


def recover(project=None, mode='preview', expected_digest=None, token=None):
    root = root_for(project)
    if mode == 'preview':
        return recovery_report(root)
    if mode != 'apply' or not expected_digest or not token:
        fail('INVALID_ARGUMENT', 'digest와 token이 필요합니다')
    with maintenance(root):
        report = recovery_report(root)
        if report['digest'] != expected_digest or report['token'] != token:
            fail('DIGEST_CONFLICT', '복구 대상 digest/token이 달라졌습니다')
        if report['liveness'] not in ('dead', 'absent'):
            fail('LOCK_OWNER_UNSAFE', '살아 있거나 불명확한 잠금은 복구하지 않습니다')
        changes = {}
        pending_tasks = {}
        original_tasks = {}
        task_snapshots = {}
        if report['liveness'] == 'dead':
            changes['.tram/local/write.lock'] = None
        for run in report['runs']:
            if owner_state(run.get('parent')) != 'dead':
                fail('EXECUTION_ACTIVE', '부모 종료를 확인하지 못했습니다')
            child = run.get('child')
            if child and owner_state(child) != 'dead':
                fail('PROCESS_CLEANUP_FAILED', '실행 종료를 확인하지 못했습니다; PID만으로 kill하지 않습니다')
            if any(owner_state(entry) != 'dead' for entry in run.get('observed', [])):
                fail('PROCESS_CLEANUP_FAILED', '관찰된 자손의 종료를 확인하지 못했습니다')
            if child:
                table = process_table()
                if any(e['pgid'] == child['pgid'] for e in table.values()):
                    fail('PROCESS_CLEANUP_FAILED', '소유 그룹이 남아 있습니다')
            result = run.get('result')
            if result and not run.get('recorded'):
                slug = run['slug']
                if slug not in pending_tasks:
                    original = task(root, slug)
                    original_tasks[slug] = original
                    pending_tasks[slug] = json.loads(json.dumps(original))
                    task_snapshots[slug] = fingerprint(root, profile(root), original)
                state = pending_tasks[slug]
                original = original_tasks[slug]
                snapshot = task_snapshots[slug]
                already_recorded = any(e.get('run_id') == run['id'] for e in state['verification'])
                if not already_recorded and (original['revision'] != run['revision'] or original['round'] != run['round']
                        or digest(canonical(snapshot)) != run['snapshot_digest']):
                    fail('STALE_RUN_RESULT', '중단된 증거의 revision/round/snapshot이 달라졌습니다')
                if not already_recorded:
                    result.update({'recorded': True, 'stale': False})
                    state['verification'].append(result)
                    state['revision'] = original['revision'] + 1
                    changes['.tram/tasks/' + slug + '.json'] = canonical(state)
                run['recorded'] = True
            run.update({'state': 'finished', 'recovered': True, 'recovered_at': now()})
            changes['.tram/local/runs/' + run['id'] + '.json'] = canonical(run)
        return apply_changes(root, 'recovery', changes)


def backup_manifest(root, backup):
    if not re.fullmatch('[a-f0-9]{32}', backup):
        fail('INVALID_ARGUMENT', 'backup UUID가 필요합니다')
    for category in ('recovery', 'migration', 'restore'):
        path = inside(root, '.tram/local/backups/' + category + '/' + backup + '/manifest.json')
        if path.is_file():
            manifest = json.loads(path.read_text())
            for relative, entry in manifest['entries'].items():
                inside(root, relative)
                if entry['original']:
                    original = inside(root, '.tram/local/' + entry['original'])
                    if digest(original.read_bytes()) != entry['before']:
                        fail('BACKUP_CHECKSUM_MISMATCH', 'backup checksum이 일치하지 않습니다', path=relative)
            return manifest
    fail('NOT_FOUND', 'backup을 찾을 수 없습니다')


def restore(project=None, mode='preview', backup=None, expected_digest=None):
    root = root_for(project)
    def preview():
        manifest = backup_manifest(root, backup)
        current = file_manifest(root, manifest['entries'])
        for relative, entry in manifest['entries'].items():
            expected = entry['after'] if manifest['journal'][relative] == 'applied' else entry['before']
            if current[relative] != expected:
                fail('RESTORE_CONFLICT', 'backup 이후 기록이 변경되었습니다', path=relative)
        if active_runs(root) or inside(root, '.tram/local/write.lock').exists():
            fail('EXECUTION_ACTIVE', '실행과 잠금을 먼저 종료하세요')
        return manifest, {'backup': backup, 'digest': digest(canonical(current)), 'targets': current, 'writes': False}
    if mode == 'preview':
        return preview()[1]
    if mode != 'apply' or not expected_digest:
        fail('INVALID_ARGUMENT', 'expected digest가 필요합니다')
    with maintenance(root):
        manifest, report = preview()
        if report['digest'] != expected_digest:
            fail('DIGEST_CONFLICT', 'restore preview 이후 변경되었습니다')
        changes = {}
        for relative, entry in manifest['entries'].items():
            data = inside(root, '.tram/local/' + entry['original']).read_bytes() if entry['original'] else None
            if data is not None and relative.startswith('.tram/tasks/'):
                value = json.loads(data)
                invalidate_restored(value)
                value['revision'] += 1
                data = canonical(value) + b'\n'
            # Restoring a dead write lock would recreate a block, so retain the diagnosed removal.
            if relative.endswith('write.lock'):
                continue
            changes[relative] = data
        return apply_changes(root, 'restore', changes)


def read_events(root):
    path = inside(root, '.tram/local/metrics/events.jsonl')
    if not path.exists():
        return []
    events = []
    with path.open() as stream:
        for line in stream:
            try:
                value = json.loads(line)
                if isinstance(value, dict) and value.get('id') and value.get('timestamp'):
                    events.append(value)
            except ValueError:
                fail('INVALID_METRICS', '손상된 지표 event가 있습니다')
    return events


def append_event(root, event):
    path = local_path(root, 'metrics/events.jsonl')
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        data = memoryview(canonical({'id': uuid.uuid4().hex, 'timestamp': now(), **event}) + b'\n')
        while data:
            written = os.write(fd, data)
            if written <= 0:
                raise OSError('metrics append stopped')
            data = data[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def episode_state(events, slug):
    selected = [e for e in events if e.get('slug') == slug]
    opened = [e for e in selected if e['type'] in ('task_started', 'reopened')]
    episode = opened[-1] if opened else None
    closed = next((e for e in reversed(selected) if e['type'] == 'task_closed'
                   and episode and e.get('episode_id') == episode['episode_id']), None)
    return episode, closed


def metrics_action(root, config, state, action, **fields):
    if not config.get('metrics', METRICS)['enabled']:
        return {'metrics_recorded': False, 'metrics_status': 'disabled'}
    try:
        events = read_events(root)
        slug = state['slug']
        episode, closed = episode_state(events, slug)
        if episode is None or (closed and (closed['outcome'] == 'failed' or state['phase'] != 'complete')):
            event = {'type': 'task_started' if episode is None else 'reopened',
                     'slug': slug, 'episode_id': uuid.uuid4().hex,
                     'action': action, 'revision': state['revision']}
            append_event(root, event)
            episode = event
            closed = None
        if action == 'start' and state['phase'] != 'complete':
            # A new task starts an episode; only a subsequent start is a resume.
            if any(e.get('slug') == slug for e in events):
                pending = [e for e in events if e.get('slug') == slug and e['type'] == 'resume_started'
                           and not any(c.get('resume_id') == e['resume_id'] and c['type'] == 'resume_closed' for c in events)]
                if pending:
                    return {'metrics_recorded': True, 'resume_id': pending[-1]['resume_id']}
                resume_id = uuid.uuid4().hex
                append_event(root, {'type': 'resume_started', 'slug': slug, 'episode_id': episode['episode_id'],
                                    'resume_id': resume_id, 'phase': state['phase'], 'round': state['round'],
                                    'revision': state['revision']})
                return {'metrics_recorded': True, 'resume_id': resume_id}
        if action in ('approve', 'transition'):
            for event in events:
                if event.get('slug') != slug or event['type'] != 'resume_started':
                    continue
                if any(e['type'] == 'resume_closed' and e.get('resume_id') == event['resume_id'] for e in events):
                    continue
                progressed = PHASES.index(state['phase']) > PHASES.index(event['phase']) or state['round'] > event['round']
                if progressed:
                    append_event(root, {'type': 'resume_closed', 'slug': slug, 'resume_id': event['resume_id'],
                                        'episode_id': episode['episode_id'], 'outcome': 'succeeded',
                                        'action': action, 'revision': state['revision']})
        if state['phase'] == 'complete' and not closed and action == 'transition':
            append_event(root, {'type': 'task_closed', 'slug': slug, 'episode_id': episode['episode_id'],
                                'outcome': 'complete', 'action': action, 'revision': state['revision']})
        if action == 'verification':
            append_event(root, {'type': 'verification', 'slug': slug, 'episode_id': episode['episode_id'], **fields})
        metrics_prune(root, config.get('metrics', METRICS))
        return {'metrics_recorded': True}
    except (OSError, TramError, ValueError) as exc:
        return {'metrics_recorded': False, 'metrics_warning': getattr(exc, 'code', 'IO_ERROR')}


def metrics_prune(root, options):
    path = inside(root, '.tram/local/metrics/events.jsonl')
    events = read_events(root)
    active_slugs = {r['slug'] for r in active_runs(root)}
    closed_episodes = {e['episode_id'] for e in events if e['type'] == 'task_closed'}
    pending_resumes = {e['resume_id'] for e in events if e['type'] == 'resume_started'} - {e['resume_id'] for e in events if e['type'] == 'resume_closed'}
    cutoff = time.time() - options['retention_days'] * 86400
    def removable(event):
        return (event.get('episode_id') in closed_episodes and event.get('slug') not in active_slugs
                and event.get('resume_id') not in pending_resumes)
    retained = [e for e in events if not (removable(e) and datetime.fromisoformat(e['timestamp']).timestamp() < cutoff)]
    size = sum(len(canonical(e)) + 1 for e in retained)
    removed_ids = set()
    for event in retained:
        if size <= options['max_project_bytes']:
            break
        if removable(event):
            removed_ids.add(event['id'])
            size -= len(canonical(event)) + 1
    retained = [e for e in retained if e['id'] not in removed_ids]
    removed = len(events) - len(retained)
    if removed:
        marker = {'id': uuid.uuid4().hex, 'timestamp': now(), 'type': 'retention_cut', 'removed': removed}
        atomic(path, b''.join(canonical(e) + b'\n' for e in retained + [marker]))
    return {'removed': removed}


def parse_time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (AttributeError, ValueError):
        fail('INVALID_ARGUMENT', 'timezone을 포함한 ISO8601 기간이 필요합니다')


def metrics(project=None, mode='summary', since=None, until=None, slug=None,
            outcome=None, reference=None, reason_code=None, resume_id=None,
            question_id=None, assessment=None, evidence_type=None, evidence_path=None,
            cost=None, tokens=None, source=None):
    root = root_for(project)
    if mode in ('summary', 'events'):
        lower, upper = parse_time(since), parse_time(until)
        if lower >= upper:
            fail('INVALID_ARGUMENT', 'since는 until보다 이전이어야 합니다')
        all_events = read_events(root)
        history = [e for e in all_events if parse_time(e['timestamp']) < upper and (not slug or e.get('slug') == slug)]
        events = [e for e in history if parse_time(e['timestamp']) >= lower]
        if mode == 'events':
            return {'events': events, 'writes': False}
        counts = {'complete': 0, 'failed': 0, 'pending': 0, 'excluded_prior_period': 0, 'unobserved_tasks': 0}
        slugs = {e['slug'] for e in history if e.get('slug')}
        for name in slugs:
            episode, closed = episode_state(history, name)
            if not episode:
                continue
            if not closed:
                counts['pending'] += 1
            elif parse_time(closed['timestamp']) < lower:
                counts['excluded_prior_period'] += 1
            else:
                counts[closed['outcome']] += 1
        folder = inside(root, '.tram/tasks')
        known = {p.stem for p in folder.glob('*.json')} if folder.exists() else set()
        counts['unobserved_tasks'] = len(({slug} if slug and slug in known else known if not slug else set()) - slugs)
        resumes = {'succeeded': 0, 'failed': 0, 'pending': 0, 'unexecuted': 0}
        starts = {e['resume_id']: e for e in history if e['type'] == 'resume_started'}
        ends = {e['resume_id']: e for e in history if e['type'] == 'resume_closed'}
        for identity, start in starts.items():
            end = ends.get(identity)
            if end and lower <= parse_time(end['timestamp']) < upper:
                resumes[end['outcome']] += 1
            elif not end and lower <= parse_time(start['timestamp']) < upper:
                resumes['pending'] += 1
        task_den = counts['complete'] + counts['failed']
        resume_den = resumes['succeeded'] + resumes['failed']
        cost_events = [e for e in events if e['type'] == 'host_measurement']
        return {'tasks': {**counts, 'denominator': task_den, 'completion_rate': counts['complete'] / task_den if task_den else None},
                'resumes': {**resumes, 'denominator': resume_den, 'success_rate': resumes['succeeded'] / resume_den if resume_den else None},
                'cost': sum(e['cost'] for e in cost_events if 'cost' in e) if any('cost' in e for e in cost_events) else None,
                'tokens': sum(e['tokens'] for e in cost_events if 'tokens' in e) if any('tokens' in e for e in cost_events) else None,
                'coverage': {'retention_truncated': any(e['type'] == 'retention_cut' for e in all_events),
                             'collection_gaps': any(e['type'] == 'collection_disabled' for e in all_events),
                             'limited_to_observed_events': True}, 'writes': False}
    with locked(root):
        config = profile(root)
        if mode == 'prune':
            return metrics_prune(root, config.get('metrics', METRICS))
        if mode == 'purge':
            if active_runs(root):
                fail('EXECUTION_ACTIVE', '실행 중 측정 자료는 삭제하지 않습니다')
            path = inside(root, '.tram/local/metrics/events.jsonl')
            if path.exists():
                path.unlink()
            return {'purged': True}
        if not config.get('metrics', METRICS)['enabled']:
            fail('METRICS_DISABLED', '지표 수집이 꺼져 있습니다')
        events = read_events(root)
        if mode in ('task-close', 'resume-close'):
            if not isinstance(reference, str) or not reference.strip() or len(reference) > 500:
                fail('REFERENCE_REQUIRED', 'caller reference가 필요합니다')
            if reason_code not in ('user-stopped', 'unresolved-blocker', 'external-failure', 'preflight-not-executed'):
                fail('INVALID_ARGUMENT', '마감 이유 코드가 필요합니다')
        if mode == 'task-close':
            state = task(root, slug)
            if outcome != 'failed' or reason_code == 'preflight-not-executed':
                fail('INVALID_ARGUMENT', '명시적인 failed 마감만 허용합니다')
            if active_runs(root, slug):
                fail('EXECUTION_ACTIVE', '실행 중 task를 마감할 수 없습니다')
            episode, closed = episode_state(events, slug)
            if not episode:
                metrics_action(root, config, state, 'observation')
                events = read_events(root)
                episode, closed = episode_state(events, slug)
            if closed:
                return {'idempotent': True, 'event': closed}
            event = {'type': 'task_closed', 'slug': slug, 'episode_id': episode['episode_id'],
                     'outcome': 'failed', 'reference': reference, 'reason_code': reason_code}
        elif mode == 'resume-close':
            starts = [e for e in events if e['type'] == 'resume_started' and e['resume_id'] == resume_id]
            if not starts or outcome not in ('failed', 'unexecuted'):
                fail('INVALID_ARGUMENT', '관측된 resume와 failed|unexecuted가 필요합니다')
            previous = [e for e in events if e['type'] == 'resume_closed' and e['resume_id'] == resume_id]
            if previous:
                return {'idempotent': True, 'event': previous[-1]}
            if outcome == 'unexecuted' and reason_code != 'preflight-not-executed':
                fail('INVALID_ARGUMENT', 'preflight 미실행 근거가 필요합니다')
            start = starts[-1]
            current = task(root, start['slug'])
            if current['phase'] != start['phase'] or current['round'] != start['round']:
                fail('RESUME_ALREADY_PROGRESSED', '실제 진행된 재개는 수동 실패로 닫지 않습니다')
            event = {'type': 'resume_closed', 'slug': start['slug'], 'episode_id': start['episode_id'],
                     'resume_id': resume_id, 'outcome': outcome, 'reference': reference, 'reason_code': reason_code}
        elif mode == 'question-assessment':
            if assessment not in ('necessary', 'unnecessary', 'unknown') or not question_id or not evidence_type or not evidence_path:
                fail('INVALID_ARGUMENT', '질문 식별자·평가·근거 유형·자료 경로가 필요합니다')
            inside(root, evidence_path)
            event = {'type': 'question_assessment', 'slug': slug, 'question_id': question_id,
                     'assessment': assessment, 'evidence_type': evidence_type, 'evidence_path': evidence_path}
        elif mode == 'host-measurement':
            if not source or (cost is None and tokens is None):
                fail('INVALID_ARGUMENT', '실측 값과 출처가 필요합니다')
            event = {'type': 'host_measurement', 'slug': slug, 'source': source}
            for key, value in (('cost', cost), ('tokens', tokens)):
                if value is not None:
                    if type(value) not in (int, float) or value < 0:
                        fail('INVALID_ARGUMENT', '측정값은 음수가 될 수 없습니다')
                    event[key] = value
        else:
            fail('INVALID_ARGUMENT', '지원하지 않는 metrics 행동입니다')
        append_event(root, event)
        metrics_prune(root, config.get('metrics', METRICS))
        return {'recorded': True, 'event': event}


def diagnostics(project=None, mode='prune', run_id=None):
    root = root_for(project)
    if mode == 'show':
        if not run_id or not re.fullmatch('[a-f0-9]{32}', run_id):
            fail('INVALID_ARGUMENT', 'run UUID가 필요합니다')
        prefix = '.tram/local/diagnostics/' + run_id + '/'
        manifest = raw_json(root, prefix + 'manifest.json')
        return {'manifest': manifest, 'stdout': inside(root, prefix + 'stdout.log').read_text(),
                'stderr': inside(root, prefix + 'stderr.log').read_text(), 'writes': False}
    if mode not in ('prune', 'purge'):
        fail('INVALID_ARGUMENT', 'diagnostics show|prune|purge를 사용하세요')
    with locked(root):
        options = dict(profile(root).get('diagnostics', DIAGNOSTICS))
        if mode == 'purge':
            options['retention_days'] = 0
        return diagnostics_prune(root, options)


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        fail("INVALID_ARGUMENT", message)


def main(argv=None):
    parser = JsonParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True, parser_class=JsonParser)
    sub.add_parser("contract", help="프로젝트 없이 action·설정·review 입력 계약을 JSON으로 조회")
    for name in ("init", "status", "start", "approve", "transition", "verify-run", "review", "unlink", "configure", "migration-preview", "doctor"):
        command = sub.add_parser(name)
        command.add_argument("--project")
        if name in ("start", "approve", "transition", "verify-run", "review", "status"):
            command.add_argument("--slug", required=name != "status")
        if name == "start":
            command.add_argument("--route", choices=ROUTES)
        if name == "approve":
            command.add_argument("--scope", choices=("prd", "plan"), required=True)
            command.add_argument("--quote", required=True)
            command.add_argument("--session", required=True)
        if name == "transition":
            command.add_argument("--action", choices=ACTIONS, required=True)
            command.add_argument("--strength", choices=("light", "full"))
            command.add_argument("--reason", help="perf light의 저위험·테스트 근거 최소 인용")
            command.add_argument("--manual-full-continuation", action="store_true",
                                 help="사용자가 직접 요청한 추가 full 검증 라운드")
        if name == "verify-run":
            command.add_argument("--command", required=True)
        if name in ("review", "configure"):
            command.add_argument("--file", required=True)
    for name in ('migrate', 'recover', 'restore', 'metrics', 'diagnostics'):
        command = sub.add_parser(name)
        command.add_argument('mode')
        command.add_argument('--project')
        if name == 'migrate':
            command.add_argument('--from', dest='from_schema', type=int, required=True)
            command.add_argument('--to', dest='to_schema', type=int, required=True)
        if name in ('migrate', 'recover', 'restore'):
            command.add_argument('--expected-digest')
        if name == 'recover':
            command.add_argument('--token')
        if name == 'restore':
            command.add_argument('--backup', required=True)
        if name == 'diagnostics':
            command.add_argument('--run-id')
        if name == 'metrics':
            for key in ('since', 'until', 'slug', 'outcome', 'reference', 'reason-code', 'resume-id',
                        'question-id', 'assessment', 'evidence-type', 'evidence-path', 'source'):
                command.add_argument('--' + key)
            command.add_argument('--cost', type=float)
            command.add_argument('--tokens', type=int)
    try:
        args = vars(parser.parse_args(argv))
        operation = args.pop("operation")
        result = globals()[operation.replace("-", "_")](**args)
        if operation == 'verify-run':
            status = result['execution_status']
            ok = status == 'succeeded' and not result.get('stale') and result.get('recorded')
            error = None if ok else result.get('registration_error') or result.get('error') or 'VERIFY_FAILED'
            payload = {'ok': ok, 'recorded': result.get('recorded', False),
                       'execution_status': status, 'errorCode': error, 'result': result}
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 2 if result.get('registration_error') else 0 if ok else 130 if status == 'cancelled' else 1
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, sort_keys=True))
        return 0
    except TramError as error:
        extra = {'recorded': False, 'execution_status': 'not_started', 'result': None} if locals().get('operation') == 'verify-run' else {}
        print(json.dumps({"ok": False, "errorCode": error.code, "message": str(error), **error.details, **extra}, ensure_ascii=False))
        return 2
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"ok": False, "errorCode": "INVALID_JSON" if isinstance(error, ValueError) else "IO_ERROR", "message": type(error).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(child_entry() if len(sys.argv) > 1 and sys.argv[1] == "_child" else main())
