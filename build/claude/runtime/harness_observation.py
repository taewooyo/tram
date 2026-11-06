"""Optional, project-local observations. Never changes Tram's completion gates."""
from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace

import tram

SCHEMA = 1
MAX_JSON = 2_000_000
MAX_DOCUMENTS = 200
MAX_DOCUMENT_BYTES = 128_000
MAX_RESULTS = 30
CONFIG = ".tram/harness.json"
KINDS = {"test", "ui", "behavior", "other"}
SENSITIVE = (".env*", "*.pem", "*.key", "*credential*", "*secret*", "*token*")


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            tram.fail("INVALID_JSON", "중복 JSON 키입니다", key=key)
        value[key] = item
    return value


def read_json(path):
    if path.stat().st_size > MAX_JSON:
        tram.fail("INVALID_ARGUMENT", "JSON 크기 제한을 초과했습니다")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)


def file_digest(path):
    if not path.is_file():
        return "missing"
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strings(value, name):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v or len(v) > 4096 for v in value):
        tram.fail("INVALID_ARGUMENT", name + " 문자열 배열이 필요합니다")
    return value


def safe_path(root, value):
    path = tram.inside(root, value)
    if Path(value).as_posix() != value or value.startswith("./"):
        tram.fail("INVALID_PATH", "정규화된 상대 경로가 필요합니다")
    return path


def _safe_document(root, value):
    path = safe_path(root, value)
    parts = Path(value).parts
    if any(p in tram.CACHE_DIRS | {".git", ".tram", "build", "dist"} or
           any(fnmatch.fnmatchcase(p.lower(), pattern) for pattern in SENSITIVE) for p in parts):
        tram.fail("INVALID_PATH", "검색·artifact 경로로 허용되지 않습니다", path=value)
    return path


def _safe_artifact(root, value):
    """Allow generated evidence while preserving path and sensitive-file guards."""
    path = safe_path(root, value)
    parts = Path(value).parts
    if any(p in tram.CACHE_DIRS | {".git"} or
           any(fnmatch.fnmatchcase(p.lower(), pattern) for pattern in SENSITIVE) for p in parts):
        tram.fail("INVALID_PATH", "민감 파일·의존성 경로는 artifact로 허용되지 않습니다", path=value)
    if ".tram" in parts and parts[:2] != (".tram", "local"):
        tram.fail("INVALID_PATH", "Tram 제어 기록은 artifact로 사용하지 않습니다", path=value)
    return path


def default_config():
    return {"schema_version": SCHEMA, "revision": 0, "mode": "observe", "checks": {},
            "knowledge": {"roots": [], "documents": []}}


