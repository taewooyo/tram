#!/usr/bin/env python3
"""Opt-in native Codex lifecycle. Unit/package tests never count as native evidence.

Only this run's CODEX_HOME and fixture repositories are modified. Authentication,
hook trust, and each fixture's document approvals remain actual user decisions.
The manifest stores digests and metadata, never CLI output or conversation text.
"""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import shlex
import selectors
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / ".tram/local/native-lifecycle"
STAGES = ("preflight", "git-probe", "prepare", "install", "pilot-python", "pilot-node",
          "continue-python", "continue-node", "resume-python", "resume-node", "upgrade",
          "candidate-check-python", "candidate-check-node", "remove", "rollback")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def tree(path):
    """Include contents, symlink targets and executable bits; omit Git internals."""
    result = {}
    if not path.exists():
        return result
    for item in sorted(path.rglob("*")):
        rel = item.relative_to(path)
        if ".git" in rel.parts:
            continue
        if item.is_symlink():
            result[str(rel)] = {"symlink": os.readlink(item)}
        elif item.is_file():
            result[str(rel)] = {"sha256": digest(item.read_bytes()),
                                "executable": bool(item.stat().st_mode & 0o111)}
    return result


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temp.replace(path)


class Blocked(Exception):
    pass


class Harness:
    def __init__(self, run, baseline, candidate, codex="codex"):
        self.run = Path(run).resolve()
        if self.run.parent != RUNS.resolve():
            raise Blocked("run must be an immediate child of .tram/local/native-lifecycle")
        uuid.UUID(self.run.name)
        self.baseline, self.candidate = Path(baseline).resolve(), Path(candidate).resolve()
        self.codex = codex
        self.home = self.run / "codex-home"
        self.manifest = self.run / "manifest.json"
        self.state = json.loads(self.manifest.read_text()) if self.manifest.exists() else {
            "schema_version": 2, "run_id": self.run.name, "host": "codex",
            "native_lifecycle_complete": False, "stages": {stage: {"status": "not-run"} for stage in STAGES}, "commands": [],
            "sessions": {}, "snapshots": {}, "gates": {}, "server": None}
        if self.state.get("schema_version") == 1:
            if self.state.get("sessions") or self.state.get("candidate_installed"):
                raise Blocked("old lifecycle manifest cannot supply strengthened native evidence; use a fresh run")
            self.state["schema_version"] = 2
        for stage in STAGES:
            self.state["stages"].setdefault(stage, {"status": "not-run"})
        for key, value in (("baseline", self.baseline), ("candidate", self.candidate)):
            previous = self.state.get(key)
            if previous and previous != str(value):
                raise Blocked("package paths cannot change within a run")
            self.state[key] = str(value)

    def save(self):
        atomic(self.manifest, self.state)

    def env(self):
        # Explicitly remove inherited credential overrides. No default auth copying.
        env = {k: v for k, v in os.environ.items() if k not in {
            "OPENAI_API_KEY", "OPENAI_ORG_ID", "OPENAI_ORGANIZATION", "OPENAI_PROJECT_ID",
            "CODEX_ACCESS_TOKEN", "CODEX_API_KEY", "OPENAI_BASE_URL"}}
        env["CODEX_HOME"] = str(self.home)
        return env

    def command(self, kind, argv, cwd=None, timeout=90, native=False,
                stdout_limit=2097152, stderr_limit=65536):
        self.home.mkdir(parents=True, exist_ok=True)
        config = self.home / "config.toml"
        if not config.exists():
            config.write_text('cli_auth_credentials_store = "file"\n')
        started = datetime.now(timezone.utc).isoformat()
        started_ns = time.time_ns()
        proc = subprocess.Popen(argv, cwd=cwd or self.run, env=self.env(),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        hashes = {key: hashlib.sha256() for key in buffers}
        counts = {key: 0 for key in buffers}
        limits = {"stdout": stdout_limit, "stderr": stderr_limit}
        selector = selectors.DefaultSelector()
        for key in buffers:
            stream = getattr(proc, key)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, key)
        deadline = time.monotonic() + timeout
        reason, stopping, killed, exited, drain_failed = None, None, False, None, False
        def stop(cause):
            nonlocal reason, stopping
            if reason is None:
                reason, stopping = cause, time.monotonic()
                # The live, unreaped Popen child owns this group. Unknown escaped
                # descendants or a group whose root has exited are never killed.
                if proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
        try:
            while selector.get_map() or proc.poll() is None:
                now = time.monotonic()
                if proc.poll() is not None and exited is None:
                    exited = now
                if now >= deadline:
                    stop("NATIVE_COMMAND_TIMEOUT")
                if stopping is not None and now - stopping >= 2 and not killed and proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    killed = True
                if (exited is not None and now - exited >= 1) or (stopping is not None and now - stopping >= 5):
                    drain_failed = True
                    reason = reason or "NATIVE_OUTPUT_DRAIN_FAILED"
                    break
                try:
                    ready = selector.select(0.05)
                except KeyboardInterrupt:
                    stop("NATIVE_COMMAND_CANCELLED")
                    continue
                for selected, _ in ready:
                    key, stream = selected.data, selected.fileobj
                    try:
                        chunk = os.read(stream.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(stream)
                        stream.close()
                        continue
                    hashes[key].update(chunk)
                    counts[key] += len(chunk)
                    available = max(0, limits[key] - len(buffers[key]))
                    buffers[key].extend(chunk[:available])
                    if len(chunk) > available:
                        stop("NATIVE_OUTPUT_LIMIT_EXCEEDED")
        finally:
            for selected in list(selector.get_map().values()):
                selected.fileobj.close()
            selector.close()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            # A failure to reap is explicit, rather than an unbounded wait.
            reason = reason or "NATIVE_PROCESS_CLEANUP_UNCONFIRMED"
        code = (130 if reason == "NATIVE_COMMAND_CANCELLED" else
                124 if reason == "NATIVE_COMMAND_TIMEOUT" else 125) if reason else proc.returncode
        self.state["commands"].append({"date": started, "kind": kind, "exit": code,
            "native": native, "host_version": self.state.get("host_version"),
            "invocation_id": str(uuid.uuid4()), "process_id": proc.pid,
            "started_ns": started_ns, "finished_ns": time.time_ns(),
            "stdout_sha256": hashes["stdout"].hexdigest(), "stderr_sha256": hashes["stderr"].hexdigest(),
            "stdout_bytes": counts["stdout"], "stderr_bytes": counts["stderr"],
            "stdout_truncated": counts["stdout"] > len(buffers["stdout"]),
            "stderr_truncated": counts["stderr"] > len(buffers["stderr"]),
            "output_complete": reason is None and not drain_failed, "errorCode": reason,
            "root_reaped": proc.returncode is not None,
            "cleanup_scope": "live owned group only; escaped descendants are unconfirmed on drain failure"})
        self.save()
        return code, buffers["stdout"].decode(errors="replace"), buffers["stderr"].decode(errors="replace")

    def require(self, *stages):
        for stage in stages:
            if self.state["stages"].get(stage, {}).get("status") != "passed":
                raise Blocked("required stage has not passed: " + stage)

    def checked(self, kind, argv, **kwargs):
        code, out, err = self.command(kind, argv, **kwargs)
        if code:
            raise Blocked(kind + " failed (exit " + str(code) + ", " + str(self.state["commands"][-1].get("errorCode")) + "); output digest recorded")
        return out

    def preflight(self):
        version = self.checked("host-version", [self.codex, "--version"], native=True)
        self.state["host_version"] = version.strip()
        self.state["commands"][-1]["host_version"] = version.strip()
        for args in (("plugin", "marketplace", "add"), ("plugin", "marketplace", "upgrade"),
                     ("plugin", "remove"), ("exec", "resume")):
            self.checked("capability-" + "-".join(args), [self.codex, *args, "--help"], native=True)
        self.checked("isolated-config", [self.codex, "plugin", "list", "--json"], native=True)
        code, out, err = self.command("isolated-auth", [self.codex, "login", "status"], native=True)
        if code or "not logged in" in (out + err).lower():
            self.state["authentication"] = "user-login-required"
            raise Blocked("Run in a user terminal: CODEX_HOME=" + str(self.home) + " codex login --device-auth")
        self.state["authentication"] = "available"

    def package(self, source, target):
        if not (source / ".codex-plugin/plugin.json").is_file():
            raise Blocked("Codex package missing: " + str(source))
        if target.exists():
            shutil.rmtree(target)  # Owned fixture checkout only; never source/package cache.
        shutil.copytree(source, target)

    def release_commit(self, source, label):
        checkout = self.run / "git-source"
        self.package(source, checkout / "plugin")
        marketplace = {"name": "tram-native-fixture", "plugins": [{"name": "tram",
            "source": {"source": "local", "path": "./plugin"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity"}]}
        atomic(checkout / ".agents/plugins/marketplace.json", marketplace)
        (checkout / "release-marker").write_text(label + "\n")
        self.checked("fixture-git-add", ["git", "add", "."], cwd=checkout)
        self.checked("fixture-git-commit", ["git", "-c", "user.name=Tram fixture", "-c",
            "user.email=fixture@invalid", "commit", "-m", label], cwd=checkout)
        commit = self.checked("fixture-git-head", ["git", "rev-parse", "HEAD"], cwd=checkout).strip()
        self.checked("fixture-git-push", ["git", "push", "origin", "HEAD:main"], cwd=checkout)
        return commit

    def git_init(self):
        checkout, bare = self.run / "git-source", self.run / "remote/repo.git"
        if checkout.exists() or bare.exists():
            raise Blocked("Git fixture already exists; use a fresh run after an interrupted probe")
        checkout.mkdir(parents=True)
        bare.parent.mkdir(parents=True)
        self.checked("fixture-git-init", ["git", "init", "--initial-branch=main", str(checkout)])
        self.checked("fixture-git-bare", ["git", "init", "--bare", "--initial-branch=main", str(bare)])
        self.checked("fixture-git-origin", ["git", "remote", "add", "origin", str(bare)], cwd=checkout)

    @contextlib.contextmanager
    def server(self, reuse=False):
        backend = Path(self.checked("git-exec-path", ["git", "--exec-path"]).strip()) / "git-http-backend"
        remote = self.run / "remote"
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_git(self):
                path, _, query = self.path.partition("?")
                if not path.startswith("/repo.git/"):
                    self.send_error(404)
                    return
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                env = {**os.environ, "GIT_PROJECT_ROOT": str(remote), "GIT_HTTP_EXPORT_ALL": "1",
                       "PATH_INFO": path, "QUERY_STRING": query, "REQUEST_METHOD": self.command,
                       "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                       "CONTENT_LENGTH": str(len(body)), "REMOTE_ADDR": "127.0.0.1"}
                proc = subprocess.run([str(backend)], input=body, capture_output=True, env=env, timeout=30)
                head, _, payload = proc.stdout.partition(b"\r\n\r\n")
                if not payload and b"\n\n" in proc.stdout:
                    head, payload = proc.stdout.split(b"\n\n", 1)
                headers = []
                status = 200
                for line in head.decode(errors="replace").splitlines():
                    key, sep, value = line.partition(":")
                    if not sep:
                        continue
                    if key.lower() == "status":
                        status = int(value.strip().split()[0])
                    else:
                        headers.append((key, value.strip()))
                self.send_response(status)
                for key, value in headers:
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload)
            do_GET = handle_git
            do_POST = handle_git
        port = self.state.get("git_port", 0) if reuse else 0
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.state["git_port"] = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.state["server"] = {"pid": os.getpid(), "port": server.server_port,
                                "owned": True, "active": True}
        self.save()
        try:
            yield "http://127.0.0.1:" + str(server.server_port) + "/repo.git"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)
            self.state["server"]["active"] = thread.is_alive()
            self.state["server"]["cleanup_confirmed"] = not thread.is_alive()
            self.save()

    def git_probe(self):
        # Capability probe is independent of account authentication; no agent is invoked.
        version = self.checked("host-version", [self.codex, "--version"], native=True).strip()
        self.state["host_version"] = version
        self.state["commands"][-1]["host_version"] = version
        self.git_init()
        self.state["baseline_tree"] = tree(self.baseline)
        first = self.release_commit(self.baseline, "baseline")
        with self.server() as url:
            self.checked("native-git-marketplace-add", [self.codex, "plugin", "marketplace", "add", url, "--json"], native=True)
            second = self.release_commit(self.candidate, "candidate")
            self.checked("native-git-marketplace-upgrade", [self.codex, "plugin", "marketplace", "upgrade", "tram-native-fixture", "--json"], native=True)
            self.state["git_releases"] = {"baseline": first, "candidate": second}
            self.state["candidate_tree"] = tree(self.candidate)
            self.release_commit(self.baseline, "restore baseline for pilots")
            self.checked("native-git-baseline-restore", [self.codex, "plugin", "marketplace", "upgrade", "tram-native-fixture", "--json"], native=True)
            self.checked("native-plugin-capability-add", [self.codex, "plugin", "add", "tram@tram-native-fixture", "--json"], native=True)
            self.selected_plugin(self.baseline)
            self.checked("native-plugin-capability-remove", [self.codex, "plugin", "remove", "tram@tram-native-fixture", "--json"], native=True)
        # A refresh is not proof of the selected plugin version; install verifies that later.

    def prepare(self):
        self.require("preflight", "git-probe")
        for stack in ("python", "node"):
            project = self.run / ("project-" + stack)
            if project.exists():
                raise Blocked("project exists; will not overwrite fixture work")
            shutil.copytree(ROOT / "tests/fixtures" / stack, project)
            (project / "AGENTS.md").write_text("사용자 관리 문서: 보존하십시오.\n")
            (project / "unrelated-dirty.txt").write_text("사용자의 기존 변경\n")
            self.checked("pilot-git-init", ["git", "init", "--initial-branch=main", str(project)])
            self.state["snapshots"][stack] = tree(project)
            runtime = [sys.executable, str(self.baseline / "runtime/tram.py")]
            self.checked("fixture-baseline-init", [*runtime, "init", "--project", str(project)])
            config = self.run / (stack + "-commands.json")
            argv = [sys.executable, "-m", "unittest", "discover"] if stack == "python" else ["node", "--test"]
            atomic(config, {"commands": [{"id": "test", "argv": argv, "cwd": ".", "confirmed": True, "required": True}]})
            self.checked("fixture-baseline-configure", [*runtime, "configure", "--file", str(config), "--project", str(project)])

    def selected_plugin(self, expected=None):
        output = self.checked("native-plugin-list", [self.codex, "plugin", "list", "--json"], native=True)
        data = json.loads(output)
        installed = [p for p in data.get("installed", []) if p.get("name") == "tram"]
        if len(installed) != 1:
            raise Blocked("selected Tram installation cannot be uniquely verified")
        self.state["selected_plugin_digest"] = digest(json.dumps(installed, sort_keys=True).encode())
        # Record non-secret identity metadata only; native versions must match the snapshot.
        self.state["selected_plugin"] = {k: installed[0].get(k) for k in ("name", "version", "marketplaceName")}
        if expected:
            version = json.loads((expected / ".codex-plugin/plugin.json").read_text())["version"]
            if installed[0].get("version") != version:
                raise Blocked("native selected version does not match expected package")
            cached = self.home / "plugins/cache/tram-native-fixture/tram" / version
            source, selected = tree(expected), tree(cached)
            if any(selected.get(k) != v for k, v in source.items()):
                raise Blocked("native installed tree does not match expected package")
            self.state["selected_plugin"]["tree_sha256"] = digest(json.dumps(selected, sort_keys=True).encode())
        return installed[0]

    def install(self):
        self.require("preflight", "git-probe", "prepare")
        self.checked("native-plugin-install", [self.codex, "plugin", "add", "tram@tram-native-fixture", "--json"], native=True)
        self.selected_plugin(self.baseline)
        self.state["installed_version"] = self.state["selected_plugin"]["version"]

    def current_package(self):
        return self.candidate if self.state.get("candidate_installed") else self.baseline

    def plugin_path(self):
        version = self.state.get("installed_version") or json.loads((self.current_package() / ".codex-plugin/plugin.json").read_text())["version"]
        return self.home / "plugins/cache/tram-native-fixture/tram" / version

    def fixture(self, stack):
        project = self.run / ("project-" + stack)
        task_path = project / ".tram/tasks/operational-pilot.json"
        if not task_path.exists():
            raise Blocked("native fixture task not created")
        task = json.loads(task_path.read_text())
        profile = json.loads((project / ".tram/project.json").read_text())
        runtime = self.plugin_path() / "runtime/tram.py"
        epoch = "candidate" if self.state.get("candidate_installed") else "baseline"
        expected = self.state.get(epoch + "_tree", {}).get("runtime/tram.py", {}).get("sha256")
        if not runtime.is_file() or not expected or digest(runtime.read_bytes()) != expected:
            raise Blocked("selected installed runtime is missing or differs from the frozen release")
        out = self.checked("fixture-runtime-status", [sys.executable,
            str(runtime), "status", "--project", str(project),
            "--slug", "operational-pilot"])
        status = json.loads(out)["result"]
        if task.get("slug") != "operational-pilot" or task.get("route") != "full":
            raise Blocked("fixture requires the expected full task")
        return project, task, profile, status

    def document(self, project, task, scope):
        path = project / task["documents"][scope]
        if path.is_symlink() or not path.resolve().is_relative_to(project.resolve()) or not path.is_file():
            raise Blocked("submitted document must be a regular fixture file")
        return path

    def approval_context(self, stack, fixture=None):
        project, task, profile, status = fixture or self.fixture(stack)
        phase = status.get("effective_phase")
        if phase not in ("prd_review", "plan_review"):
            raise Blocked("approval requires the current submitted document review phase")
        scope = phase.split("_", 1)[0]
        if scope == "plan" and status.get("approvals_valid", {}).get("prd") is not True:
            raise Blocked("plan approval requires a current PRD approval")
        path = self.document(project, task, scope)
        if not self.state["sessions"].get(stack):
            raise Blocked("approval has no actual saved native session")
        binding = {"run_id": self.run.name, "stack": stack, "project": str(project),
            "slug": task["slug"], "scope": scope, "phase": phase,
            "native_session_id": self.state["sessions"].get(stack),
            "task_revision": task["revision"], "document_sha256": digest(path.read_bytes()),
            "upstream_prd_sha256": digest(self.document(project, task, "prd").read_bytes()) if scope == "plan" else None}
        binding["gate_reference"] = digest(json.dumps(binding, sort_keys=True).encode())
        return binding

    def fixture_status(self, stack):
        project, task, profile, status = self.fixture(stack)
        docs = {scope: {"path": str(self.document(project, task, scope)),
                        "sha256": digest(self.document(project, task, scope).read_bytes())}
                for scope in ("prd", "plan") if (project / task["documents"][scope]).is_file()}
        result = {"phase": status.get("effective_phase"), "documents": docs,
            "task_sha256": digest(json.dumps(task, sort_keys=True).encode()),
            "round": task["round"], "snapshot": status["snapshot"]}
        if status.get("effective_phase") in ("prd_review", "plan_review"):
            result["approval_request"] = self.approval_context(stack, (project, task, profile, status))
        return result

    def check_approval(self, stack, approval):
        supplied = json.loads(Path(approval).read_text())
        if not isinstance(supplied, dict):
            raise Blocked("approval file must contain the submitted gate object")
        expected = self.approval_context(stack)
        # This binds caller attestation to its target; it does not authenticate a human.
        if any(supplied.get(key) != value for key, value in expected.items()):
            raise Blocked("approval does not match current fixture/session/submitted gate")
        for key in ("quote", "session"):
            if not isinstance(supplied.get(key), str) or not 1 <= len(supplied[key].strip()) <= 500:
                raise Blocked("approval requires actual user quote and caller session reference")
        previous = self.state.get("gates", {}).get(stack, {}).get("approval_request")
        if previous != expected:
            raise Blocked("approval gate was not submitted by the recorded native session")
        project, task, _, _ = self.fixture(stack)
        body = self.document(project, task, expected["scope"]).read_text()
        return supplied, task, body

    @staticmethod
    def document_body(text):
        # Runtime approve updates only the status marker. Other content stays bound.
        return re.sub(r"(?m)^> 상태:.*\n?", "", text, count=1).lstrip("\n")

    def approval_result(self, stack, supplied, previous, body):
        project, task, _, status = self.fixture(stack)
        scope = supplied["scope"]
        records = task.get("approvals", [])
        if len(records) != len(previous.get("approvals", [])) + 1 or records[:-1] != previous.get("approvals", []):
            raise Blocked("native approval changed unrelated approval history")
        approval = records[-1]
        document = self.document(project, task, scope)
        if (approval.get("scope") != scope or approval.get("path") != task["documents"][scope]
                or approval.get("quote") != supplied["quote"].strip()
                or approval.get("session") != supplied["session"].strip()
                or approval.get("digest") != digest(document.read_bytes())
                or status.get("approvals_valid", {}).get(scope) is not True
                or self.document_body(body) != self.document_body(document.read_text())):
            raise Blocked("native approval result is not bound to supplied user attestation and final document")
        if scope == "plan" and approval.get("upstream_digest") != supplied["upstream_prd_sha256"]:
            raise Blocked("native Plan approval changed upstream PRD binding")
        self.state.setdefault("approval_evidence", {}).setdefault(stack, []).append({
            "scope": scope, "gate_reference": supplied["gate_reference"],
            "before_document_sha256": supplied["document_sha256"], "after_document_sha256": approval["digest"],
            "quote_sha256": digest(supplied["quote"].strip().encode()),
            "caller_session_sha256": digest(supplied["session"].strip().encode())})

    @staticmethod
    def command_argv(command):
        try:
            argv = shlex.split(command)
            if len(argv) == 3 and Path(argv[0]).name in ("zsh", "bash", "sh") and argv[1] in ("-lc", "-c"):
                argv = shlex.split(argv[2])
            if any(token in (";", "&&", "||", "|", ">", ">>", "<") for token in argv):
                return []
            return argv
        except ValueError:
            return []

    def collect_native(self, stack, output, invocation, expected=None, reviewer=False):
        events = []
        for line in output.splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    events.append(value)
            except ValueError:
                continue
        sessions = {e.get("thread_id") for e in events if e.get("type") == "thread.started"}
        if len(sessions) != 1:
            raise Blocked("host JSONL did not expose one actual session ID")
        session = sessions.pop()
        uuid.UUID(session)
        if expected and expected != session:
            raise Blocked("resumed host session differs from saved fixture session")
        if not events or events[-1].get("type") != "turn.completed" or any(e.get("type") == "turn.failed" for e in events):
            raise Blocked("host JSONL did not confirm a completed turn")
        package_path, project = self.plugin_path(), self.run / ("project-" + stack)
        proof = {"session": session, "invocation_id": invocation, "runtime": [], "skills": [], "reviewers": [],
                 "origin": "cli_child" if reviewer else "native_cli_turn",
                 "generic_spawns": [], "generic_results": []}
        started_items = {}
        latest_turn_report = None
        latest_turn_completed = False
        for event_index, event in enumerate(events):
            if event.get("type") == "turn.started":
                latest_turn_report = None
                latest_turn_completed = False
            elif event.get("type") == "turn.completed":
                latest_turn_completed = True
            elif event.get("type") == "turn.failed":
                latest_turn_report = None
                latest_turn_completed = False
            item = event.get("item", {})
            if event.get("type") == "item.started" and item.get("id"):
                started_items[item["id"]] = (event_index, item)
            if (event.get("type") == "item.completed" and item.get("type") == "collab_tool_call"
                    and item.get("status") == "completed" and item.get("sender_thread_id") == session):
                # Observed native Codex parent event shape. It proves the spawn edge,
                # never the origin of command_execution events in the parent stream.
                for receiver in item.get("receiver_thread_ids", []):
                    try:
                        uuid.UUID(receiver)
                    except (ValueError, TypeError, AttributeError):
                        continue
                    if receiver == session:
                        continue
                    metadata = {"parent_session": session, "child_session": receiver, "item_id": item.get("id"),
                                "event_index": event_index, "tool": item.get("tool")}
                    start = started_items.get(item.get("id"))
                    if start and start[1].get("tool") == item.get("tool") and start[1].get("sender_thread_id") == session:
                        metadata["started_index"] = start[0]
                    if item.get("tool") == "spawn_agent" and metadata not in proof["generic_spawns"]:
                        proof["generic_spawns"].append(metadata)
                    state = item.get("agents_states", {}).get(receiver, {})
                    if state.get("status") == "completed":
                        result = {**metadata, "status": "completed",
                            "message_sha256": digest(str(state.get("message", "")).encode()),
                            "child_commands_verified": False}
                        try:
                            report = json.loads(state.get("message", ""))
                            run_ids = report.get("verification_run_ids", [])
                            if (report.get("run_id") == self.run.name and type(report.get("round")) is int
                                    and report["round"] > 0 and report.get("verdict") in ("pass", "implementation-defect", "design-problem")
                                    and isinstance(run_ids, list) and 0 < len(run_ids) <= 100):
                                for run_id in run_ids:
                                    uuid.UUID(run_id)
                                result["caller_attestation"] = {"run_id": self.run.name,
                                    "snapshot_sha256": digest(json.dumps(report.get("snapshot"), sort_keys=True).encode()),
                                    "round": report["round"], "verdict": report["verdict"], "verification_run_ids": run_ids}
                        except (ValueError, TypeError, AttributeError):
                            pass
                        proof["generic_results"].append(result)
            if reviewer and event.get("type") == "item.completed" and item.get("type") == "agent_message":
                latest_turn_report = None
                try:
                    report = json.loads(item.get("text", ""))
                    if isinstance(report, dict):
                        latest_turn_report = {key: report.get(key) for key in ("verdict", "snapshot", "round")}
                except ValueError:
                    pass
            if event.get("type") != "item.completed" or item.get("type") != "command_execution" or item.get("exit_code") != 0:
                continue
            argv = self.command_argv(item.get("command", ""))
            if not argv:
                continue
            if Path(argv[0]).name == "cat":
                for skill in ("init", "start"):
                    if str(package_path / "skills" / skill / "SKILL.md") in argv[1:]:
                        proof["skills"].append(skill)
            runtime = str(package_path / "runtime/tram.py")
            if len(argv) > 2 and re.fullmatch(r"python(?:[0-9]+(?:\.[0-9]+)*)?", Path(argv[0]).name) and argv[1] == runtime:
                args = argv[2:]
                def option(name):
                    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None
                if option("--project") != str(project) or (args[0] != "init" and option("--slug") != "operational-pilot"):
                    continue
                try:
                    response = json.loads(item.get("aggregated_output", ""))
                except ValueError:
                    continue
                if response.get("ok") is not True:
                    continue
                result = response.get("result", {})
                action = args[0]
                value = {"action": action, "command_sha256": digest(item["command"].encode()),
                         "call_id": item.get("id"), "event_index": event_index,
                         "started_index": started_items.get(item.get("id"), (None,))[0]}
                if action == "status":
                    value.update({"snapshot": result.get("snapshot"), "phase": result.get("effective_phase"),
                                  "round": result.get("task", {}).get("round")})
                elif action == "verify-run":
                    if option("--command") != result.get("command_id"):
                        continue
                    value["record"] = {key: result.get(key) for key in (
                        "id", "command_id", "command_digest", "snapshot", "round", "exit_code", "stale", "execution_status")}
                    value["timestamp"] = result.get("timestamp")
                proof["runtime"].append(value)
            # Independent child execution is accepted only from an actual codex exec command,
            # never an arbitrary reference or an echoed thread.started string.
            if (not reviewer and Path(argv[0]).name == Path(self.codex).name and len(argv) > 2
                    and argv[1] == "exec" and (len(argv) < 3 or argv[2] not in ("resume", "fork")) and "--json" in argv
                    and ("-C" in argv or "--cd" in argv)):
                option = "-C" if "-C" in argv else "--cd"
                if argv.index(option) + 1 < len(argv) and argv[argv.index(option) + 1] == str(project):
                    child = self.collect_native(stack, item.get("aggregated_output", ""), invocation,
                                                reviewer=True)
                    if child["session"] != session:
                        proof["reviewers"].append(child)
        if reviewer:
            if not latest_turn_completed or not latest_turn_report:
                raise Blocked("reviewer did not provide a final completed-turn report")
            proof["report"] = latest_turn_report
        return proof

    def host_path(self, path):
        """Only the isolated host session namespace; never arbitrary input."""
        root = self.home / "sessions"
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise Blocked("CHILD_RECORD_PATH_OUTSIDE_HOME") from exc
        if ".." in relative.parts:
            raise Blocked("CHILD_RECORD_PATH_OUTSIDE_HOME")
        for current in (self.home, root, *[root.joinpath(*relative.parts[:n]) for n in range(1, len(relative.parts) + 1)]):
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise Blocked("CHILD_RECORD_PATH_UNSAFE")
        return path

    def session_inventory(self):
        root = self.home / "sessions"
        if not root.exists() and not root.is_symlink():
            return {}
        self.host_path(root)
        result = {}
        visited = 0
        for folder, directories, names in os.walk(root, followlinks=False):
            visited += len(directories) + len(names)
            if visited > 4096 or len(Path(folder).relative_to(root).parts) > 8:
                raise Blocked("CHILD_RECORD_INVENTORY_LIMIT")
            for name in list(directories):
                if (Path(folder) / name).is_symlink():
                    directories.remove(name)
            for name in names:
                if not name.endswith(".jsonl"):
                    continue
                path = Path(folder) / name
                info = path.lstat()
                result[str(path.relative_to(root))] = {
                    "device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid,
                    "mode": info.st_mode, "links": info.st_nlink, "size": info.st_size,
                    "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}
        return result

    def generic_child(self, stack, parent, child_id):
        """Conditional adapter for known event JSONL, not unknown rollout wrappers.

        Host-local observations are not cryptographic identity. Same-user
        tampering outside the sandbox cannot be authenticated here.
        """
        spawns = [edge for edge in parent.get("generic_spawns", [])
                  if edge.get("child_session") == child_id and edge.get("parent_session") == parent["session"]
                  and edge.get("tool") == "spawn_agent" and isinstance(edge.get("started_index"), int)
                  and edge["started_index"] < edge["event_index"]]
        if len(spawns) != 1:
            raise Blocked("GENERIC_SPAWN_EDGE_UNVERIFIED")
        spawn = spawns[0]
        waits = [edge for edge in parent.get("generic_results", [])
                 if edge.get("child_session") == child_id and edge.get("parent_session") == parent["session"]
                 and edge.get("tool") == "wait" and edge.get("status") == "completed"
                 and isinstance(edge.get("started_index"), int)
                 and spawn["event_index"] < edge["started_index"] < edge["event_index"]]
        if not waits:
            raise Blocked("GENERIC_WAIT_COMPLETION_MISSING")
        wait = waits[-1]
        window = parent.get("host_window", {})
        required = ("started_ns", "finished_ns", "process_id")
        if (window.get("invocation_id") != parent.get("invocation_id")
                or any(type(window.get(key)) is not int for key in required)
                or window["started_ns"] >= window["finished_ns"] or window["process_id"] <= 0
                or window.get("native") is not True or window.get("exit") != 0
                or window.get("root_reaped") is not True or window.get("output_complete") is not True
                or not isinstance(window.get("sessions_before"), dict)):
            raise Blocked("PARENT_HOST_INVOCATION_UNVERIFIED")
        invocation = next((command for command in self.state["commands"]
                           if command.get("invocation_id") == parent["invocation_id"]), None)
        if (not invocation or not parent.get("parent_output_sha256")
                or parent["parent_output_sha256"] != invocation.get("stdout_sha256")
                or any(invocation.get(key) != window[key] for key in (*required, "native", "exit", "root_reaped", "output_complete"))):
            raise Blocked("PARENT_HOST_INVOCATION_UNLINKED")
        inventory = self.session_inventory()
        names = [name for name in inventory if (Path(name).name == child_id + ".jsonl" or
                 re.fullmatch(r"rollout-[0-9TZ:._+-]+-" + re.escape(child_id) + r"\.jsonl", Path(name).name))]
        if len(names) != 1:
            raise Blocked("CHILD_HOST_RECORD_MISSING" if not names else "CHILD_HOST_RECORD_AMBIGUOUS")
        name = names[0]
        path = self.host_path(self.home / "sessions" / name)
        info = inventory[name]
        if (not stat.S_ISREG(info["mode"]) or info["links"] != 1 or name in window["sessions_before"]
                or any(info["inode"] == previous.get("inode") and info["device"] == previous.get("device")
                       for previous in window["sessions_before"].values())):
            raise Blocked("CHILD_RECORD_NOT_FRESH_REGULAR_FILE")
        if not all(window["started_ns"] <= info[key] <= window["finished_ns"] for key in ("mtime_ns", "ctime_ns")):
            raise Blocked("CHILD_RECORD_OUTSIDE_INVOCATION_WINDOW")
        if not 0 < info["size"] <= 2097152:
            raise Blocked("CHILD_RECORD_SIZE_LIMIT")
        with contextlib.ExitStack() as descriptors:
            directory = os.open(self.home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.callback(os.close, directory)
            for part in ("sessions", *Path(name).parts[:-1]):
                directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                descriptors.callback(os.close, directory)
                directory_info = os.fstat(directory)
                if directory_info.st_uid != os.getuid() or directory_info.st_mode & 0o022:
                    raise Blocked("CHILD_RECORD_PATH_UNSAFE")
            fd = os.open(Path(name).name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            source = descriptors.enter_context(os.fdopen(fd, "rb"))
            before = os.fstat(source.fileno())
            data = source.read(2097153)
            after = os.fstat(source.fileno())
        self.host_path(path)
        current = path.lstat()
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if (identity(before) != identity(after) or identity(after) != identity(current)
                or before.st_dev != info["device"] or before.st_ino != info["inode"] or len(data) != info["size"]):
            raise Blocked("CHILD_RECORD_CHANGED_DURING_READ")
        try:
            lines = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
        except (ValueError, UnicodeError) as exc:
            raise Blocked("CHILD_HOST_FORMAT_UNSUPPORTED") from exc
        if (not lines or not all(isinstance(event, dict) for event in lines)
                or lines[0].get("type") != "thread.started" or lines[0].get("thread_id") != child_id):
            raise Blocked("CHILD_HEADER_ID_OR_FORMAT_MISMATCH")
        if lines[-1].get("type") != "turn.completed":
            raise Blocked("CHILD_TURN_INCOMPLETE")
        calls, finished = {}, set()
        for index, event in enumerate(lines):
            item = event.get("item", {})
            if not isinstance(item, dict):
                raise Blocked("CHILD_HOST_FORMAT_UNSUPPORTED")
            if item.get("type") != "command_execution":
                continue
            call_id = item.get("id")
            if not isinstance(call_id, str) or not call_id:
                raise Blocked("CHILD_COMMAND_CALL_ID_MISSING")
            if event.get("type") == "item.started":
                if call_id in calls:
                    raise Blocked("CHILD_COMMAND_CALL_ID_REUSED")
                calls[call_id] = (index, item.get("command"))
            elif event.get("type") == "item.completed":
                if (call_id not in calls or call_id in finished or calls[call_id][1] != item.get("command")
                        or type(item.get("exit_code")) is not int):
                    raise Blocked("CHILD_COMMAND_RESULT_UNLINKED")
                finished.add(call_id)
        if not calls or set(calls) != finished:
            raise Blocked("CHILD_COMMAND_RESULT_MISSING")
        child = self.collect_native(stack, data.decode("utf-8"), parent["invocation_id"], expected=child_id, reviewer=True)
        child["origin"] = "generic_host_session_stream"
        child["provenance"] = {"path": name, "sha256": digest(data), "file": info,
            "spawn_item_id": spawn["item_id"], "wait_item_id": wait["item_id"],
            "parent_session": parent["session"], "parent_invocation_id": parent["invocation_id"],
            "started_ns": window["started_ns"], "finished_ns": window["finished_ns"],
            "format": "codex-thread-command-events-v1", "attestation_only": False,
            "identity_limit": "local observations; same-user tampering is not authenticated"}
        child["provenance"]["child_session"] = child_id
        epoch = "candidate" if self.state.get("candidate_installed") else "baseline"
        previous = self.state.get("generic_provenance", {}).get(stack, {}).get(epoch)
        if previous and previous.get("child_session") == child_id and (previous.get("sha256") != digest(data) or previous.get("file") != info):
            raise Blocked("CHILD_RECORD_CHANGED_AFTER_COLLECTION")
        child["wait_attestation"] = wait.get("caller_attestation")
        return child

    def completion(self, stack):
        project, task, profile, status = self.fixture(stack)
        if (status.get("effective_phase") != "complete" or status.get("completion_issues")
                or not all(status.get("approvals_valid", {}).get(key) is True for key in ("prd", "plan"))):
            raise Blocked("current fixture approvals/tests/review are not complete")
        attestations = self.state.get("approval_evidence", {}).get(stack, [])
        for scope in ("prd", "plan"):
            records = [record for record in task.get("approvals", []) if record.get("scope") == scope]
            record = records[-1] if records else {}
            if not any(item.get("scope") == scope and item.get("after_document_sha256") == record.get("digest")
                       and item.get("quote_sha256") == digest(record.get("quote", "").strip().encode())
                       and item.get("caller_session_sha256") == digest(record.get("session", "").strip().encode())
                       for item in attestations):
                raise Blocked("current approval lacks a matching actual caller attestation gate")
        epoch = "candidate" if self.state.get("candidate_installed") else "baseline"
        proofs = self.state.get("native_evidence", {}).get(stack, {}).get(epoch, [])
        skills = {skill for proof in proofs for skill in proof["skills"]}
        native = [record for proof in proofs for record in proof["runtime"]]
        if skills != {"init", "start"} or not any(record["action"] == "init" for record in native):
            raise Blocked("actual selected plugin init/start loading and native connection are unverified")
        snapshot, round_number = status["snapshot"], task["round"]
        required = [command for command in profile["commands"] if command.get("required")]
        if not required:
            raise Blocked("no required real test command")
        reviews = [review for review in task.get("reviews", []) if review.get("round") == round_number]
        if not reviews:
            raise Blocked("no current fresh reviewer record")
        review = reviews[-1]
        implementation = self.state["sessions"].get(stack)
        if not implementation:
            raise Blocked("completion has no actual native implementation session")
        reference = review.get("reference", "")
        child_id = reference.removeprefix("codex:")
        try:
            uuid.UUID(child_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise Blocked("GENERIC_REVIEW_REFERENCE_INVALID") from exc
        parents = [proof for proof in proofs if any(edge.get("child_session") == child_id
                   for edge in proof.get("generic_spawns", []))]
        if len(parents) != 1:
            raise Blocked("GENERIC_SPAWN_EDGE_UNVERIFIED: CLI child and arbitrary references cannot pass")
        child = self.generic_child(stack, parents[0], child_id)
        if (not child or review.get("fresh") is not True or review.get("verdict") != "pass"
                or review.get("snapshot") != snapshot or child["session"] == implementation
                or review.get("implementer_reference") not in (implementation, "codex:" + implementation)
                or child.get("report") != {"verdict": "pass", "snapshot": snapshot, "round": round_number}):
            raise Blocked("reviewer reference lacks matching actual fresh native execution/report")
        previous = self.state.get("completed_reviews", {}).get(stack, {})
        if epoch == "candidate" and previous.get("baseline") == child["session"]:
            raise Blocked("candidate requires a fresh reviewer after update")
        if not any(value["action"] == "status" and value.get("snapshot") == snapshot
                   and value.get("round") == round_number for value in child["runtime"]):
            raise Blocked("reviewer did not inspect current runtime snapshot/round")
        all_runtime = native + child["runtime"]
        for command in required:
            records = [record for record in task.get("verification", [])
                       if record.get("command_id") == command["id"] and record.get("round") == round_number]
            record = records[-1] if records else {}
            if (not command.get("confirmed") or not record.get("id") or record.get("exit_code") != 0
                    or record.get("stale") or record.get("snapshot") != snapshot
                    or (epoch == "candidate" and (record.get("execution_status") != "succeeded"
                        or record.get("recorded") is not True or record.get("cleanup", {}).get("confirmed") is not True))):
                raise Blocked("missing/stale real runtime test evidence")
            expected = {key: record.get(key) for key in ("id", "command_id", "command_digest", "snapshot", "round", "exit_code", "stale", "execution_status")}
            if not any(value["action"] == "verify-run" and value.get("record") == expected for value in all_runtime):
                raise Blocked("runtime test record lacks matching actual native command event")
            matching = [value for value in child["runtime"] if value["action"] == "verify-run" and value.get("record") == expected]
            if not matching:
                raise Blocked("fresh reviewer did not execute the matching required runtime run")
            execution = matching[-1]
            try:
                uuid.UUID(record["id"])
                timestamp_ns = int(datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).timestamp() * 1e9)
            except (ValueError, KeyError, TypeError) as exc:
                raise Blocked("CHILD_RUNTIME_TIMESTAMP_OR_RUN_ID_INVALID") from exc
            provenance = child["provenance"]
            if (execution.get("timestamp") != record.get("timestamp")
                    or not provenance["started_ns"] // 1000000000 * 1000000000 <= timestamp_ns <= provenance["finished_ns"] + 1000000000):
                raise Blocked("CHILD_RUNTIME_RUN_OUTSIDE_HOST_WINDOW")
            if not any(value["action"] == "status" and value.get("snapshot") == snapshot
                       and value.get("round") == round_number and value["event_index"] < execution["started_index"]
                       for value in child["runtime"]):
                raise Blocked("CHILD_STATUS_NOT_BEFORE_VERIFICATION")
        required_ids = {next(record["id"] for record in reversed(task["verification"])
                             if record.get("command_id") == command["id"] and record.get("round") == round_number)
                        for command in required}
        attestation = child.get("wait_attestation") or {}
        if (attestation.get("run_id") != self.run.name or attestation.get("verdict") != "pass"
                or attestation.get("round") != round_number
                or attestation.get("snapshot_sha256") != digest(json.dumps(snapshot, sort_keys=True).encode())
                or set(attestation.get("verification_run_ids", [])) != required_ids):
            raise Blocked("GENERIC_WAIT_REPORT_MISMATCH")
        self.state.setdefault("completed_reviews", {}).setdefault(stack, {})[epoch] = child["session"]
        self.state.setdefault("generic_provenance", {}).setdefault(stack, {})[epoch] = child["provenance"]
        self.state["generic_reviewer_support"] = "conditionally verified known child event stream; actual native availability requires host evidence"
        return {"review_session": child["session"], "provenance_sha256": child["provenance"]["sha256"]}

    def completion_snapshot(self, stack):
        # Called only after completion() has accepted all required native evidence.
        project, task, _, status = self.fixture(stack)
        return {"snapshot": status["snapshot"], "round": task["round"],
            "task_sha256": digest(json.dumps(task, sort_keys=True).encode()),
            "project_tree": tree(project)}

    def native_turn(self, stack, prompt, resume=False):
        project = self.run / ("project-" + stack)
        expected = self.state["sessions"].get(stack) if resume else None
        if resume and not expected:
            raise Blocked("no actual native session ID for resume")
        argv = ([self.codex, "exec", "resume", "--json", expected, prompt] if resume else
                [self.codex, "exec", "--json", "--sandbox", "workspace-write", "-C", str(project), prompt])
        before_sessions = self.session_inventory()
        code, out, _ = self.command("native-resume" if resume else "native-pilot", argv,
                                  cwd=project, timeout=600, native=True)
        invocation = self.state["commands"][-1]["invocation_id"]
        if code:
            raise Blocked("native host invocation failed: " + str(self.state["commands"][-1].get("errorCode")) + "; output digest recorded")
        proof = self.collect_native(stack, out, invocation, expected=expected)
        command = self.state["commands"][-1]
        proof["host_window"] = {key: command.get(key) for key in (
            "invocation_id", "process_id", "started_ns", "finished_ns", "exit", "native", "root_reaped", "output_complete")}
        proof["host_window"]["sessions_before"] = before_sessions
        proof["parent_output_sha256"] = command.get("stdout_sha256")
        self.state["sessions"][stack] = proof["session"]
        epoch = "candidate" if self.state.get("candidate_installed") else "baseline"
        self.state.setdefault("native_evidence", {}).setdefault(stack, {}).setdefault(epoch, []).append(proof)
        self.save()
        return proof

    def pilot(self, stack, approval=None, continuing=False, candidate=False):
        self.require("install")
        if candidate:
            self.require("upgrade")
            if not self.state.get("candidate_installed"):
                raise Blocked("candidate revalidation requires the selected candidate installation")
        elif self.state.get("candidate_installed"):
            raise Blocked("baseline pilot must finish before candidate update")
        before_candidate = tree(self.run / ("project-" + stack)) if candidate else None
        if continuing and not self.state["sessions"].get(stack):
            raise Blocked("no actual native session ID for continuation")
        if not continuing and self.state["sessions"].get(stack):
            raise Blocked("session exists; use continue for submitted approvals")
        if continuing and not candidate and self.state["stages"].get("pilot-" + stack, {}).get("status") == "passed":
            raise Blocked("baseline work is complete; use final resume stage")
        if continuing:
            _, _, _, current_status = self.fixture(stack)
            if current_status.get("effective_phase") in ("prd_review", "plan_review") and not approval:
                self.state["gates"][stack] = self.fixture_status(stack)
                self.save()
                raise Blocked("actual user approval is required before continuing the submitted gate")
        supplied = previous = body = None
        if approval:
            if not continuing or candidate:
                raise Blocked("approval files are accepted only by continue stages")
            supplied, previous, body = self.check_approval(stack, approval)
        path = self.plugin_path()
        prompt = ("실제 설치 경로 " + str(path) + "의 skills/init/SKILL.md와 skills/start/SKILL.md를 명시적인 shell cat 명령으로 읽고 "
            "runtime/tram.py init --project 명령을 실제 호출하여 연결을 확인하십시오. 설치된 Tram start 스킬로 operational-pilot full 작업을 수행하십시오. "
            "기존 greet 함수에 빈 이름 거부 검사를 추가하십시오. 실제 PRD와 Plan 제출 후 각각 실제 사용자 승인을 기다리십시오. "
            "승인을 생성하거나 다른 프로젝트 승인을 재사용하지 마십시오. 기존 코드·dirty 파일·관리 문서를 보존하십시오. "
            "양 승인 후 실제 테스트와 fresh 독립 검토를 수행하십시오. 독립 검토는 adapter가 요구하는 fresh generic spawn으로 수행하고 CLI child로 대체하지 마십시오. "
            "reviewer는 현재 status snapshot/round를 읽고 runtime verify-run으로 required tests를 실행한 뒤 "
            "최종 응답에 코드펜스 없는 JSON {run_id,verdict,snapshot,round,verification_run_ids}를 반환해야 합니다. run_id는 " + self.run.name + "입니다. review reference는 실제 child thread UUID 또는 codex:UUID, "
            "implementer_reference는 실제 이 세션 UUID를 사용하십시오. 현재 설치 runtime을 사용하고 hook trust 우회는 하지 마십시오.")
        if candidate:
            prompt = ("현재 설치된 후보 경로 " + str(path) + "의 skills/init/SKILL.md와 skills/start/SKILL.md를 명시적인 shell cat으로 읽고 "
                "이 후보 runtime/tram.py init --project를 실제 실행하여 연결을 확인하십시오. operational-pilot 기존 작업에서 "
                "migration이 무효화한 검증만 새로 수행하십시오. 사용자 PRD/Plan 본문과 기존 승인·구현은 변경하지 마십시오. "
                "후보 runtime verify-run의 required tests와 adapter가 요구하는 fresh generic spawn reviewer를 실제 수행하십시오. CLI child로 대체하지 마십시오. "
                "reviewer는 실제 status snapshot/round 조회·runtime verify-run을 실행하고 마지막에 코드펜스 없는 JSON {run_id,snapshot,round,verdict,verification_run_ids}를 반환하십시오. run_id는 " + self.run.name + "입니다. "
                "새 reviewer child thread UUID 또는 codex:UUID를 review reference로 사용하고 완료하십시오. "
                "새 승인이 필요하거나 재검증이 불가능하면 해당 게이트에서 멈추십시오. hook trust 우회는 하지 마십시오.")
        if supplied:
            prompt += " 실제 사용자의 현재 제출 gate에 대한 승인만 전달합니다: " + json.dumps(supplied, ensure_ascii=False)
            prompt += " 이 scope만 approve하고 다음 미승인 문서를 제출한 뒤 멈추십시오."
        self.native_turn(stack, prompt, resume=continuing)
        if candidate:
            current = tree(self.run / ("project-" + stack))
            if any(current.get(key) != before_candidate.get(key) for key in set(current) | set(before_candidate) if not key.startswith(".tram/")):
                raise Blocked("candidate revalidation changed existing user code or immutable documents")
        if supplied:
            self.approval_result(stack, supplied, previous, body)
        self.state["gates"][stack] = self.fixture_status(stack)
        self.save()
        self.completion(stack)
        result = self.completion_snapshot(stack)
        key = ("candidate-check-" if candidate else "pilot-") + stack
        self.state["stages"][key] = {"status": "passed", "evidence": result}

    def resume(self, stack):
        self.require("pilot-" + stack)
        if not self.state["sessions"].get(stack):
            raise Blocked("no actual native session ID for resume")
        if self.state.get("candidate_installed"):
            raise Blocked("baseline recovery proof must precede candidate update")
        self.completion(stack)
        before = self.completion_snapshot(stack)
        prompt = ("재개 복원 확인만 수행하십시오. 기존 설치 runtime의 status --project PROJECT --slug operational-pilot을 "
                  "실제 호출하고 현재 승인·산출물·완료 상태를 확인하십시오. start/전이/수정/검증 실행은 하지 마십시오.")
        proof = self.native_turn(stack, prompt, resume=True)
        self.completion(stack)
        after = self.completion_snapshot(stack)
        if before != after or not any(value["action"] == "status" and value.get("phase") == "complete"
                and value.get("snapshot") == before["snapshot"] and value.get("round") == before["round"] for value in proof["runtime"]):
            raise Blocked("fresh native resume did not restore matching task/approvals/artifacts")
        self.state.setdefault("resume_evidence", {})[stack] = {"session": proof["session"],
            "invocation_id": proof["invocation_id"], "restored_task_sha256": after["task_sha256"]}

    def preserve(self, label):
        for stack in ("python", "node"):
            current = tree(self.run / ("project-" + stack))
            self.state.setdefault("preservation", {}).setdefault(label, {})[stack] = current
            original = self.state["snapshots"].get(stack, {})
            for name in ("unrelated-dirty.txt",):
                if current.get(name) != original.get(name):
                    raise Blocked("preservation failure: " + stack + "/" + name)
            if "AGENTS.md" in original:
                text = (self.run / ("project-" + stack) / "AGENTS.md").read_text()
                if "사용자 관리 문서: 보존하십시오." not in text:
                    raise Blocked("user-managed document content was lost")

    def compare_preservation(self, before, after, allow_runtime=False):
        for stack in ("python", "node"):
            old = self.state["preservation"][before][stack]
            new = self.state["preservation"][after][stack]
            keys = set(old) | set(new)
            for key in keys:
                if allow_runtime and key.startswith(".tram/"):
                    if key in old and key not in new:
                        raise Blocked("runtime history removed: " + key)
                    continue
                if old.get(key) != new.get(key):
                    raise Blocked("lifecycle changed user project path: " + key)

    def migrate_fixtures(self, old, new):
        if tree(self.candidate) != self.state.get("candidate_tree"):
            raise Blocked("candidate migration tool changed since the Git probe")
        for stack in ("python", "node"):
            project = self.run / ("project-" + stack)
            profile = json.loads((project / ".tram/project.json").read_text())
            if profile.get("schema_version") == new:
                continue
            if profile.get("schema_version") != old:
                raise Blocked("unexpected fixture schema before migration")
            runtime = [sys.executable, str(self.candidate / "runtime/tram.py")]
            args = ["--project", str(project), "--from", str(old), "--to", str(new)]
            out = self.checked("migration-preview", [*runtime, "migrate", "preview", *args])
            preview = json.loads(out)["result"]
            expected = preview.get("digest")
            if not expected:
                raise Blocked("migration preview did not provide expected digest")
            self.checked("migration-apply", [*runtime, "migrate", "apply", *args, "--expected-digest", expected])
            self.state.setdefault("migrations", []).append({"stack": stack, "from": old,
                "to": new, "preview_sha256": digest(out.encode())})

    def upgrade(self):
        self.require("install", "pilot-python", "pilot-node", "resume-python", "resume-node")
        if tree(self.candidate) != self.state.get("candidate_tree"):
            raise Blocked("candidate source changed since Git probe; create a fresh run")
        self.preserve("before-upgrade")
        self.release_commit(self.candidate, "pilot candidate upgrade")
        with self.server(reuse=True):
            self.checked("native-candidate-upgrade", [self.codex, "plugin", "marketplace", "upgrade", "tram-native-fixture", "--json"], native=True)
            self.checked("native-candidate-select", [self.codex, "plugin", "add", "tram@tram-native-fixture", "--json"], native=True)
        self.selected_plugin(self.candidate)
        self.state["installed_version"] = self.state["selected_plugin"]["version"]
        self.state["candidate_installed"] = True
        self.migrate_fixtures(1, 2)
        self.preserve("after-upgrade")
        self.compare_preservation("before-upgrade", "after-upgrade", allow_runtime=True)

    def remove(self):
        self.require("upgrade", "pilot-python", "pilot-node", "resume-python", "resume-node", "candidate-check-python", "candidate-check-node")
        self.preserve("before-remove")
        self.checked("native-plugin-remove", [self.codex, "plugin", "remove", "tram@tram-native-fixture", "--json"], native=True)
        self.preserve("after-remove")
        self.compare_preservation("before-remove", "after-remove")

    def rollback(self):
        self.require("remove")
        if tree(self.baseline) != self.state.get("baseline_tree"):
            raise Blocked("baseline source changed since Git probe")
        self.preserve("before-rollback")
        self.migrate_fixtures(2, 1)
        self.release_commit(self.baseline, "rollback baseline")
        with self.server(reuse=True):
            self.checked("native-rollback-source", [self.codex, "plugin", "marketplace", "upgrade", "tram-native-fixture", "--json"], native=True)
            self.checked("native-rollback-install", [self.codex, "plugin", "add", "tram@tram-native-fixture", "--json"], native=True)
        self.selected_plugin(self.baseline)
        self.state["installed_version"] = self.state["selected_plugin"]["version"]
        self.preserve("after-rollback")
        self.compare_preservation("before-rollback", "after-rollback", allow_runtime=True)
        self.state["candidate_installed"] = False
        self.state["native_lifecycle_complete"] = True

    def execute(self, stage, approval=None):
        if self.state["stages"].get(stage, {}).get("status") == "running":
            raise Blocked("stage has an unresolved running owner; inspect before retrying")
        if self.state["stages"].get(stage, {}).get("status") == "passed":
            raise Blocked("stage already passed; create a new run rather than repeat mutations")
        if approval and not stage.startswith("continue-"):
            raise Blocked("approval files are accepted only by continue stages")
        self.state["stages"][stage] = {"status": "running"}
        self.save()
        try:
            if stage.startswith("pilot-"):
                self.pilot(stage.split("-", 1)[1])
            elif stage.startswith("continue-"):
                self.pilot(stage.split("-", 1)[1], continuing=True, approval=approval)
            elif stage.startswith("resume-"):
                if approval:
                    raise Blocked("use continue stage for user approvals, final resume is read-only")
                self.resume(stage.split("-", 1)[1])
            elif stage.startswith("candidate-check-"):
                self.pilot(stage.rsplit("-", 1)[1], continuing=True, candidate=True)
            else:
                getattr(self, stage.replace("-", "_"))()
        except (Blocked, OSError, ValueError, subprocess.SubprocessError) as exc:
            self.state["stages"][stage] = {"status": "blocked", "reason": str(exc)}
            self.save()
            raise Blocked(str(exc)) from exc
        self.state["stages"][stage] = {"status": "passed"}
        self.save()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "status", *STAGES))
    parser.add_argument("--run", default=None, help="UUID run directory under .tram/local/native-lifecycle")
    parser.add_argument("--approval-file", help="user-supplied current approval_request binding plus quote/session; continue stages only")
    parser.add_argument("--baseline", default=str(ROOT / ".tram/local/operational-readiness-baseline/packages/codex"))
    parser.add_argument("--candidate", default=str(ROOT / "build/codex"))
    args = parser.parse_args(argv)
    if args.action == "preview":
        print(json.dumps({"stages": STAGES, "writes": "isolated UUID run directory only",
            "auth": "user device-login; no inherited credentials", "gates": "actual per-fixture PRD/Plan approvals; caller attestation is not identity authentication",
            "native_success": "not inferred from unit tests or host exit", "run": args.run}, indent=2))
        return 0
    run = Path(args.run) if args.run else RUNS / str(uuid.uuid4())
    try:
        harness = Harness(run, args.baseline, args.candidate)
        if args.action == "status":
            print(json.dumps(harness.state, indent=2))
        else:
            harness.execute(args.action, approval=args.approval_file)
            print(json.dumps({"ok": True, "run": str(run), "stage": args.action}))
        return 0
    except (Blocked, ValueError) as exc:
        print(json.dumps({"ok": False, "errorCode": "NATIVE_STAGE_BLOCKED", "reason": str(exc), "run": str(run),
                          "manifest": str(run / "manifest.json")}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
