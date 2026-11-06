"""Observations are advisory; approval and evidence gates remain runtime-owned."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/runtime"))
import tram
import harness_observation as harness


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    tram.init(root)
    (root / "code.py").write_text("value = 1\n")
    commands = [{"id": "unit", "argv": [sys.executable, "-c", "print('ok')"], "cwd": ".",
                 "required": True, "confirmed": True},
                {"id": "ui", "argv": [sys.executable, "-c", "print('ui')"], "cwd": ".",
                 "required": False, "confirmed": True},
                {"id": "unknown", "argv": ["unknown-tool"], "cwd": ".",
                 "required": False, "confirmed": False}]
    write(root, "profile.json", {"commands": commands, "inputs": ["code.py"]})
    tram.configure(root, root / "profile.json")
    tram.start(root, "sample", "quick")
    return root


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))
    return path


def configure(root, **delta):
    config, digest = harness.configuration(root, tram.profile(root))
    write(root, "observation-config.json", delta)
    return harness.configure(root, "observation-config.json", config["revision"], digest)


def record(root, value, digest=None):
    write(root, "input.json", value)
    before = digest or harness.file_digest(harness.storage_path(root, "sample"))
    return harness.record(root, "sample", "input.json", before)


def tree(root):
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in root.rglob("*")}


def assert_error(code, call, *args, **kwargs):
    with pytest.raises(tram.TramError) as caught:
        call(*args, **kwargs)
    assert caught.value.code == code


def test_missing_configuration_readonly_and_required_preserved(project):
    before = tree(project)
    result = harness.recommend(project, "sample", "문구 수정", ["code.py"], ["unit"])
    assert not result["configured"]
    choices = {c["command_id"]: c for c in result["checks"]}
    assert choices["unit"]["selected"]
    assert not choices["ui"]["selected"]
    assert not choices["unknown"]["executable"]
    assert result["warnings"][0]["code"] == "REQUIRED_CHECK_OMISSION_PROPOSED"
    shown = harness.show(project, "sample")
    assert shown["runtime"]["completion_issues"] == tram.status(project, "sample")["completion_issues"]
    assert tree(project) == before


def test_configure_revision_digest_and_profile_unchanged(project):
    profile = (project / ".tram/project.json").read_bytes()
    result = configure(project, checks={"ui": {"paths": ["screen/**"], "keywords": ["화면"]}})
    assert result["config"]["revision"] == 1
    assert (project / ".tram/project.json").read_bytes() == profile
    choices = harness.recommend(project, "sample", "화면 수정", ["screen/home.py"])["checks"]
    assert {c["command_id"] for c in choices if c["selected"]} == {"unit", "ui"}
    assert_error("DIGEST_CONFLICT", harness.configure, project, "observation-config.json", 0, "missing")


@pytest.mark.parametrize("delta", [
    {"mode": "enforce"}, {"commands": []}, {"checks": {"missing": {}}},
    {"checks": {"unit": {"required": False}}},
    {"checks": {"unit": {"minimum_cases": True}}},
    {"checks": {"unit": {"paths": ["../other"]}}},
    {"knowledge": {"roots": [".env"], "documents": []}},
    {"knowledge": {"roots": [], "documents": [{"path": "docs/a.md"}, {"path": "docs/a.md"}]}},
])
def test_invalid_configuration_never_written(project, delta):
    with pytest.raises(tram.TramError):
        configure(project, **delta)
    assert not (project / ".tram/harness.json").exists()


def test_duplicate_json_and_symlink_refused(project, tmp_path):
    (project / "duplicate.json").write_text('{"checks":{},"checks":{}}')
    assert_error("INVALID_JSON", harness.configure, project, "duplicate.json", 0, "missing")
    (project / "linked.json").symlink_to(project / "duplicate.json")
    assert_error("SYMLINK", harness.configure, project, "linked.json", 0, "missing")
    assert_error("INVALID_PATH", harness.configure, project, "../outside", 0, "missing")


def test_ignore_required_for_explicit_writes(project):
    (project / ".gitignore").write_text("")
    assert_error("LOCAL_NOT_IGNORED", configure, project, mode="observe")
    assert not (project / ".tram/harness.json").exists()


def test_recommendation_record_resume_request_and_code_stale(project):
    report = harness.recommend(project, "sample", "처음 요청", ["code.py"])
    original = (project / ".tram/tasks/sample.json").read_bytes()
    saved = record(project, {"schema_version": 1, "kind": "recommendation", "report": report})
    assert saved["observation"]["source"] == "caller_reported"
    assert (project / ".tram/tasks/sample.json").read_bytes() == original
    before = tree(project)
    assert harness.show(project, "sample")["records"][0]["validity"] == "unknown"
    assert harness.show(project, "sample", "처음 요청", ["code.py"])["records"][0]["validity"] == "current"
    assert harness.show(project, "sample", "범위 확대", ["code.py"])["records"][0]["validity"] == "stale"
    assert tree(project) == before
    (project / "code.py").write_text("value = 2\n")
    assert harness.show(project, "sample", "처음 요청", ["code.py"])["records"][0]["state"] == "stale"


def test_record_compare_and_swap_and_required_omission(project):
    report = harness.recommend(project, "sample", "수정", ["code.py"])
    value = {"schema_version": 1, "kind": "recommendation", "report": report}
    record(project, value)
    assert_error("DIGEST_CONFLICT", record, project, value, "missing")
    report["checks"][0]["selected"] = False
    assert_error("INVALID_ARGUMENT", record, project, value)


def result(run_id=None, outcome="not_run", **changes):
    return {"schema_version": 1, "kind": "result", "command_id": "unit", "run_id": run_id,
            "outcome": outcome, "declared_scope": ["sample"], "limitations": [],
            **({"reason": "환경 미준비"} if outcome == "not_run" else {}), **changes}


def test_not_run_missing_and_forged_run_are_not_pass(project):
    configure(project, checks={"unit": {"expects_result": True}})
    assert harness.show(project, "sample")["undeclared_results"][0]["warnings"] == ["VERIFICATION_RESULT_MISSING"]
    assert record(project, result())["observation"]["state"] == "not_run"
    observed = record(project, result("invented", "passed"))["observation"]
    assert observed["state"] == "unknown"
    assert observed["warnings"] == ["VERIFICATION_RESULT_INVALID"]


def test_show_preserves_declared_scope_limitations_and_unexecuted_reason(project):
    record(project, result(limitations=["테스트 환경 없음"], reason="기기 미연결"))
    observation = harness.show(project, "sample")["records"][0]
    assert observation["command_id"] == "unit"
    assert observation["run_id"] is None
    assert observation["source"] == "caller_reported"
    assert observation["declared_scope"] == ["sample"]
    assert observation["limitations"] == ["테스트 환경 없음"]
    assert observation["reason"] == "기기 미연결"
    assert observation["state"] == "not_run"


@pytest.mark.parametrize("relative", ["app/build/reports/androidTests/index.html",
                                      "dist/report.html", ".tram/local/ui/screenshot.png"])
def test_generated_artifacts_are_allowed_without_becoming_search_sources(project, relative):
    path = write(project, relative, {"render": "generated"})
    observation = record(project, result(artifacts=[relative]))["observation"]
    assert observation["artifact_digests"][relative] == harness.file_digest(path)
    assert harness.show(project, "sample")["records"][0]["state"] == "not_run"
    path.write_text("changed")
    assert harness.show(project, "sample")["records"][0]["state"] == "stale"
    assert_error("INVALID_PATH", configure, project,
                 knowledge={"roots": [str(path.parent.relative_to(project))], "documents": []})


@pytest.mark.parametrize("relative", [".tram/project.json", ".git/config", ".env", "node_modules/report.json"])
def test_artifact_guards_remain_strict(project, relative):
    assert_error("INVALID_PATH", record, project, result(artifacts=[relative]))


@pytest.mark.parametrize("identity", [[], {}, None])
def test_corrupt_stored_command_id_returns_structured_cli_error(project, identity):
    record(project, result())
    target = harness.storage_path(project, "sample")
    saved = json.loads(target.read_text())
    saved["records"][0]["input"]["command_id"] = identity
    target.write_text(json.dumps(saved))
    process = subprocess.run([sys.executable, str(ROOT / "src/scripts/harness.py"), "show",
                              "--project", str(project), "--slug", "sample"], capture_output=True, text=True)
    assert process.returncode == 2
    assert json.loads(process.stdout)["errorCode"] == "INVALID_JSON"
    assert "Traceback" not in process.stderr


def test_real_execution_report_and_runtime_gates_unchanged(project):
    configure(project, checks={"unit": {"minimum_cases": 1, "expects_result": True}})
    tram.transition(project, "sample", "verify")
    run = tram.verify_run(project, "sample", "unit")
    assert run["execution_status"] == "succeeded"
    before = tram.status(project, "sample")
    for count in (None, True, 0, "1"):
        value = result(run["run_id"], "passed", **({"cases_count": count} if count is not None else {}))
        assert record(project, value)["observation"]["state"] == "unknown"
    write(project, "reports/ui.txt", {"render": "generated"})
    value = result(run["run_id"], "needs_human_review", cases_count=1, artifacts=["reports/ui.txt"])
    observation = record(project, value)["observation"]
    assert observation["state"] == "needs_human_review"
    assert "HUMAN_REVIEW_PENDING" in observation["warnings"]
    assert record(project, result(run["run_id"], "passed", cases_count=1))["observation"]["state"] == "reported_pass"
    after = tram.status(project, "sample")
    assert before["completion_issues"] == after["completion_issues"]
    assert before["task"] == after["task"]
    (project / "reports/ui.txt").write_text("changed")
    assert harness.show(project, "sample")["records"][-2]["state"] == "stale"
    (project / "reports/ui.txt").unlink()
    (project / "reports/ui.txt").symlink_to(project / "code.py")
    assert harness.show(project, "sample")["records"][-2]["state"] == "stale"
    (project / "code.py").write_text("value = 9")
    assert harness.show(project, "sample")["records"][-1]["state"] == "stale"


def test_failed_execution_cannot_be_reported_pass(project):
    config = tram.profile(project)
    config["commands"][0]["argv"] = [sys.executable, "-c", "raise SystemExit(7)"]
    write(project, "failure-config.json", {"commands": config["commands"]})
    tram.configure(project, project / "failure-config.json")
    tram.transition(project, "sample", "verify")
    run = tram.verify_run(project, "sample", "unit")
    assert record(project, result(run["run_id"], "passed"))["observation"]["state"] == "failed"
    assert "COMMAND_EVIDENCE_MISSING:unit" in tram.status(project, "sample")["completion_issues"]


def test_search_korean_metadata_mapping_and_bounded_readonly(project):
    write(project, "docs/knowledge/upload.md", "스크린샷 업로드 금지 정책")
    # Use actual Markdown text, not a copied policy index.
    (project / "docs/knowledge/upload.md").write_text("# 스크린샷\n업로드는 어뷰징 방지를 위해 제한한다")
    (project / "docs/knowledge/new.md").write_text("# 새 정책\n업로드 정책은 확인 필요")
    configure(project, knowledge={"roots": [], "documents": [
        {"path": "docs/knowledge/upload.md", "kind": "decision", "tags": ["스크린샷"],
         "source": "회의 기록", "confirmed_at": "2026-11-06"},
        {"path": "docs/knowledge/new.md", "supersedes": ["docs/knowledge/upload.md"]}]})
    before = tree(project)
    found = harness.search(project, "스크린샷 업로드", ["code.py"])
    assert found["results"][0]["path"] == "docs/knowledge/upload.md"
    assert "superseded_by:docs/knowledge/new.md" in found["results"][0]["warnings"]
    assert found["results"][0]["validity"] == "unconfirmed"
    assert tree(project) == before
    assert not harness.search(project, "전혀없는단어")["results"]


def test_search_truncation_symlink_sensitive_and_large_files(project, monkeypatch):
    folder = project / "docs/knowledge"
    folder.mkdir(parents=True)
    (folder / "token.md").write_text("정책")
    (folder / "a.md").write_text("정책" * 100)
    (folder / "b.md").write_text("정책")
    (folder / "c.md").symlink_to(folder / "b.md")
    monkeypatch.setattr(harness, "MAX_DOCUMENT_BYTES", 30)
    result = harness.search(project, "정책")
    assert [item["path"] for item in result["results"]] == ["docs/knowledge/b.md"]
    assert {"docs/knowledge/token.md", "docs/knowledge/a.md", "docs/knowledge/c.md"}.issubset(result["skipped"])
    monkeypatch.setattr(harness, "MAX_DOCUMENTS", 1)
    assert harness.search(project, "정책")["truncated"]


def test_evaluate_fixed_and_holdout_have_no_execution_or_writes(project):
    for name in ("baseline.json", "holdout.json"):
        fixture = json.loads((ROOT / "tests/fixtures/harness" / name).read_text())
        write(project, "evaluation.json", fixture)
        before = tree(project)
        result = harness.evaluate(project, "evaluation.json")
        assert result["counts"]["missed"] == 0
        assert result["counts"]["unnecessary"] == 0
        assert result["performance"]["completion_time"] is None
        assert tree(project) == before
    write(project, "empty.json", {"schema_version": 1, "cases": []})
    assert harness.evaluate(project, "empty.json")["recommendation_recall"] is None


def test_cli_contract_and_invalid_arguments():
    command = [sys.executable, str(ROOT / "src/scripts/harness.py")]
    contract = subprocess.run([*command, "contract"], capture_output=True, text=True)
    assert contract.returncode == 0
    assert not json.loads(contract.stdout)["result"]["completion_gates_changed"]
    invalid = subprocess.run([*command, "show"], capture_output=True, text=True)
    assert invalid.returncode == 2
    assert json.loads(invalid.stdout)["errorCode"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("change", [
    {"checks": {"unit": {"evidence_kind": []}}},
    {"knowledge": {"roots": [], "documents": [{"path": "docs/a.md", "kind": []}]}},
    {"knowledge": {"roots": [], "documents": [{"path": "docs/a.md", "confirmed_at": "2026-99-99"}]}},
])
def test_nested_malformed_configuration_has_structured_error(project, change):
    assert_error("INVALID_ARGUMENT", configure, project, **change)


def test_policy_change_invalidates_recommendation_outside_snapshot_inputs(project):
    (project / "docs/knowledge").mkdir(parents=True)
    (project / "docs/knowledge/policy.md").write_text("스크린샷 업로드 제한")
    report = harness.recommend(project, "sample", "스크린샷 업로드", ["code.py"])
    assert "docs/knowledge/policy.md" in report["policy_digests"]
    record(project, {"schema_version": 1, "kind": "recommendation", "report": report})
    (project / "docs/knowledge/policy.md").write_text("스크린샷 업로드 정책 변경")
    shown = harness.show(project, "sample", "스크린샷 업로드", ["code.py"])
    assert shown["records"][0]["changed_policies"] == ["docs/knowledge/policy.md"]
    assert shown["records"][0]["state"] == "stale"


@pytest.mark.parametrize("bad", [None, [], "broken"])
def test_corrupt_storage_nested_data_is_json_error(project, bad):
    target = harness.storage_path(project, "sample")
    write(project, str(target.relative_to(project)), {"schema_version": 1, "revision": 1, "records": [
        {"snapshot": {}, "config_digest": "missing", "input": {}, "observation": bad}]})
    assert_error("INVALID_JSON", harness.show, project, "sample")


@pytest.mark.parametrize("bad", [
    {"schema_version": True, "cases": []},
    {"schema_version": 1, "cases": [{"kind": "recommendation", "commands": [], "checks": [], "expected": []}]},
    {"schema_version": 1, "cases": [{"kind": "recommendation", "commands": [], "request": [], "expected": []}]},
])
def test_evaluation_malformed_values_do_not_execute_or_crash(project, bad):
    write(project, "bad-eval.json", bad)
    assert_error("INVALID_ARGUMENT", harness.evaluate, project, "bad-eval.json")


def test_removed_profile_command_and_symlink_artifact_show_stale(project):
    configure(project, checks={"ui": {"expects_result": True}})
    record(project, result(command_id="ui"))
    commands = [c for c in tram.profile(project)["commands"] if c["id"] != "ui"]
    write(project, "profile-remove.json", {"commands": commands})
    tram.configure(project, project / "profile-remove.json")
    shown = harness.show(project, "sample")
    assert shown["records"][0]["state"] == "stale"
    assert "VERIFICATION_RESULT_INVALID" in shown["records"][0]["warnings"]


def test_forged_recommendation_nested_command_type_refused(project):
    report = harness.recommend(project, "sample", "수정", ["code.py"])
    report["checks"][0]["command_id"] = []
    assert_error("INVALID_ARGUMENT", record, project, {"schema_version": 1, "kind": "recommendation", "report": report})


def test_policy_and_result_evaluation_fixtures(project):
    (project / "docs/knowledge").mkdir(parents=True)
    (project / "docs/knowledge/fixture-policy.md").write_text("스크린샷 업로드를 제한하는 정책")
    for name in ("policy.json", "results.json"):
        write(project, "evaluation.json", json.loads((ROOT / "tests/fixtures/harness" / name).read_text()))
        before = tree(project)
        result = harness.evaluate(project, "evaluation.json")
        assert result["counts"]["policy_missed"] == 0
        assert result["counts"]["state_mismatch"] == 0
        if name == "results.json":
            assert result["counts"]["not_run"] == 1
            assert result["counts"]["unknown"] == 0
            assert result["counts"]["stale"] == 0
        assert tree(project) == before