def validate_config(root, value, profile, allow_orphans=False):
    if not isinstance(value, dict) or set(value) != set(default_config()):
        tram.fail("INVALID_ARGUMENT", "관찰 설정 필드가 잘못되었습니다")
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA:
        tram.fail("SCHEMA_INCOMPATIBLE", "관찰 schema 1이 필요합니다")
    if type(value["revision"]) is not int or value["revision"] < 0 or value["mode"] != "observe":
        tram.fail("INVALID_ARGUMENT", "관찰 모드와 revision을 확인하세요")
    commands = {c["id"] for c in profile["commands"]}
    if not isinstance(value["checks"], dict):
        tram.fail("INVALID_ARGUMENT", "checks는 command ID별 객체입니다")
    for identity, rule in value["checks"].items():
        if (identity not in commands and not allow_orphans) or not isinstance(rule, dict) or set(rule) - {
                "description", "paths", "keywords", "evidence_kind", "expects_result", "minimum_cases"}:
            tram.fail("INVALID_ARGUMENT", "기존 command ID와 허용된 검사 규칙이 필요합니다")
        if "description" in rule and (not isinstance(rule["description"], str) or len(rule["description"]) > 4096):
            tram.fail("INVALID_ARGUMENT", "description 문자열이 필요합니다")
        for pattern in strings(rule.get("paths", []), "paths"):
            safe_path(root, pattern)
        strings(rule.get("keywords", []), "keywords")
        if not isinstance(rule.get("evidence_kind", "other"), str) or rule.get("evidence_kind", "other") not in KINDS or type(rule.get("expects_result", False)) is not bool:
            tram.fail("INVALID_ARGUMENT", "evidence_kind/expects_result를 확인하세요")
        if "minimum_cases" in rule and (type(rule["minimum_cases"]) is not int or rule["minimum_cases"] < 0):
            tram.fail("INVALID_ARGUMENT", "minimum_cases는 음이 아닌 정수입니다")
    knowledge = value["knowledge"]
    if not isinstance(knowledge, dict) or set(knowledge) != {"roots", "documents"}:
        tram.fail("INVALID_ARGUMENT", "knowledge roots/documents가 필요합니다")
    for relative in strings(knowledge["roots"], "roots"):
        _safe_document(root, relative)
    if not isinstance(knowledge["documents"], list):
        tram.fail("INVALID_ARGUMENT", "documents 배열이 필요합니다")
    seen = set()
    for item in knowledge["documents"]:
        if not isinstance(item, dict) or set(item) - {"path", "kind", "tags", "scope", "source", "confirmed_at", "supersedes"}:
            tram.fail("INVALID_ARGUMENT", "지식 metadata 필드가 잘못되었습니다")
        relative = item.get("path")
        _safe_document(root, relative)
        if relative in seen:
            tram.fail("INVALID_ARGUMENT", "중복 지식 경로입니다")
        seen.add(relative)
        if not isinstance(item.get("kind", "fact"), str) or item.get("kind", "fact") not in {"fact", "decision"}:
            tram.fail("INVALID_ARGUMENT", "kind는 fact 또는 decision입니다")
        for name in ("tags", "scope"):
            strings(item.get(name, []), name)
        for name in ("source", "confirmed_at"):
            if name in item and (not isinstance(item[name], str) or not item[name] or len(item[name]) > 4096):
                tram.fail("INVALID_ARGUMENT", name + " 문자열이 필요합니다")
        if "confirmed_at" in item:
            from datetime import date
            try:
                parsed = date.fromisoformat(item["confirmed_at"])
                if parsed.isoformat() != item["confirmed_at"]:
                    raise ValueError("noncanonical date")
            except ValueError:
                tram.fail("INVALID_ARGUMENT", "confirmed_at은 유효한 YYYY-MM-DD입니다")
        for target in strings(item.get("supersedes", []), "supersedes"):
            _safe_document(root, target)


def configuration(root, profile):
    path = safe_path(root, CONFIG)
    if not path.exists():
        return default_config(), "missing"
    value = read_json(path)
    validate_config(root, value, profile, allow_orphans=True)
    return value, file_digest(path)


def configure(project, file, expected_revision, expected_digest):
    root = tram.root_for(project)
    delta = read_json(safe_path(root, file))
    if not isinstance(delta, dict) or set(delta) - {"mode", "checks", "knowledge"}:
        tram.fail("INVALID_ARGUMENT", "mode/checks/knowledge delta만 허용합니다")
    # Validate before creating any managed directories or locks.
    profile = tram.profile(root)
    old, before = configuration(root, profile)
    new = {**old, **delta, "revision": old["revision"] + 1}
    validate_config(root, new, profile)
    if expected_revision != old["revision"] or expected_digest != before:
        tram.fail("DIGEST_CONFLICT", "관찰 설정이 변경됐습니다")
    tram.local_path(root, "harness/configure-check")
    with tram.locked(root):
        current, current_digest = configuration(root, tram.profile(root))
        if current["revision"] != expected_revision or current_digest != expected_digest:
            tram.fail("DIGEST_CONFLICT", "관찰 설정이 변경됐습니다")
        tram.atomic(safe_path(root, CONFIG), tram.canonical(new) + b"\n")
    return {"config": new, "config_digest": file_digest(safe_path(root, CONFIG)), "writes": True}


