"""Harness guard/metadata tests, explicitly not native host lifecycle evidence."""
import copy
import importlib.util
import json
import os
import signal
import time
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("native_lifecycle", ROOT / "scripts/native-lifecycle.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class NativeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.run = native.RUNS / str(uuid.uuid4())
        self.h = native.Harness(self.run, ROOT / "build/codex", ROOT / "build/codex")

    def tearDown(self):
        if self.run.exists():
            shutil.rmtree(self.run)

    def test_preview_has_no_writes(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/native-lifecycle.py"),
            "preview", "--run", str(self.run)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("actual per-fixture", result.stdout)
        self.assertFalse(self.run.exists())

    def test_outside_and_non_uuid_runs_refused(self):
        for path in (ROOT, native.RUNS / "not-a-uuid", native.RUNS / ".." / str(uuid.uuid4())):
            with self.assertRaises((native.Blocked, ValueError)):
                native.Harness(path, ROOT, ROOT)

    def test_environment_never_inherits_api_auth(self):
        with patch.dict(native.os.environ, {"OPENAI_API_KEY": "secret", "CODEX_ACCESS_TOKEN": "secret"}):
            env = self.h.env()
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("CODEX_ACCESS_TOKEN", env)
        self.assertEqual(env["CODEX_HOME"], str(self.run / "codex-home"))

    def test_manifest_retains_hashes_not_outputs(self):
        code, out, _ = self.h.command("test-only", [sys.executable, "-c", "print('secret-output')"])
        self.assertEqual(code, 0)
        self.assertIn("secret-output", out)
        raw = self.h.manifest.read_text()
        self.assertNotIn("secret-output", raw)
        data = json.loads(raw)
        self.assertFalse(data["commands"][0]["native"])
        self.assertFalse(data["native_lifecycle_complete"])
        self.assertEqual(data["commands"][0]["stdout_sha256"], native.digest(b"secret-output\n"))

    def test_bounded_dual_stream_hashes_and_no_raw_manifest(self):
        payload = b"x" * 100000
        code, out, err = self.h.command("bounded-test", [sys.executable, "-c",
            "import os; os.write(1,b'x'*100000); os.write(2,b'y'*100000)"],
            stdout_limit=100, stderr_limit=100)
        self.assertEqual(code, 125)
        self.assertLessEqual(len(out), 100)
        self.assertLessEqual(len(err), 100)
        record = self.h.state["commands"][-1]
        self.assertEqual(record["errorCode"], "NATIVE_OUTPUT_LIMIT_EXCEEDED")
        self.assertTrue(record["stdout_truncated"])
        self.assertFalse(record["output_complete"])
        self.assertNotIn("xxxx", self.h.manifest.read_text())
        # A normal completed stream hashes all consumed bytes incrementally.
        code, out, _ = self.h.command("hash-test", [sys.executable, "-c", "print('bounded')"])
        self.assertEqual(code, 0)
        self.assertEqual(self.h.state["commands"][-1]["stdout_sha256"], native.digest(b"bounded\n"))

    def test_timeout_with_closed_pipes_is_bounded_and_root_reaped(self):
        started = time.monotonic()
        code, _, _ = self.h.command("closed-pipe-timeout", [sys.executable, "-c",
            "import os,time; os.close(1); os.close(2); time.sleep(60)"], timeout=0.1)
        self.assertEqual(code, 124)
        self.assertLess(time.monotonic() - started, 4)
        self.assertTrue(self.h.state["commands"][-1]["root_reaped"])

    def test_escaped_pipe_drain_is_bounded_and_unrelated_process_survives(self):
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        child = None
        try:
            script = ("import subprocess,sys; p=subprocess.Popen([sys.executable,'-c',"
                      "'import time; time.sleep(60)'],start_new_session=True); print(p.pid,flush=True)")
            started = time.monotonic()
            code, out, _ = self.h.command("escaped-pipe-test", [sys.executable, "-c", script], timeout=10)
            child = int(out.strip())
            self.assertEqual(code, 125)
            self.assertLess(time.monotonic() - started, 4)
            self.assertEqual(self.h.state["commands"][-1]["errorCode"], "NATIVE_OUTPUT_DRAIN_FAILED")
            self.assertFalse(self.h.state["commands"][-1]["output_complete"])
            self.assertIsNone(unrelated.poll())
            # The harness did not claim ownership of or kill the escaped process.
            os.kill(child, 0)
        finally:
            if child:
                try:
                    os.kill(child, signal.SIGTERM)  # Test-created child, never detector input.
                except ProcessLookupError:
                    pass
            unrelated.terminate()
            unrelated.wait(timeout=3)

    def test_missing_auth_blocks_and_records(self):
        def fake(kind, argv, **kwargs):
            if kind == "host-version":
                self.h.state["commands"].append({"kind": kind})
                return "codex test-version"
            return "{}"
        with patch.object(self.h, "checked", side_effect=fake), patch.object(
                self.h, "command", return_value=(1, "", "Not logged in")):
            with self.assertRaisesRegex(native.Blocked, "device-auth"):
                self.h.execute("preflight")
        self.assertEqual(self.h.state["stages"]["preflight"]["status"], "blocked")
        self.assertFalse(self.h.state["native_lifecycle_complete"])

    def test_install_requires_all_preconditions(self):
        with self.assertRaisesRegex(native.Blocked, "preflight"):
            self.h.execute("install")
        self.assertEqual(self.h.state["commands"], [])

    def test_resume_requires_actual_session(self):
        self.h.state["stages"]["install"] = {"status": "passed"}
        self.h.state["stages"]["pilot-python"] = {"status": "passed"}
        with self.assertRaisesRegex(native.Blocked, "actual native session"):
            self.h.execute("resume-python")

    def test_package_paths_cannot_be_switched_on_resume(self):
        self.h.save()
        with self.assertRaisesRegex(native.Blocked, "paths cannot change"):
            native.Harness(self.run, ROOT / "src", ROOT / "build/codex")

    def test_no_overwrite_of_existing_fixture(self):
        self.h.state["stages"].update({s: {"status": "passed"} for s in ("preflight", "git-probe")})
        target = self.run / "project-python"
        target.mkdir(parents=True)
        (target / "user.txt").write_text("keep")
        with self.assertRaisesRegex(native.Blocked, "will not overwrite"):
            self.h.prepare()
        self.assertEqual((target / "user.txt").read_text(), "keep")

    def fixture_case(self, phase="prd_review"):
        project = self.run / "project-python"
        documents = {scope: "docs/" + scope + "/operational-pilot.md" for scope in ("prd", "plan")}
        for scope, relative in documents.items():
            path = project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# " + scope + "\n\nReviewed content\n")
        task = {"slug": "operational-pilot", "route": "full", "phase": phase,
                "revision": 4, "round": 1, "documents": documents, "approvals": [],
                "verification": [], "reviews": []}
        profile = {"commands": [{"id": "test", "required": True, "confirmed": True}]}
        status = {"effective_phase": phase, "approvals_valid": {"prd": phase != "prd_review", "plan": False},
                  "completion_issues": [], "snapshot": {"files": {"app.py": "current"}}}
        self.h.state["sessions"]["python"] = str(uuid.uuid4())
        self.h.fixture = lambda stack: (project, task, profile, status)
        return project, task, profile, status

    def approval_file(self, binding):
        path = self.run / "approval.json"
        native.atomic(path, {**binding, "quote": "actual test caller quote", "session": "test-caller-session"})
        return path

    def test_stale_document_approval_refused(self):
        project, _, _, _ = self.fixture_case()
        binding = self.h.approval_context("python")
        self.h.state["gates"]["python"] = {"approval_request": binding}
        approval = self.approval_file(binding)
        (project / "docs/prd/operational-pilot.md").write_text("changed document")
        with self.assertRaisesRegex(native.Blocked, "current fixture"):
            self.h.check_approval("python", approval)

    def test_approval_binds_every_gate_dimension(self):
        self.fixture_case()
        binding = self.h.approval_context("python")
        self.h.state["gates"]["python"] = {"approval_request": binding}
        for key in ("run_id", "stack", "project", "slug", "scope", "phase", "native_session_id",
                    "task_revision", "document_sha256", "gate_reference", "upstream_prd_sha256"):
            with self.subTest(key=key):
                changed = {**binding, key: "different"}
                with self.assertRaisesRegex(native.Blocked, "current fixture"):
                    self.h.check_approval("python", self.approval_file(changed))
        supplied, _, _ = self.h.check_approval("python", self.approval_file(binding))
        self.assertEqual(supplied["scope"], "prd")

    def test_unsubmitted_gate_and_wrong_runtime_phase_refused(self):
        _, _, _, status = self.fixture_case()
        binding = self.h.approval_context("python")
        with self.assertRaisesRegex(native.Blocked, "not submitted"):
            self.h.check_approval("python", self.approval_file(binding))
        self.h.state["gates"]["python"] = {"approval_request": binding}
        status["effective_phase"] = "implementing"
        with self.assertRaisesRegex(native.Blocked, "review phase"):
            self.h.check_approval("python", self.approval_file(binding))

    def test_plan_requires_valid_upstream_approval(self):
        _, _, _, status = self.fixture_case("plan_review")
        binding = self.h.approval_context("python")
        self.assertIsNotNone(binding["upstream_prd_sha256"])
        status["approvals_valid"]["prd"] = False
        with self.assertRaisesRegex(native.Blocked, "current PRD"):
            self.h.approval_context("python")

    def test_post_approval_preserves_body_and_actual_caller_binding(self):
        project, task, _, status = self.fixture_case()
        binding = self.h.approval_context("python")
        self.h.state["gates"]["python"] = {"approval_request": binding}
        supplied, previous, body = self.h.check_approval("python", self.approval_file(binding))
        previous = copy.deepcopy(previous)
        path = project / task["documents"]["prd"]
        path.write_text("> 상태: 확정 · 2026-10 (스냅샷 — 코드 변경에 맞춰 최신화 안 함)\n\n" + body)
        task["approvals"].append({"scope": "prd", "path": task["documents"]["prd"],
            "quote": supplied["quote"], "session": supplied["session"], "digest": native.digest(path.read_bytes())})
        status["approvals_valid"]["prd"] = True
        self.h.approval_result("python", supplied, previous, body)
        self.assertNotIn(supplied["quote"], json.dumps(self.h.state))
        for key in ("quote", "session", "digest", "scope", "path"):
            with self.subTest(key=key):
                old = task["approvals"][-1][key]
                task["approvals"][-1][key] = "wrong"
                with self.assertRaises(native.Blocked):
                    self.h.approval_result("python", supplied, previous, body)
                task["approvals"][-1][key] = old
        path.write_text(path.read_text() + "changed body\n")
        task["approvals"][-1]["digest"] = native.digest(path.read_bytes())
        with self.assertRaisesRegex(native.Blocked, "final document"):
            self.h.approval_result("python", supplied, previous, body)

    def command_event(self, argv, result, item_id="command"):
        return {"type": "item.completed", "item": {"type": "command_execution", "id": item_id,
            "command": __import__("shlex").join(argv), "exit_code": 0,
            "aggregated_output": json.dumps({"ok": True, "result": result})}}

    def jsonl(self, session, events):
        return "\n".join(json.dumps(event) for event in [
            {"type": "thread.started", "thread_id": session}, *events, {"type": "turn.completed"}])

    def completion_case(self, candidate=False):
        project, task, profile, status = self.fixture_case("complete")
        status["approvals_valid"] = {"prd": True, "plan": True}
        self.h.state["candidate_installed"] = candidate
        runtime = str(self.h.plugin_path() / "runtime/tram.py")
        session = self.h.state["sessions"]["python"]
        reviewer = str(uuid.uuid4())
        snapshot = status["snapshot"]
        for scope in ("prd", "plan"):
            document = project / task["documents"][scope]
            approval = {"scope": scope, "digest": native.digest(document.read_bytes()),
                        "quote": "test caller approval " + scope, "session": "test caller"}
            task["approvals"].append(approval)
            self.h.state.setdefault("approval_evidence", {}).setdefault("python", []).append({
                "scope": scope, "after_document_sha256": approval["digest"],
                "quote_sha256": native.digest(approval["quote"].encode()),
                "caller_session_sha256": native.digest(approval["session"].encode())})
        record = {"id": "actual-runtime-run", "command_id": "test", "command_digest": "confirmed-command",
            "snapshot": snapshot, "round": 1, "exit_code": 0, "stale": False}
        if candidate:
            record.update(execution_status="succeeded", recorded=True, cleanup={"confirmed": True})
        task["verification"].append(record)
        review = {"reviewer": "reviewer", "reference": "codex:" + reviewer,
            "implementer_reference": "codex:" + session, "fresh": True,
            "snapshot": snapshot, "round": 1, "verdict": "pass"}
        task["reviews"].append(review)
        args = ["--project", str(project), "--slug", "operational-pilot"]
        reviewer_events = [self.command_event([sys.executable, runtime, "status", *args],
            {"snapshot": snapshot, "effective_phase": "verifying", "task": {"round": 1}}),
            self.command_event([sys.executable, runtime, "verify-run", *args, "--command", "test"], record),
            {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({
                "verdict": "pass", "snapshot": snapshot, "round": 1})}}]
        child_output = self.jsonl(reviewer, reviewer_events)
        child = {"type": "item.completed", "item": {"type": "command_execution", "exit_code": 0,
            "command": __import__("shlex").join(["codex", "exec", "--json", "-C", str(project), "review"]),
            "aggregated_output": child_output}}
        events = [self.command_event(["cat", str(self.h.plugin_path() / "skills/init/SKILL.md"),
                                      str(self.h.plugin_path() / "skills/start/SKILL.md")], {}),
            self.command_event([sys.executable, runtime, "init", "--project", str(project)], {}), child]
        output = self.jsonl(session, events)
        proof = self.h.collect_native("python", output, "real-host-invocation-in-test", expected=session)
        epoch = "candidate" if candidate else "baseline"
        self.h.state["native_evidence"] = {"python": {epoch: [proof]}}
        return project, task, profile, status, proof, output

    def generic_case(self, candidate=False, actual_record=None, actual_fixture=None):
        """Synthetic host producer + real filesystem, never native success evidence."""
        if actual_fixture:
            project, task, profile, status = actual_fixture
            old = {"runtime": [{"action": "init"}], "skills": ["init", "start"]}
            for approval in task["approvals"]:
                self.h.state.setdefault("approval_evidence", {}).setdefault("python", []).append({
                    "scope": approval["scope"], "after_document_sha256": approval["digest"],
                    "quote_sha256": native.digest(approval["quote"].encode()),
                    "caller_session_sha256": native.digest(approval["session"].encode())})
        else:
            project, task, profile, status, old, _ = self.completion_case(candidate)
        record = task["verification"][-1]
        if not actual_fixture:
            record.update(actual_record or {"id": str(uuid.uuid4()), "timestamp": native.datetime.now(native.timezone.utc).isoformat()})
        snapshot = record["snapshot"]
        session = self.h.state["sessions"]["python"]
        child_id = task["reviews"][-1]["reference"].removeprefix("codex:")
        root = self.h.home / "sessions"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        inventory = self.h.session_inventory()
        started_ns = time.time_ns() - 1000000000
        runtime = str(self.h.plugin_path() / "runtime/tram.py")
        args = ["--project", str(project), "--slug", "operational-pilot"]
        completed = [self.command_event([sys.executable, runtime, "status", *args],
                {"snapshot": snapshot, "effective_phase": "verifying", "task": {"round": task["round"]}}, "status-call"),
            self.command_event([sys.executable, runtime, "verify-run", *args, "--command", "test"], record, "verify-call")]
        child_events = []
        for event in completed:
            child_events.append({"type": "item.started", "item": {"type": "command_execution", "id": event["item"]["id"],
                "command": event["item"]["command"], "exit_code": None}})
            child_events.append(event)
        report = {"run_id": self.run.name, "snapshot": snapshot, "round": task["round"],
                  "verdict": "pass", "verification_run_ids": [record["id"]]}
        child_events.append({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(report)}})
        path = root / (child_id + ".jsonl")
        path.write_text(self.jsonl(child_id, child_events))
        path.chmod(0o600)
        parent_events = []
        for tool, item_id in (("spawn_agent", "spawn-native"), ("wait", "wait-native")):
            for event_type, status_name in (("item.started", "in_progress"), ("item.completed", "completed")):
                item = {"id": item_id, "type": "collab_tool_call", "tool": tool, "status": status_name,
                    "sender_thread_id": session, "receiver_thread_ids": [child_id], "agents_states": {}}
                if tool == "wait" and event_type == "item.completed":
                    item["agents_states"] = {child_id: {"status": "completed", "message": json.dumps(report)}}
                parent_events.append({"type": event_type, "item": item})
        output = self.jsonl(session, parent_events)
        invocation_id = str(uuid.uuid4())
        proof = self.h.collect_native("python", output, invocation_id, expected=session)
        proof["runtime"], proof["skills"] = old["runtime"], old["skills"]
        command = {"invocation_id": invocation_id, "process_id": 22222, "started_ns": started_ns,
                   "finished_ns": time.time_ns() + 100000000, "native": True, "exit": 0,
                   "root_reaped": True, "output_complete": True, "stdout_sha256": native.digest(output.encode())}
        self.h.state["commands"].append(command)
        proof["host_window"] = {**command, "sessions_before": inventory}
        proof["parent_output_sha256"] = command["stdout_sha256"]
        epoch = "candidate" if candidate else "baseline"
        self.h.state.setdefault("native_evidence", {}).setdefault("python", {})[epoch] = [proof]
        return project, task, profile, status, proof, path

    def test_complete_requires_native_matching_test_and_fresh_child_events(self):
        _, task, _, status, proof, path = self.generic_case()
        result = self.h.completion("python")
        self.assertEqual(result["review_session"], task["reviews"][-1]["reference"].removeprefix("codex:"))
        self.assertFalse(self.h.state["native_lifecycle_complete"])
        # Altering the host file after the invocation cannot retain provenance.
        path.write_text(path.read_text() + "\n")
        with self.assertRaises(native.Blocked):
            self.h.completion("python")

    def test_host_exit_zero_and_arbitrary_reviewer_reference_do_not_pass(self):
        _, task, _, _, proof, _ = self.completion_case()
        task["reviews"][-1]["reference"] = "invented-reference"
        with self.assertRaisesRegex(native.Blocked, "GENERIC_REVIEW_REFERENCE_INVALID"):
            self.h.completion("python")
        with self.assertRaisesRegex(native.Blocked, "actual session ID"):
            self.h.collect_native("python", "", "exit-zero-without-events")

    def test_stale_missing_failed_and_wrong_round_tests_refused(self):
        for field, value in (("stale", True), ("exit_code", 7), ("round", 2),
                             ("snapshot", {"old": True}), ("id", None)):
            with self.subTest(field=field):
                _, task, _, _, _, _ = self.generic_case()
                task["verification"][-1][field] = value
                with self.assertRaisesRegex(native.Blocked, "runtime test evidence"):
                    self.h.completion("python")

    def test_candidate_requires_successful_recorded_cleanup_and_new_review(self):
        for field, value in (("execution_status", "failed"), ("recorded", False), ("cleanup", {"confirmed": False})):
            with self.subTest(field=field):
                _, task, _, _, _, _ = self.generic_case(candidate=True)
                task["verification"][-1][field] = value
                with self.assertRaisesRegex(native.Blocked, "runtime test evidence"):
                    self.h.completion("python")
        _, task, _, _, proof, _ = self.generic_case(candidate=True)
        self.h.state["completed_reviews"] = {"python": {"baseline": proof["generic_spawns"][0]["child_session"]}}
        with self.assertRaisesRegex(native.Blocked, "fresh reviewer after update"):
            self.h.completion("python")

    def test_completion_requires_actual_caller_approval_evidence(self):
        self.completion_case()
        self.h.state["approval_evidence"]["python"].pop()
        with self.assertRaisesRegex(native.Blocked, "caller attestation"):
            self.h.completion("python")

    def test_wrong_resumed_session_and_echoed_reviewer_events_refused(self):
        _, _, _, _, _, output = self.completion_case()
        with self.assertRaisesRegex(native.Blocked, "differs from saved"):
            self.h.collect_native("python", output, "new-process", expected=str(uuid.uuid4()))
        events = [json.loads(line) for line in output.splitlines()]
        child = events[-2]
        child["item"]["command"] = "echo fabricated-events"
        proof = self.h.collect_native("python", "\n".join(json.dumps(e) for e in events), "new-process")
        self.assertEqual(proof["reviewers"], [])
        self.assertEqual(self.h.command_argv("echo cat /plugin/skills/init/SKILL.md && python fake"), [])

    def test_reviewer_report_requires_final_completed_message_of_completed_turn(self):
        session = str(uuid.uuid4())
        passing = {"verdict": "pass", "snapshot": {"current": True}, "round": 1}
        started_only = {"type": "item.started", "item": {"type": "agent_message", "text": json.dumps(passing)}}
        with self.assertRaisesRegex(native.Blocked, "final completed-turn report"):
            self.h.collect_native("python", self.jsonl(session, [started_only]), "review", reviewer=True)

        completed_pass = {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(passing)}}
        completed_invalid = {"type": "item.completed", "item": {"type": "agent_message", "text": "not a report"}}
        with self.assertRaisesRegex(native.Blocked, "final completed-turn report"):
            self.h.collect_native("python", self.jsonl(session, [completed_pass, completed_invalid]),
                                 "review", reviewer=True)

        # A later turn invalidates an earlier pass, even if the earlier turn completed.
        events = [{"type": "turn.started"}, completed_pass, {"type": "turn.completed"}, {"type": "turn.started"}]
        with self.assertRaisesRegex(native.Blocked, "completed turn"):
            self.h.collect_native("python", "\n".join(json.dumps(event) for event in [
                {"type": "thread.started", "thread_id": session}, *events]), "review", reviewer=True)

    def test_upgrade_requires_both_completed_work_and_final_resumes(self):
        self.h.state["stages"]["install"] = {"status": "passed"}
        with self.assertRaisesRegex(native.Blocked, "pilot-python"):
            self.h.upgrade()
        for stage in ("pilot-python", "pilot-node", "resume-python"):
            self.h.state["stages"][stage] = {"status": "passed"}
        with self.assertRaisesRegex(native.Blocked, "resume-node"):
            self.h.upgrade()
        with self.assertRaisesRegex(native.Blocked, "candidate-check-python"):
            for stage in ("upgrade", "resume-node"):
                self.h.state["stages"][stage] = {"status": "passed"}
            self.h.remove()

    def test_final_resume_is_separate_read_only_matching_restore(self):
        project, task, _, status, proof, _ = self.completion_case()
        self.h.state["stages"]["pilot-python"] = {"status": "passed"}
        runtime = str(self.h.plugin_path() / "runtime/tram.py")
        session = self.h.state["sessions"]["python"]
        output = self.jsonl(session, [self.command_event([sys.executable, runtime, "status", "--project", str(project),
            "--slug", "operational-pilot"], {"snapshot": status["snapshot"], "effective_phase": "complete", "task": {"round": 1}})])
        def command(*args, **kwargs):
            self.h.state["commands"].append({"invocation_id": "separate-real-host-process-in-test", "process_id": 12345})
            return 0, output, ""
        with patch.object(self.h, "command", side_effect=command), patch.object(self.h, "completion"):
            self.h.resume("python")
        self.assertEqual(self.h.state["resume_evidence"]["python"]["invocation_id"], "separate-real-host-process-in-test")
        def changed(*args, **kwargs):
            task["revision"] += 1
            return command(*args, **kwargs)
        with patch.object(self.h, "command", side_effect=changed), patch.object(self.h, "completion"):
            with self.assertRaisesRegex(native.Blocked, "restore matching"):
                self.h.resume("python")
        with self.assertRaisesRegex(native.Blocked, "only by continue"):
            self.h.execute("resume-python", approval="unrelated-approval.json")

    def test_actual_packaged_runtime_submission_and_marker_binding(self):
        # Real runtime integration; test caller quotes are not native/user evidence.
        project = self.run / "project-python"
        shutil.copytree(ROOT / "tests/fixtures/python", project)
        runtime = ROOT / "build/codex/runtime/tram.py"
        def call(*args):
            output = self.h.checked("test-runtime-integration", [sys.executable, str(runtime),
                *args, "--project", str(project)])
            return json.loads(output)["result"]
        call("init")
        # Install a test-only copy for status path integrity; this is not native installation evidence.
        shutil.copytree(ROOT / "build/codex", self.h.plugin_path())
        self.h.state["baseline_tree"] = native.tree(ROOT / "build/codex")
        call("start", "--slug", "operational-pilot")
        path = project / "docs/prd/operational-pilot.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Test-only submitted PRD\n\nStable reviewed body.\n")
        call("transition", "--slug", "operational-pilot", "--action", "submit-prd")
        self.h.state["sessions"]["python"] = str(uuid.uuid4())
        binding = self.h.approval_context("python")
        self.h.state["gates"]["python"] = {"approval_request": binding}
        supplied, previous, body = self.h.check_approval("python", self.approval_file(binding))
        call("approve", "--slug", "operational-pilot", "--scope", "prd", "--quote", supplied["quote"], "--session", supplied["session"])
        self.h.approval_result("python", supplied, previous, body)
        self.assertEqual(self.h.fixture_status("python")["phase"], "plan_draft")
        self.assertFalse(self.h.state["native_lifecycle_complete"])
        with self.assertRaisesRegex(native.Blocked, "not complete"):
            self.h.completion("python")

    def test_missing_user_approval_never_launches_continuation(self):
        self.fixture_case()
        self.h.state["stages"]["install"] = {"status": "passed"}
        with patch.object(self.h, "native_turn") as turn:
            with self.assertRaisesRegex(native.Blocked, "actual user approval is required"):
                self.h.pilot("python", continuing=True)
            turn.assert_not_called()

    def test_baseline_pilot_precedes_upgrade_and_stops_at_actual_review(self):
        self.fixture_case()
        self.h.state["sessions"].clear()
        self.h.state["stages"]["install"] = {"status": "passed"}
        def turn(*args, **kwargs):
            self.h.state["sessions"]["python"] = str(uuid.uuid4())
            return {}
        with patch.object(self.h, "native_turn", side_effect=turn) as host:
            with self.assertRaisesRegex(native.Blocked, "not complete"):
                self.h.pilot("python")
            host.assert_called_once()
        self.assertEqual(self.h.state["gates"]["python"]["approval_request"]["scope"], "prd")
        self.assertEqual(self.h.state["stages"]["upgrade"]["status"], "not-run")

    def test_selected_package_path_tracks_baseline_and_candidate(self):
        baseline, candidate = self.run / "baseline", self.run / "candidate"
        for path, version in ((baseline, "0.1.0"), (candidate, "0.2.0")):
            native.atomic(path / ".codex-plugin/plugin.json", {"version": version})
        self.h.baseline, self.h.candidate = baseline, candidate
        self.assertEqual(self.h.current_package(), baseline)
        self.assertEqual(self.h.plugin_path().name, "0.1.0")
        self.h.state["candidate_installed"] = True
        self.assertEqual(self.h.current_package(), candidate)
        self.assertEqual(self.h.plugin_path().name, "0.2.0")
        with self.assertRaisesRegex(native.Blocked, "before candidate update"):
            self.h.state["stages"]["install"] = {"status": "passed"}
            self.h.pilot("python")

    def test_observed_generic_spawn_metadata_is_not_child_test_provenance(self):
        _, task, _, _, original, output = self.completion_case()
        session = self.h.state["sessions"]["python"]
        child = str(uuid.uuid4())
        metadata = {"type": "collab_tool_call", "tool": "spawn_agent", "status": "completed",
            "id": "native-spawn-item", "sender_thread_id": session, "receiver_thread_ids": [child],
            "prompt": "private prompt never retained", "agents_states": {
                child: {"status": "completed", "message": "private reviewer response never retained"}}}
        events = [{"type": "item.completed", "item": metadata}]
        proof = self.h.collect_native("python", self.jsonl(session, events), "native-parent")
        self.assertEqual(proof["generic_spawns"][0]["child_session"], child)
        self.assertNotIn("private", json.dumps(proof))
        proof["runtime"] = original["runtime"]
        proof["skills"] = original["skills"]
        self.h.state["native_evidence"]["python"]["baseline"] = [proof]
        task["reviews"][-1]["reference"] = "codex:" + child
        with self.assertRaisesRegex(native.Blocked, "GENERIC_SPAWN_EDGE_UNVERIFIED"):
            self.h.completion("python")
        # A foreign sender and an incomplete spawn cannot establish the edge.
        metadata["sender_thread_id"] = str(uuid.uuid4())
        other = self.h.collect_native("python", self.jsonl(session, events), "parent")
        self.assertEqual(other["generic_spawns"], [])

    def test_rollout_metadata_is_diagnosed_without_accepting_a_spawn_edge(self):
        self.fixture_case()
        parent = self.h.state["sessions"]["python"]
        child = str(uuid.uuid4())
        # Sanitized observed record shape; no private prompts or account metadata.
        events = [
            {"type": "session_meta", "payload": {"id": child,
                "parent_thread_id": parent, "agent_path": "/root/reviewer"}},
            {"type": "response_item", "payload": {"type": "function_call",
                "name": "spawn_agent", "call_id": "spawn-call",
                "arguments": json.dumps({"task_name": "reviewer"})}},
            {"type": "response_item", "payload": {"type": "function_call_output",
                "call_id": "spawn-call", "output": json.dumps({"task_name": "/root/reviewer"})}},
            {"type": "event_msg", "payload": {"type": "task_complete"}},
        ]
        with self.assertRaisesRegex(native.Blocked, "HOST_SESSION_FORMAT_UNSUPPORTED.*spawn/wait"):
            self.h.collect_native("python", "\n".join(map(json.dumps, events)), "unsupported-rollout")
        self.assertFalse(self.h.state.get("native_lifecycle_complete"))
        self.assertNotIn("native_evidence", self.h.state)

    def test_missing_spawn_edge_explains_task_name_format_limit(self):
        self.completion_case()
        with self.assertRaisesRegex(native.Blocked, "GENERIC_SPAWN_EDGE_UNVERIFIED.*task-name-only"):
            self.h.completion("python")

    def test_generic_structured_wait_report_remains_attestation_only(self):
        self.fixture_case()
        session = self.h.state["sessions"]["python"]
        child, run_id = str(uuid.uuid4()), str(uuid.uuid4())
        report = {"run_id": self.run.name, "snapshot": {"files": {"app.py": "hash"}},
                  "round": 2, "verdict": "pass", "verification_run_ids": [run_id]}
        item = {"type": "collab_tool_call", "tool": "wait", "status": "completed", "id": "wait-child",
            "sender_thread_id": session, "receiver_thread_ids": [child],
            "agents_states": {child: {"status": "completed", "message": json.dumps(report)}}}
        proof = self.h.collect_native("python", self.jsonl(session, [{"type": "item.completed", "item": item}]), "parent-invocation")
        result = proof["generic_results"][0]
        self.assertFalse(result["child_commands_verified"])
        self.assertEqual(result["caller_attestation"]["verification_run_ids"], [run_id])
        self.assertEqual(result["caller_attestation"]["snapshot_sha256"], native.digest(json.dumps(report["snapshot"], sort_keys=True).encode()))
        self.assertEqual(proof["reviewers"], [])
        self.assertFalse(self.h.state["native_lifecycle_complete"])

    def test_malformed_approval_object_is_blocked(self):
        self.fixture_case()
        path = self.run / "malformed-approval.json"
        native.atomic(path, ["not", "a", "gate"])
        with self.assertRaisesRegex(native.Blocked, "gate object"):
            self.h.check_approval("python", path)

    def refresh_window(self, proof):
        finished = time.time_ns() + 100000000
        proof["host_window"]["finished_ns"] = finished
        for command in self.h.state["commands"]:
            if command.get("invocation_id") == proof["invocation_id"]:
                command["finished_ns"] = finished

    def rewrite_child(self, path, mutate, proof):
        lines = [json.loads(line) for line in path.read_text().splitlines()]
        mutate(lines)
        path.write_text("\n".join(json.dumps(line) for line in lines))
        self.refresh_window(proof)

    def test_cli_child_and_unlinked_parent_cannot_supply_generic_provenance(self):
        self.completion_case()
        with self.assertRaisesRegex(native.Blocked, "GENERIC_SPAWN_EDGE_UNVERIFIED"):
            self.h.completion("python")
        _, _, _, _, proof, _ = self.generic_case()
        proof["parent_output_sha256"] = "forged"
        with self.assertRaisesRegex(native.Blocked, "PARENT_HOST_INVOCATION_UNLINKED"):
            self.h.completion("python")

    def test_child_record_missing_unknown_header_and_foreign_thread_rejected(self):
        _, _, _, _, proof, path = self.generic_case()
        text = path.read_text()
        path.unlink()
        with self.assertRaisesRegex(native.Blocked, "CHILD_HOST_RECORD_MISSING"):
            self.h.completion("python")
        for header, error in (({"type": "session_meta", "payload": {}}, "CHILD_HOST_FORMAT_UNSUPPORTED.*rollout"),
                              ({"type": "thread.started", "thread_id": str(uuid.uuid4())},
                               "CHILD_HEADER_ID_OR_FORMAT_MISMATCH")):
            path.write_text(text)
            self.rewrite_child(path, lambda lines: lines.__setitem__(0, header), proof)
            with self.assertRaisesRegex(native.Blocked, error):
                self.h.completion("python")
        path.write_text("not-json\n")
        self.refresh_window(proof)
        with self.assertRaisesRegex(native.Blocked, "CHILD_HOST_FORMAT_UNSUPPORTED"):
            self.h.completion("python")

    def test_symlink_outside_namespace_and_writable_record_rejected(self):
        _, _, _, _, proof, path = self.generic_case()
        outside = self.run / "outside-child.jsonl"
        path.rename(outside)
        path.symlink_to(outside)
        with self.assertRaisesRegex(native.Blocked, "CHILD_RECORD_PATH_UNSAFE"):
            self.h.completion("python")
        with self.assertRaisesRegex(native.Blocked, "CHILD_RECORD_PATH_OUTSIDE_HOME"):
            self.h.host_path(outside)
        with self.assertRaisesRegex(native.Blocked, "CHILD_RECORD_PATH_OUTSIDE_HOME"):
            self.h.host_path(self.h.home / "sessions/../outside.jsonl")
        path.unlink()
        outside.rename(path)
        path.chmod(0o666)
        self.refresh_window(proof)
        with self.assertRaisesRegex(native.Blocked, "CHILD_RECORD_PATH_UNSAFE"):
            self.h.completion("python")

    def test_old_preexisting_or_hardlinked_child_cannot_be_fresh_spawn(self):
        _, _, _, _, proof, path = self.generic_case()
        info = self.h.session_inventory()[path.name]
        proof["host_window"]["sessions_before"][path.name] = info
        with self.assertRaisesRegex(native.Blocked, "CHILD_RECORD_NOT_FRESH_REGULAR_FILE"):
            self.h.completion("python")
        proof["host_window"]["sessions_before"] = {}
        os.utime(path, ns=(1, 1))
        self.refresh_window(proof)
        with self.assertRaisesRegex(native.Blocked, "CHILD_RECORD_OUTSIDE_INVOCATION_WINDOW"):
            self.h.completion("python")
        os.link(path, self.run / "hardlink")
        with self.assertRaisesRegex(native.Blocked, "CHILD_RECORD_NOT_FRESH_REGULAR_FILE"):
            self.h.completion("python")

    def test_command_result_call_id_pairing_and_exit_are_required(self):
        for mutate, error in (
            (lambda lines: lines.pop(4), "CHILD_COMMAND_RESULT_MISSING"),
            (lambda lines: lines[4]["item"].update(id="unlinked"), "CHILD_COMMAND_RESULT_UNLINKED"),
            (lambda lines: lines[4]["item"].update(exit_code=7), "actual native command"),
            (lambda lines: lines.pop(), "CHILD_TURN_INCOMPLETE")):
            with self.subTest(error=error):
                _, _, _, _, proof, path = self.generic_case()
                self.rewrite_child(path, mutate, proof)
                with self.assertRaisesRegex(native.Blocked, error):
                    self.h.completion("python")

    def test_wait_edge_attestation_and_runtime_timestamp_are_bound(self):
        _, task, _, _, proof, _ = self.generic_case()
        wait = next(value for value in proof["generic_results"] if value["tool"] == "wait")
        original = copy.deepcopy(wait)
        wait["caller_attestation"]["verification_run_ids"] = [str(uuid.uuid4())]
        with self.assertRaisesRegex(native.Blocked, "GENERIC_WAIT_REPORT_MISMATCH"):
            self.h.completion("python")
        wait.clear()
        wait.update(original)
        task["verification"][-1]["timestamp"] = "2000-01-01T00:00:00+00:00"
        with self.assertRaisesRegex(native.Blocked, "CHILD_RUNTIME_RUN_OUTSIDE_HOST_WINDOW"):
            self.h.completion("python")
        wait["started_index"] = 0
        with self.assertRaisesRegex(native.Blocked, "GENERIC_WAIT_COMPLETION_MISSING"):
            self.h.completion("python")

    def test_parser_contract_with_actual_runtime_verification_is_not_native_success(self):
        project = self.run / "project-python"
        shutil.copytree(ROOT / "tests/fixtures/python", project)
        runtime = ROOT / "build/codex/runtime/tram.py"
        def call(*args):
            output = self.h.checked("test-real-runtime", [sys.executable, str(runtime), *args, "--project", str(project)])
            return json.loads(output)["result"]
        call("init")
        config = self.run / "runtime-config.json"
        native.atomic(config, {"reviewer": {"configured": True}, "commands": [{"id": "test", "argv":
            [sys.executable, "-m", "unittest", "discover"], "cwd": ".", "confirmed": True, "required": True}]})
        call("configure", "--file", str(config))
        call("start", "--slug", "operational-pilot")
        for scope in ("prd", "plan"):
            document = project / "docs" / scope / "operational-pilot.md"
            document.parent.mkdir(parents=True, exist_ok=True)
            document.write_text("# Parser test-only " + scope + "\n")
            call("transition", "--slug", "operational-pilot", "--action", "submit-" + scope)
            call("approve", "--slug", "operational-pilot", "--scope", scope, "--quote", "Synthetic test caller", "--session", "test-only")
        call("transition", "--slug", "operational-pilot", "--action", "verify")
        call("verify-run", "--slug", "operational-pilot", "--command", "test")
        state = call("status", "--slug", "operational-pilot")
        parent, child = str(uuid.uuid4()), str(uuid.uuid4())
        self.h.state["sessions"]["python"] = parent
        review = {"reviewer": child, "reference": "codex:" + child, "adapter": "codex",
            "implementer_reference": "codex:" + parent, "fresh": True, "snapshot": state["snapshot"],
            "round": state["task"]["round"], "axes": [{"name": name, "level": 2, "evidence": "parser fixture only"}
                for name in ("correctness", "tests", "reuse", "simplicity", "conventions")],
            "blocking": [], "unmet": [], "score": 100, "verdict": "pass"}
        review_file = self.run / "test-review.json"
        native.atomic(review_file, review)
        call("review", "--slug", "operational-pilot", "--file", str(review_file))
        call("transition", "--slug", "operational-pilot", "--action", "complete")
        shutil.copytree(ROOT / "build/codex", self.h.plugin_path())
        self.h.state["baseline_tree"] = native.tree(ROOT / "build/codex")
        fixture = self.h.fixture("python")
        self.generic_case(actual_fixture=fixture)
        accepted = self.h.completion("python")
        self.assertEqual(accepted["review_session"], child)
        self.assertEqual(call("status", "--slug", "operational-pilot")["effective_phase"], "complete")
        self.assertFalse(self.h.state["native_lifecycle_complete"])
        with self.assertRaises(native.Blocked):
            self.h.remove()

    def test_preservation_checks_dirty_user_file(self):
        for stack in ("python", "node"):
            project = self.run / ("project-" + stack)
            project.mkdir(parents=True)
            (project / "unrelated-dirty.txt").write_text("original")
            self.h.state["snapshots"][stack] = native.tree(project)
        (self.run / "project-python/unrelated-dirty.txt").write_text("lost")
        with self.assertRaisesRegex(native.Blocked, "preservation failure"):
            self.h.preserve("test")

    def test_tree_detects_executable_and_symlink(self):
        self.run.mkdir(parents=True)
        file = self.run / "a"
        file.write_text("content")
        before = native.tree(self.run)
        file.chmod(0o755)
        (self.run / "link").symlink_to("a")
        after = native.tree(self.run)
        self.assertNotEqual(before["a"], after["a"])
        self.assertEqual(after["link"], {"symlink": "a"})

    def test_completed_stage_is_not_silently_reexecuted(self):
        self.h.state["stages"]["install"] = {"status": "passed"}
        with self.assertRaisesRegex(native.Blocked, "already passed"):
            self.h.execute("install")


if __name__ == "__main__":
    unittest.main()
