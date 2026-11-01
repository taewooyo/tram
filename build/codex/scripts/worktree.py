#!/usr/bin/env python3
"""Opt-in Git worktree lifecycle helpers for Tram.

The helper never copies dirty files, runs a merge, or force-removes a worktree.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import platform

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "runtime"))
sys.dont_write_bytecode = True
import tram  # noqa: E402

SCHEMA = 1


class WorktreeError(ValueError):
    pass


def git(root: Path, *args: str, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          timeout=timeout, shell=False,
                          env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})


def checked(root: Path, *args: str, timeout: int = 10) -> bytes:
    try:
        result = git(root, *args, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorktreeError(f"Git 실행을 확인할 수 없습니다: {exc}") from exc
    if result.returncode:
        detail = os.fsdecode(result.stderr).strip()
        raise WorktreeError(detail or f"Git 명령 실패: {' '.join(args)}")
    return result.stdout


def project_root(value: str) -> Path:
    root = tram.root_for(value)
    if not shutil.which("git"):
        raise WorktreeError("Git이 설치되지 않아 worktree를 사용할 수 없습니다")
    return root


def workspace(root: Path) -> dict:
    script = Path(__file__).with_name("project-context.py")
    try:
        result = subprocess.run([sys.executable, str(script), "workspace", "--project",
                                 str(root), "--all"], capture_output=True, timeout=20,
                                shell=False, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorktreeError(f"workspace 상태 확인에 실패했습니다: {exc}") from exc
    try:
        payload = json.loads(result.stdout if result.returncode == 0 else result.stderr)
    except (ValueError, UnicodeError) as exc:
        raise WorktreeError("workspace 상태 결과를 읽을 수 없습니다") from exc
    if result.returncode or payload.get("ok") is not True:
        raise WorktreeError(payload.get("message", "workspace 상태를 확인할 수 없습니다"))
    state = payload["result"]
    if not state.get("git_root") or state.get("head") is None or state.get("dirty") is None:
        raise WorktreeError("검증된 Git 저장소, committed HEAD, 작업 상태가 필요합니다")
    return state


def reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            # macOS exposes /tmp and /var as system aliases into /private.
            if platform.system() == "Darwin" and current in (Path("/tmp"), Path("/var")):
                current = current.resolve(strict=True)
                continue
            raise WorktreeError(f"심볼릭 링크 경로는 허용하지 않습니다: {current}")


def canonical_new_path(raw: str, repo: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise WorktreeError("worktree 경로는 절대 경로로 지정해야 합니다")
    if ".." in path.parts:
        raise WorktreeError("worktree 경로에 상위 경로 표기를 사용할 수 없습니다")
    reject_symlink_components(path)
    parent = path.parent.resolve(strict=True)
    canonical = parent / path.name
    if canonical.exists() or canonical.is_symlink():
        raise WorktreeError("worktree 경로가 이미 존재합니다")
    if canonical == repo or canonical.is_relative_to(repo) or repo.is_relative_to(canonical):
        raise WorktreeError("worktree는 원본 저장소 바깥의 별도 경로여야 합니다")
    return canonical


def listed_worktrees(repo: Path) -> list[dict]:
    raw = checked(repo, "worktree", "list", "--porcelain", "-z")
    records = []
    current: dict[str, str | bool] = {}
    for item in raw.split(b"\0"):
        if not item:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = os.fsdecode(item).partition(" ")
        current[key] = True if key == "bare" else value
    if current:
        records.append(current)
    return records


def create(args) -> dict:
    root = project_root(args.project)
    state = workspace(root)
    repo = Path(state["git_root"])
    if state["detached"] or not state["branch"]:
        raise WorktreeError("detached HEAD에서는 worktree 격리를 만들지 않습니다")
    branch = args.branch
    checked(repo, "check-ref-format", "--branch", branch)
    probe = git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    if probe.returncode == 0:
        raise WorktreeError(f"branch가 이미 존재합니다: {branch}")
    if probe.returncode not in (1,):
        raise WorktreeError("branch 존재 여부를 확인하지 못했습니다")
    base = args.base or state["head"]
    resolved = os.fsdecode(checked(repo, "rev-parse", "--verify", "--end-of-options",
                                   f"{base}^{{commit}}")).strip()
    path = canonical_new_path(args.path, repo)
    checked(repo, "worktree", "add", "-b", branch, str(path), resolved, timeout=30)
    task_dir = path / ".tram/tasks"
    tram_state = {
        "project_config_exists": (path / ".tram/project.json").exists() or
                                 (path / ".tram/project.json").is_symlink(),
        "tasks_directory_exists": task_dir.exists() or task_dir.is_symlink(),
        "task_records": sorted(item.relative_to(path).as_posix() for item in task_dir.glob("*.json"))
                        if task_dir.is_dir() and not task_dir.is_symlink() else [],
        "installation_exists": (path / ".tram/installation.json").exists() or
                              (path / ".tram/installation.json").is_symlink(),
        "local_directory_exists": (path / ".tram/local").exists() or
                                  (path / ".tram/local").is_symlink(),
    }
    return {"command": "create", "project_root": str(root), "worktree": str(path),
            "branch": branch, "commit": resolved, "original_dirty_preserved": state["dirty"],
            "included_content": "선택한 commit의 tracked 파일만", "tram_state": tram_state,
            "tram_state_migrated": False,
            "resume": f"새 세션에서 이 경로를 다시 열거나 project 경로로 지정하세요: {path}"}


def list_worktrees(args) -> dict:
    root = project_root(args.project)
    state = workspace(root)
    records = listed_worktrees(Path(state["git_root"]))
    return {"command": "list", "project_root": str(root), "worktrees": records,
            "resume_note": "재개 시 사용할 worktree 경로를 사용자가 직접 다시 지정해야 합니다"}


def connect(args) -> dict:
    root = project_root(args.project)
    raw_target = Path(args.path).expanduser()
    reject_symlink_components(raw_target)
    target = raw_target.resolve(strict=True)
    state = workspace(target)
    records = listed_worktrees(Path(state["git_root"]))
    if not any(Path(str(item.get("worktree", ""))).resolve() == target for item in records):
        raise WorktreeError("선택 경로가 해당 저장소의 등록된 worktree가 아닙니다")
    return {"command": "connect", "previous_project_root": str(root),
            "project_root": str(target), "branch": state["branch"], "head": state["head"],
            "resume": "이 경로를 project root로 지정해 start를 실행하세요; 연결은 저장되지 않습니다"}


def disconnect(args) -> dict:
    current = project_root(args.project)
    current_state = workspace(current)
    destination = project_root(args.to)
    destination_state = workspace(destination)
    current_common = os.fsdecode(checked(Path(current_state["git_root"]),
                                         "rev-parse", "--path-format=absolute",
                                         "--git-common-dir")).strip()
    destination_common = os.fsdecode(checked(Path(destination_state["git_root"]),
                                             "rev-parse", "--path-format=absolute",
                                             "--git-common-dir")).strip()
    if Path(current_common).resolve() != Path(destination_common).resolve():
        raise WorktreeError("원본 경로가 현재 worktree와 같은 저장소가 아닙니다")
    record = next((item for item in listed_worktrees(Path(current_state["git_root"]))
                   if Path(str(item.get("worktree", ""))).resolve() == current), None)
    if record is None:
        raise WorktreeError("현재 경로가 등록된 worktree가 아닙니다")
    return {"command": "disconnect", "previous_project_root": str(current),
            "project_root": str(destination), "branch": current_state["branch"],
            "head": current_state["head"], "removed": False,
            "note": "지정한 원본 경로로 작업 대상을 전환합니다. worktree는 삭제되지 않습니다"}


def status_entries(path: Path, include_ignored: bool = False) -> list[bytes]:
    args = ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
    if include_ignored:
        args.append("--ignored=matching")
    return [entry for entry in checked(path, *args, timeout=20).split(b"\0") if entry]


def merge_suggestion(args) -> dict:
    target_root = project_root(args.project)
    target_state = workspace(target_root)
    target_repo = Path(target_state["git_root"])
    if target_state["branch"] != args.expected_branch:
        raise WorktreeError("원본 branch가 예상값과 달라 제안하지 않습니다")
    if target_state["head"] != args.expected_head:
        raise WorktreeError("원본 HEAD가 예상값과 달라 제안하지 않습니다")
    if target_state["entries"]:
        raise WorktreeError("원본에 tracked 또는 untracked 변경이 있어 merge 제안을 중단합니다")
    source = Path(args.source).expanduser().resolve(strict=True)
    source_state = workspace(source)
    target_common = os.fsdecode(checked(target_repo, "rev-parse", "--path-format=absolute",
                                        "--git-common-dir")).strip()
    source_common = os.fsdecode(checked(Path(source_state["git_root"]), "rev-parse",
                                        "--path-format=absolute", "--git-common-dir")).strip()
    if Path(source_common).resolve() != Path(target_common).resolve() or source == target_root:
        raise WorktreeError("source는 같은 저장소의 별도 linked worktree여야 합니다")
    if source_state["branch"] is None or source_state["head"] is None:
        raise WorktreeError("source branch와 committed HEAD를 확인할 수 없습니다")
    record = next((item for item in listed_worktrees(target_repo)
                   if Path(str(item.get("worktree", ""))).resolve() == source), None)
    if record is None or record.get("branch") != f"refs/heads/{source_state['branch']}" or source_state["entries"]:
        raise WorktreeError("source가 clean한 등록 branch worktree가 아닙니다")
    names = checked(target_repo, "diff", "--name-only", "-z",
                    f"{target_state['head']}..{source_state['head']}").split(b"\0")
    changed = [os.fsdecode(name) for name in names if name]
    ignored = set()
    if changed:
        ignored_raw = git(target_root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
        if ignored_raw.returncode:
            raise WorktreeError("원본 ignored 경로 충돌을 확인하지 못했습니다")
        ignored = {os.fsdecode(item) for item in ignored_raw.stdout.split(b"\0") if item}
    conflicts = sorted(path for path in changed for ignored_path in ignored
                       if path == ignored_path or path.startswith(ignored_path.rstrip("/") + "/")
                       or ignored_path.startswith(path.rstrip("/") + "/"))
    if conflicts:
        raise WorktreeError("merge 변경 경로와 원본 ignored 파일이 겹칩니다: " + ", ".join(conflicts))
    ancestor = git(target_repo, "merge-base", "--is-ancestor", target_state["head"], source_state["head"])
    if ancestor.returncode:
        raise WorktreeError("source가 원본 HEAD를 포함하지 않거나 ancestry를 확인하지 못했습니다")
    preflight = git(target_repo, "merge-tree", "--write-tree", target_state["head"], source_state["head"])
    if preflight.returncode:
        raise WorktreeError("merge preflight에서 충돌 또는 검사 오류가 있어 명령을 제안하지 않습니다")
    command = "git -C " + shlex.quote(str(target_root)) + " merge --no-ff " + shlex.quote(source_state["head"])
    return {"command": "suggest-merge", "executed": False, "project_root": str(target_root),
            "expected_branch": target_state["branch"], "expected_head": target_state["head"],
            "source_branch": source_state["branch"], "source_head": source_state["head"],
            "suggested_command": command,
            "warning": "상태 점검은 원자적 보호가 아니며 동시 편집을 막지 않습니다. 실행 직전 다시 확인하세요"}


def finish_observation(raw: str) -> dict:
    """Observe a registered root; failed checks stay unknown, never clean."""
    observed = {"path": raw, "status": "unknown", "branch": None, "head": None,
                "dirty": None, "tracked": None, "untracked": None, "ignored": None,
                "registered": None}
    try:
        path = Path(raw).expanduser().absolute()
        if ".." in path.parts:
            raise WorktreeError("worktree 경로에 상위 경로 표기를 사용할 수 없습니다")
        reject_symlink_components(path)
        root = project_root(str(path))
        observed["path"] = str(root)
        state = workspace(root)
        observed.update(branch=state["branch"], head=state["head"])
        if Path(state["git_root"]).resolve() != root:
            raise WorktreeError("프로젝트 경로는 하위 디렉터리가 아닌 worktree root여야 합니다")
        records = listed_worktrees(root)
        record = next((item for item in records
                       if Path(str(item.get("worktree", ""))).resolve() == root), None)
        observed["registered"] = record is not None
        if record is None:
            raise WorktreeError("선택 경로가 등록된 worktree가 아닙니다")
        entries = status_entries(root, include_ignored=True)
        # Rename/copy records have a second NUL field containing only the old path.
        statuses = []
        index = 0
        while index < len(entries):
            entry = entries[index]
            if len(entry) < 4 or entry[2:3] != b" ":
                raise WorktreeError("Git porcelain 상태 결과를 해석할 수 없습니다")
            status = entry[:2]
            statuses.append(status)
            index += 2 if b"R" in status or b"C" in status else 1
        observed.update(status="available", dirty=any(s != b"!!" for s in statuses),
                        tracked=sum(s not in (b"??", b"!!") for s in statuses),
                        untracked=statuses.count(b"??"), ignored=statuses.count(b"!!"),
                        reason="현재 로컬 worktree 상태를 확인했습니다")
    except (OSError, UnicodeError, ValueError, tram.TramError) as exc:
        observed["reason"] = str(exc)
    return observed


def finish_status(args) -> dict:
    """No user files, refs, index, settings or runtime writes; preflight may write Git objects."""
    source = finish_observation(args.project)
    target = finish_observation(args.target) if args.target else None

    def option(status, reason, next_action):
        return {"status": status, "reason": reason, "next_action": next_action}

    merge = option("unknown", "merge target이 지정되지 않았습니다",
                   "같은 저장소의 target worktree root를 --target으로 지정하세요")
    if source["status"] != "available":
        merge = option("unknown", source["reason"], "source 경로와 Git 상태를 먼저 확인하세요")
    elif target is not None:
        if target["status"] != "available":
            merge = option("unknown", target["reason"], "target 경로와 Git 상태를 확인하세요")
        elif not source["branch"] or not target["branch"]:
            merge = option("blocked", "detached HEAD에서는 branch를 확인할 수 없습니다",
                           "기존 변경을 보존하고 사용할 branch를 확인하세요")
        else:
            try:
                suggestion = merge_suggestion(argparse.Namespace(
                    project=target["path"], source=source["path"],
                    expected_branch=target["branch"], expected_head=target["head"]))
                merge = option("available", "기존 merge 상태·ancestry·ignored·preflight 검사를 통과했습니다",
                               "실행 권한을 별도로 확인하고 실행 직전 상태를 다시 검사하세요")
                merge["suggestion"] = suggestion
            except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired, tram.TramError) as exc:
                merge = option("blocked", str(exc),
                               "변경·ignored 파일을 보존하고 차단 사유를 해결한 뒤 다시 조회하세요")

    pr = option("unknown", source["reason"], "source 경로와 Git 상태를 확인하세요")
    if source["status"] == "available":
        try:
            remotes = os.fsdecode(checked(Path(source["path"]), "remote")).splitlines()
            gh_available = bool(shutil.which("gh"))
            missing = []
            if not source["branch"]:
                missing.append("detached HEAD")
            if source["dirty"]:
                missing.append("미커밋 tracked/untracked 변경")
            if not remotes:
                missing.append("로컬 remote 없음")
            if not gh_available:
                missing.append("gh 도구 없음")
            pr = option("blocked" if missing else "unknown",
                        ", ".join(missing) if missing else "로컬 준비 조건 확인; 인증·원격 접근·실제 PR 가능 여부는 미확인",
                        "파일을 보존하고 필요한 commit/remote/도구 준비 후 기존 push/pr 절차에서 인증과 실행 권한을 확인하세요")
            pr.update(local_readiness="blocked" if missing else "available",
                      remotes=remotes, gh_available=gh_available,
                      authentication="unknown", remote_capability="unknown")
        except (OSError, UnicodeError, ValueError) as exc:
            pr = option("unknown", str(exc), "로컬 remote 상태를 확인한 뒤 기존 push/pr 절차로 진행하세요")
    keep = option("available" if source["status"] == "available" else "unknown",
                  "현재 파일과 worktree를 그대로 유지합니다" if source["status"] == "available" else source["reason"],
                  "프로젝트·slug·source/target 경로·관측 branch/HEAD·남은 행동을 기존 로컬 작업 메모에 남기고 재개 시 다시 조회하세요")
    return {"command": "finish-status", "project_root": source["path"],
            "source": source, "target": target, "options": {"merge": merge, "pr": pr, "keep": keep},
            "executed": False,
            "read_only_note": "사용자 파일·refs·HEAD·index·설정·runtime·메모를 변경하지 않습니다. merge-tree --write-tree preflight는 Git 객체를 기록할 수 있습니다. 원격 접근은 하지 않습니다",
            "warning": "관측은 원자적 보호가 아닙니다. 실행 직전 상태를 다시 확인하세요"}


def remove(args) -> dict:
    root = project_root(args.project)
    state = workspace(root)
    repo = Path(state["git_root"])
    raw_target = Path(args.path).expanduser()
    if not raw_target.is_absolute():
        raise WorktreeError("worktree 경로는 절대 경로로 지정해야 합니다")
    reject_symlink_components(raw_target)
    target = raw_target.resolve(strict=True)
    if target == root or target == repo:
        raise WorktreeError("원본 작업공간은 remove 대상이 될 수 없습니다")
    record = next((item for item in listed_worktrees(repo)
                   if Path(str(item.get("worktree", ""))).resolve() == target), None)
    if record is None:
        raise WorktreeError("선택 경로가 등록된 worktree가 아닙니다")
    if status_entries(target, include_ignored=True):
        raise WorktreeError("변경·untracked·ignored 파일이 있어 삭제하지 않았습니다")
    checked(repo, "worktree", "remove", str(target), timeout=30)
    return {"command": "remove", "worktree": str(target), "removed": True, "forced": False}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subs = result.add_subparsers(dest="command", required=True)
    create_parser = subs.add_parser("create")
    create_parser.add_argument("--project", required=True)
    create_parser.add_argument("--path", required=True)
    create_parser.add_argument("--branch", required=True)
    create_parser.add_argument("--base")
    for name in ("list",):
        sub = subs.add_parser(name)
        sub.add_argument("--project", required=True)
    connect_parser = subs.add_parser("connect")
    connect_parser.add_argument("--project", required=True)
    connect_parser.add_argument("--path", required=True)
    disconnect_parser = subs.add_parser("disconnect")
    disconnect_parser.add_argument("--project", required=True)
    merge_parser = subs.add_parser("suggest-merge")
    merge_parser.add_argument("--project", required=True)
    merge_parser.add_argument("--source", required=True)
    merge_parser.add_argument("--expected-branch", required=True)
    merge_parser.add_argument("--expected-head", required=True)
    disconnect_parser.add_argument("--to", required=True)
    remove_parser = subs.add_parser("remove")
    remove_parser.add_argument("--project", required=True)
    remove_parser.add_argument("--path", required=True)
    finish_parser = subs.add_parser("finish-status")
    finish_parser.add_argument("--project", required=True)
    finish_parser.add_argument("--target")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        handlers = {"create": create, "list": list_worktrees, "connect": connect,
                    "disconnect": disconnect, "suggest-merge": merge_suggestion, "remove": remove,
                    "finish-status": finish_status}
        result = handlers[args.command](args)
        print(json.dumps({"schema_version": SCHEMA, "ok": True, "result": result},
                         ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, tram.TramError) as exc:
        message = str(exc)
        print(json.dumps({"schema_version": SCHEMA, "ok": False,
                          "errorCode": "WORKTREE_ERROR", "message": message},
                         ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