def context(project, slug):
    root = tram.root_for(project)
    profile = tram.profile(root)
    state = tram.task(root, slug)
    config, digest = configuration(root, profile)
    return root, profile, state, config, digest, tram.fingerprint(root, profile, state)


def recommend_checks(commands, checks, request, paths, omit=()):
    choices, warnings = [], []
    for cmd in commands:
        rule = checks.get(cmd["id"], {})
        reasons = []
        if cmd["required"]:
            reasons.append("project_required")
        matched_paths = [p for p in paths if any(fnmatch.fnmatchcase(p, pat) for pat in rule.get("paths", []))]
        matched_words = [word for word in rule.get("keywords", []) if word.casefold() in request.casefold()]
        if matched_paths:
            reasons.append("path_match")
        if matched_words:
            reasons.append("keyword_match")
        if cmd["id"] in omit and cmd["required"]:
            warnings.append({"code": "REQUIRED_CHECK_OMISSION_PROPOSED", "command_id": cmd["id"]})
        selected = bool(reasons) and (cmd["required"] or cmd["id"] not in omit)
        choices.append({"command_id": cmd["id"], "required": cmd["required"],
                        "selected": selected, "executable": cmd["confirmed"],
                        "reasons": reasons if selected else ["caller_excluded" if cmd["id"] in omit else "impact_unconfirmed"],
                        "matched_paths": matched_paths, "matched_keywords": matched_words})
    return choices, warnings


def request_digest(request, paths):
    return tram.digest(tram.canonical({"request": request, "paths": paths}))


def recommend(project, slug, request, path=None, omit=None):
    root, profile, state, config, config_digest, snapshot = context(project, slug)
    if not isinstance(request, str) or not request.strip() or len(request) > 4096:
        tram.fail("INVALID_ARGUMENT", "4096자 이하의 작업 요청이 필요합니다")
    paths = strings(path or [], "path")
    for relative in paths:
        safe_path(root, relative)
    omissions = strings(omit or [], "omit")
    if set(omissions) - {c["id"] for c in profile["commands"]}:
        tram.fail("INVALID_ARGUMENT", "알 수 없는 검사 생략 요청입니다")
    choices, warnings = recommend_checks(profile["commands"], config["checks"], request, paths, omissions)
    for identity in set(config["checks"]) - {c["id"] for c in profile["commands"]}:
        warnings.append({"code": "observation_rule_unconfigured_command", "command_id": identity})
    policies = search(project, request, paths)
    return {"schema_version": SCHEMA, "kind": "recommendation", "mode": "observe", "slug": slug,
            "snapshot": snapshot, "config_digest": config_digest, "request_digest": request_digest(request, paths),
            "paths": paths, "checks": choices, "warnings": warnings,
            "policy_digests": {p["path"]: p["sha256"] for p in policies["results"]},
            "policy_search_truncated": policies["truncated"],
            "limitations": ["업무 영향·경로 밖 파급은 미확인", "추천은 기존 실행·완료 조건을 변경하지 않습니다"],
            "configured": config_digest != "missing", "writes": False}


def _mapping(root, paths):
    script = Path(__file__).resolve().parents[1] / "scripts/project-context.py"
    spec = importlib.util.spec_from_file_location("tram_observation_project_context", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.knowledge(SimpleNamespace(project=str(root), path=paths))


def search(project, query, path=None):
    root = tram.root_for(project)
    profile = tram.profile(root)
    config, config_digest = configuration(root, profile)
    if not isinstance(query, str) or not query.strip() or len(query) > 4096:
        tram.fail("INVALID_ARGUMENT", "검색어가 필요합니다")
    paths = strings(path or [], "path")
    for relative in paths:
        safe_path(root, relative)
    mapped = _mapping(root, paths)
    metadata = {item["path"]: item for item in config["knowledge"]["documents"]}
    candidates = set(mapped["document_paths"]) | set(metadata)
    warnings, skipped, truncated = list(mapped["warnings"]), [], False
    roots = ["docs/domain", "docs/knowledge", *config["knowledge"]["roots"]]
    folders_seen = 0
    for relative in roots:
        folder = _safe_document(root, relative)
        if not folder.exists():
            continue
        for folder_name, dirs, names in os.walk(folder, followlinks=False):
            folders_seen += 1
            dirs[:] = sorted(d for d in dirs if d not in tram.CACHE_DIRS | {".git", ".tram", "build", "dist"}
                             and not (Path(folder_name) / d).is_symlink())
            for name in sorted(names):
                item = (Path(folder_name) / name).relative_to(root).as_posix()
                if name.endswith(".md"):
                    candidates.add(item)
                if len(candidates) > MAX_DOCUMENTS:
                    truncated = True
                    break
            if len(candidates) > MAX_DOCUMENTS or folders_seen > 1000:
                truncated = True
                break
        if truncated:
            break
    tokens = list(dict.fromkeys([query.casefold(), *query.casefold().split()]))
    results = []
    mapping_paths = set(mapped["document_paths"])
    replacements = {}
    for item in metadata.values():
        for target in item.get("supersedes", []):
            replacements.setdefault(target, []).append(item["path"])
    superseded = {target: sources[0] for target, sources in replacements.items()}
    for relative in sorted(candidates, key=lambda p: (p not in mapping_paths, p))[:MAX_DOCUMENTS]:
        try:
            item = _safe_document(root, relative)
            if not item.is_file() or item.stat().st_size > MAX_DOCUMENT_BYTES:
                skipped.append(relative)
                continue
            text = item.read_text(encoding="utf-8")
        except (tram.TramError, OSError, UnicodeError):
            skipped.append(relative)
            continue
        meta = metadata.get(relative, {})
        corpus = (relative + " " + text + " " + " ".join(meta.get("tags", [])) + " " + " ".join(meta.get("scope", []))).casefold()
        matches = [token for token in tokens if token in corpus]
        if not matches and relative not in mapping_paths:
            continue
        diagnostic = []
        if relative in superseded:
            diagnostic.append("superseded_by:" + superseded[relative])
        if relative in meta.get("supersedes", []) or len(replacements.get(relative, [])) > 1 or any(
                relative in metadata.get(target, {}).get("supersedes", []) for target in meta.get("supersedes", [])):
            diagnostic.append("conflicting_supersession")
        if not meta.get("source") or not meta.get("confirmed_at"):
            diagnostic.append("provenance_unconfirmed")
        excerpt = next((line for line in text.splitlines() if any(t in line.casefold() for t in tokens)), text.splitlines()[0] if text else "")
        results.append({"path": relative, "sha256": file_digest(item), "mapped": relative in mapping_paths,
                        "matched_terms": matches, "score": len(matches), "excerpt": excerpt[:500],
                        "metadata": meta, "warnings": diagnostic, "validity": "unconfirmed"})
    results.sort(key=lambda x: (not x["mapped"], -x["score"], x["path"]))
    return {"mode": "observe", "results": results[:MAX_RESULTS], "mapping": mapped,
            "config_digest": config_digest, "searched_roots": roots,
            "truncated": truncated or len(candidates) > MAX_DOCUMENTS or len(results) > MAX_RESULTS,
            "skipped": skipped[:MAX_DOCUMENTS], "warnings": warnings,
            "limitations": ["검색 부재는 정책 부재가 아닙니다", "텍스트 의미 충돌·현행 유효성은 직접 확인해야 합니다"],
            "writes": False}


def storage_path(root, slug):
    tram.slug_path(root, slug)
    return safe_path(root, f".tram/local/harness/{slug}/latest.json")


def interpret_result(root, profile, state, config, snapshot, value):
    allowed = {"schema_version", "kind", "command_id", "run_id", "outcome", "declared_scope", "limitations", "cases_count", "artifacts", "reason"}
    if not isinstance(value, dict) or set(value) - allowed or not isinstance(value.get("outcome"), str) or value.get("outcome") not in {"passed", "failed", "needs_human_review", "not_run"}:
        tram.fail("INVALID_ARGUMENT", "결과 관찰 형식이 잘못되었습니다")
    identity = value.get("command_id")
    if not isinstance(identity, str) or identity not in {c["id"] for c in profile["commands"]}:
        tram.fail("INVALID_ARGUMENT", "기존 command ID가 필요합니다")
    strings(value.get("declared_scope", []), "declared_scope")
    strings(value.get("limitations", []), "limitations")
    declared = {"command_id": identity, "run_id": value.get("run_id"),
                "declared_scope": value.get("declared_scope", []),
                "limitations": value.get("limitations", []),
                "cases_count": value.get("cases_count"), "reason": value.get("reason")}
    artifacts = {}
    for relative in strings(value.get("artifacts", []), "artifacts"):
        artifacts[relative] = file_digest(_safe_artifact(root, relative))
    run_id = value.get("run_id")
    if value["outcome"] == "not_run":
        if run_id is not None or not isinstance(value.get("reason"), str) or not value["reason"].strip():
            tram.fail("INVALID_ARGUMENT", "not_run은 run_id null과 이유가 필요합니다")
        return {**declared, "state": "not_run", "source": "caller_reported", "runtime_execution": None,
                "warnings": [], "artifact_digests": artifacts}
    if not isinstance(run_id, str) or not run_id:
        tram.fail("INVALID_ARGUMENT", "run_id가 필요합니다")
    records = [r for r in state["verification"] if r.get("run_id") == run_id and r.get("command_id") == identity]
    warnings = []
    status = "unknown"
    run = records[-1] if records else None
    if not run:
        warnings.append("VERIFICATION_RESULT_INVALID")
    elif run.get("round") != state["round"] or run.get("snapshot") != snapshot or run.get("stale") or not run.get("recorded"):
        status = "stale"
        warnings.append("VERIFICATION_RESULT_INVALID")
    elif run.get("execution_status") != "succeeded" or run.get("exit_code") != 0:
        status = "failed"
        if value["outcome"] == "passed":
            warnings.append("VERIFICATION_RESULT_INVALID")
    else:
        status = {"passed": "reported_pass", "failed": "failed", "needs_human_review": "needs_human_review"}[value["outcome"]]
    rule = config["checks"].get(identity, {})
    count = value.get("cases_count")
    if "minimum_cases" in rule and (type(count) is not int or count < rule["minimum_cases"]):
        warnings.append("VERIFICATION_RESULT_INVALID")
        if status == "reported_pass":
            status = "unknown"
    elif count is not None and (type(count) is not int or count < 0):
        warnings.append("VERIFICATION_RESULT_INVALID")
        if status == "reported_pass":
            status = "unknown"
    elif count == 0 and "minimum_cases" not in rule:
        warnings.append("scope_unconfirmed_zero_cases")
    if status == "needs_human_review":
        warnings.append("HUMAN_REVIEW_PENDING")
    if any(d == "missing" for d in artifacts.values()):
        warnings.append("VERIFICATION_RESULT_INVALID")
        if status == "reported_pass":
            status = "unknown"
    return {**declared, "state": status, "source": "caller_reported", "runtime_execution": run.get("execution_status") if run else None,
            "warnings": list(dict.fromkeys(warnings)), "artifact_digests": artifacts}


def record(project, slug, file, expected_digest):
    root, profile, state, config, config_digest, snapshot = context(project, slug)
    value = read_json(safe_path(root, file))
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != SCHEMA:
        tram.fail("SCHEMA_INCOMPATIBLE", "관찰 입력 schema 1이 필요합니다")
    target = storage_path(root, slug)
    before = file_digest(target)
    if before != expected_digest:
        tram.fail("DIGEST_CONFLICT", "관찰 기록이 변경됐습니다")
    if value.get("kind") == "recommendation":
        if set(value) != {"schema_version", "kind", "report"}:
            tram.fail("INVALID_ARGUMENT", "recommendation report가 필요합니다")
        report = value["report"]
        if not isinstance(report, dict) or report.get("snapshot") != snapshot or report.get("config_digest") != config_digest or report.get("slug") != slug:
            tram.fail("DIGEST_CONFLICT", "현행 추천 결과가 필요합니다")
        required = {c["id"] for c in profile["commands"] if c["required"]}
        choices = report.get("checks")
        if not isinstance(choices, list) or not all(isinstance(c, dict) and isinstance(c.get("command_id"), str)
                and type(c.get("selected")) is bool for c in choices):
            tram.fail("INVALID_ARGUMENT", "checks 배열이 필요합니다")
        ids = [c["command_id"] for c in choices]
        if len(ids) != len(set(ids)) or set(ids) != {c["id"] for c in profile["commands"]}:
            tram.fail("INVALID_ARGUMENT", "현행 검사 목록이 모두 필요합니다")
        if not isinstance(report.get("request_digest"), str) or not re.fullmatch("[0-9a-f]{64}", report["request_digest"]):
            tram.fail("INVALID_ARGUMENT", "요청 digest가 필요합니다")
        for relative in strings(report.get("paths"), "paths"):
            safe_path(root, relative)
        if not required.issubset({c.get("command_id") for c in choices if c.get("selected") is True}):
            tram.fail("INVALID_ARGUMENT", "필수 검사를 제외한 추천은 저장하지 않습니다")
        observation = {"state": "recommendation", "source": "caller_reported", "report": report}
    elif value.get("kind") == "result":
        observation = interpret_result(root, profile, state, config, snapshot, value)
    else:
        tram.fail("INVALID_ARGUMENT", "recommendation 또는 result가 필요합니다")
    envelope = read_json(target) if target.exists() else {"schema_version": SCHEMA, "revision": 0, "records": []}
    validate_storage(envelope)
    if len(envelope["records"]) >= 100:
        tram.fail("INVALID_ARGUMENT", "작업당 관찰 100개 제한입니다")
    entry = {"timestamp": tram.now(), "snapshot": snapshot, "config_digest": config_digest,
             "input_digest": tram.digest(tram.canonical(value)), "input": value, "observation": observation}
    tram.local_path(root, f"harness/{slug}/latest.json")
    with tram.locked(root):
        _, _, _, _, current_digest, current_snapshot = context(project, slug)
        if current_digest != config_digest or current_snapshot != snapshot or file_digest(target) != expected_digest:
            tram.fail("DIGEST_CONFLICT", "기록 중 입력이 변경됐습니다")
        envelope["revision"] += 1
        envelope["records"].append(entry)
        data = tram.canonical(envelope) + b"\n"
        if len(data) > MAX_JSON:
            tram.fail("INVALID_ARGUMENT", "관찰 저장 크기 제한입니다")
        tram.atomic(target, data)
    return {"observation": observation, "storage_digest": file_digest(target), "revision": envelope["revision"], "writes": True}


def validate_storage(value):
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != SCHEMA:
        tram.fail("SCHEMA_INCOMPATIBLE", "관찰 기록 schema가 다릅니다")
    if type(value.get("revision")) is not int or value["revision"] < 0 or not isinstance(value.get("records"), list):
        tram.fail("INVALID_JSON", "관찰 기록 형식이 잘못되었습니다")
    for entry in value["records"]:
        if not isinstance(entry, dict) or not all(k in entry for k in ("snapshot", "config_digest", "input", "observation")) or not isinstance(entry["snapshot"], dict) or not isinstance(entry["config_digest"], str) or not isinstance(entry["input"], dict) or not isinstance(entry["observation"], dict):
            tram.fail("INVALID_JSON", "관찰 항목이 손상됐습니다")
        kind = entry["input"].get("kind")
        if not isinstance(kind, str) or kind not in {"recommendation", "result"}:
            tram.fail("INVALID_JSON", "저장된 관찰 종류가 잘못되었습니다")
        if kind == "result" and not isinstance(entry["input"].get("command_id"), str):
            tram.fail("INVALID_JSON", "저장된 검사 ID는 문자열이어야 합니다")


def show(project, slug, request=None, path=None):
    root, profile, state, config, config_digest, snapshot = context(project, slug)
    target = storage_path(root, slug)
    envelope = read_json(target) if target.exists() else {"schema_version": SCHEMA, "revision": 0, "records": []}
    validate_storage(envelope)
    paths = strings(path or [], "path")
    for relative in paths:
        safe_path(root, relative)
    results, declared_ids = [], set()
    for entry in envelope["records"]:
        observation = dict(entry["observation"])
        stale = entry["snapshot"] != snapshot or entry["config_digest"] != config_digest
        if entry["input"].get("kind") == "recommendation":
            report = observation.get("report", {})
            if not isinstance(report, dict) or not isinstance(report.get("policy_digests", {}), dict):
                tram.fail("INVALID_JSON", "저장된 추천 형식이 잘못되었습니다")
            validity = "unknown" if request is None or path is None else (
                "current" if report.get("request_digest") == request_digest(request, paths) else "stale")
            observation["request_validity"] = validity
            stale = stale or validity == "stale"
            observation["validity"] = "stale" if stale else validity
            changed_policies = []
            for relative, previous in report.get("policy_digests", {}).items():
                try:
                    current = file_digest(_safe_document(root, relative))
                except (tram.TramError, OSError):
                    current = "unavailable"
                if current != previous:
                    changed_policies.append(relative)
            if changed_policies:
                stale = True
                observation["validity"] = "stale"
            observation["changed_policies"] = changed_policies
        else:
            declared_ids.add(entry["input"].get("command_id"))
            try:
                observation = interpret_result(root, profile, state, config, snapshot, entry["input"])
            except (tram.TramError, OSError):
                observation = {"state": "unknown", "source": "caller_reported", "artifact_digests": {},
                               "warnings": ["VERIFICATION_RESULT_INVALID"]}
                stale = True
            old_digests = entry["observation"].get("artifact_digests", {})
            if observation["artifact_digests"] != old_digests:
                stale = True
            observation["validity"] = "stale" if stale else "current"
        if stale:
            observation["state"] = "stale"
        results.append(observation)
    missing = []
    for cmd in profile["commands"]:
        if cmd["id"] not in declared_ids:
            missing.append({"command_id": cmd["id"], "state": "unknown", "scope": "unknown",
                            "warnings": ["VERIFICATION_RESULT_MISSING"] if config["checks"].get(cmd["id"], {}).get("expects_result") else []})
    return {"mode": "observe", "records": results, "undeclared_results": missing,
            "storage_digest": file_digest(target), "config_digest": config_digest, "revision": envelope["revision"],
            "runtime": {"phase": state["phase"], "completion_issues": tram.completion_issues(root, profile, state, snapshot)},
            "writes": False}


def evaluate(project, file):
    root = tram.root_for(project)
    fixture = read_json(safe_path(root, file))
    if not isinstance(fixture, dict) or set(fixture) != {"schema_version", "cases"} or type(fixture["schema_version"]) is not int or fixture["schema_version"] != SCHEMA or not isinstance(fixture["cases"], list):
        tram.fail("INVALID_ARGUMENT", "평가 fixture schema/cases가 필요합니다")
    counts = {"expected": 0, "selected": 0, "missed": 0, "unnecessary": 0, "policy_expected": 0,
              "policy_hit": 0, "policy_missed": 0, "state_mismatch": 0, "unknown": 0,
              "not_run": 0, "stale": 0, "truncated": 0}
    rows = []
    for case in fixture["cases"]:
        if not isinstance(case, dict):
            tram.fail("INVALID_ARGUMENT", "평가 case 객체가 필요합니다")
        kind = case.get("kind")
        if kind == "recommendation":
            commands = case.get("commands")
            if not isinstance(commands, list) or any(not isinstance(c, dict) or set(c) != {"id", "required", "confirmed"} or not isinstance(c["id"], str) or type(c["required"]) is not bool or type(c["confirmed"]) is not bool for c in commands):
                tram.fail("INVALID_ARGUMENT", "평가 command 정의가 잘못됐습니다")
            synthetic = default_config()
            synthetic["checks"] = case.get("checks", {})
            validate_config(root, synthetic, {"commands": commands})
            if not isinstance(case.get("request", ""), str) or len(case.get("request", "")) > 4096:
                tram.fail("INVALID_ARGUMENT", "평가 요청 문자열이 필요합니다")
            expected = set(strings(case.get("expected", []), "expected"))
            choices, _ = recommend_checks(commands, case.get("checks", {}), case.get("request", ""), strings(case.get("paths", []), "paths"))
            selected = {c["command_id"] for c in choices if c["selected"]}
            counts["expected"] += len(expected)
            counts["selected"] += len(selected)
            counts["missed"] += len(expected - selected)
            counts["unnecessary"] += len(selected - expected)
            rows.append({"kind": kind, "missed": sorted(expected - selected), "unnecessary": sorted(selected - expected)})
        elif kind == "search":
            result = search(project, case.get("query"), case.get("paths", []))
            expected = set(strings(case.get("expected", []), "expected"))
            actual = {r["path"] for r in result["results"]}
            counts["policy_expected"] += len(expected)
            counts["policy_hit"] += len(expected & actual)
            counts["policy_missed"] += len(expected - actual)
            counts["truncated"] += int(result["truncated"])
            rows.append({"kind": kind, "missed": sorted(expected - actual)})
        elif kind == "result":
            if not isinstance(case.get("slug"), str):
                tram.fail("INVALID_ARGUMENT", "평가 task slug가 필요합니다")
            _, profile, state, config, _, snapshot = context(project, case.get("slug"))
            actual = interpret_result(root, profile, state, config, snapshot, case.get("input", {}))["state"]
            counts["state_mismatch"] += int(actual != case.get("expected"))
            if actual in {"unknown", "not_run", "stale"}:
                counts[actual] += 1
            rows.append({"kind": kind, "actual": actual, "expected": case.get("expected")})
        else:
            tram.fail("INVALID_ARGUMENT", "지원하지 않는 평가 kind입니다")
    return {"cases": rows, "counts": counts,
            "recommendation_recall": (counts["expected"] - counts["missed"]) / counts["expected"] if counts["expected"] else None,
            "policy_recall": counts["policy_hit"] / counts["policy_expected"] if counts["policy_expected"] else None,
            "performance": {"completion_time": None, "interventions": None, "post_completion_defects": None},
            "limitations": ["명시 fixture 정답 대비 평가이며 native host E2E가 아닙니다"], "writes": False}


def contract():
    return {"schema_version": SCHEMA, "mode": "observe", "completion_gates_changed": False,
            "actions": {"configure": "write", "record": "write", "recommend": "read", "search": "read", "show": "read", "evaluate": "read"},
            "config_example": {"mode": "observe", "checks": {}, "knowledge": {"roots": [], "documents": []}},
            "result_example": {"schema_version": SCHEMA, "kind": "result", "command_id": "test", "run_id": None,
                               "outcome": "not_run", "reason": "환경 미준비", "declared_scope": [], "limitations": []},
            "source": "caller_reported", "warnings_are_not_runtime_failures": True}
