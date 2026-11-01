#!/usr/bin/env bash
# .tram/project.json 우선. Python 기본값은 명시적 legacy 호환에서만 사용한다.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/project-profile.sh"

coverage_profile_adapter() {
  local root="$1"
  local profile
  profile=$(project_profile_path "$root")

  if [[ ! -f "$profile" ]]; then
    if [[ "${TRAM_LEGACY_PROFILE:-0}" == 1 ]]; then printf '%s\n' "python-pytest-cov"; else printf '%s\n' "unconfigured"; fi
    return 0
  fi

  jq -r --arg legacy "$([[ "$profile" == */.codex/project-profile.json ]] && echo 1 || echo 0)" 'if .coverage.configured == false then "unconfigured" elif .coverage == null then (if $legacy == "1" then "python-pytest-cov" else "unconfigured" end) else (.coverage.adapter // "unconfigured") end' "$profile"
}

coverage_profile_validate() {
  local root="$1"
  local profile
  profile=$(project_profile_path "$root")
  local root_real wrapper wrapper_dir wrapper_real

  [[ -d "$root" ]] || { echo "coverage-profile: project root not found: $root" >&2; return 2; }
  [[ "$(coverage_profile_adapter "$root")" != unconfigured ]] || { echo "coverage-profile: coverage adapter is unconfigured" >&2; return 2; }
  [[ -f "$profile" ]] || return 0

  if ! jq -e '
    def relpath:
      type == "string" and length > 0 and
      (startswith("/") | not) and
      (split("/") | all(. != ".." and . != "" and . != "."));
    def gradle_path:
      type == "string" and test("^(:[A-Za-z0-9_.-]+)+$");
    def supported_scope:
      type == "string" and (. == "jvm" or test("^android[A-Z][A-Za-z0-9]*$"));
    def kover_xml_task:
      type == "string" and
      test("^(:[A-Za-z0-9_.-]+)*:koverXmlReport(Jvm|[A-Z][A-Za-z0-9]*)?$") and
      (test("ios|js|native|linux|macos|mingw|wasm|connected|instrumentation|device|androidtest"; "i") | not);
    def task_matches_scope($jvm_targets):
      if .scope == "jvm" then
        (.task | test("^(:[A-Za-z0-9_.-]+)*:koverXmlReport([A-Z][A-Za-z0-9]*)?$")) and
        (.task | sub("^.*:koverXmlReport"; "") | ascii_downcase) as $target |
        (if $target == "" then
          ($jvm_targets | length == 0 or any(.[]; ascii_downcase == "jvm"))
        elif $target == "jvm" then true
        else ($jvm_targets | any(.[]; ascii_downcase == $target)) end)
      elif (.scope | startswith("android")) then
        (.scope | sub("^android"; "")) as $variant |
        (.task | test("^(:[A-Za-z0-9_.-]+)*:koverXmlReport" + $variant + "$"))
      else false end;
    def target_list:
      type == "array" and length > 0 and all(.[]; type == "string" and test("^[A-Za-z][A-Za-z0-9_]*$"));
    if (has("coverage") | not) or .coverage == null then true
    elif (.coverage | type) != "object" then false
    elif .coverage.adapter == "python-pytest-cov" then true
    elif .coverage.adapter != "kotlin-kover" then false
    else
      (.coverage.kmp.jvmTargets // []) as $jvm_targets |
      (
      (.coverage.target | type == "number" and . >= 1 and . <= 100 and floor == .) and
      (.coverage.modules | type == "array" and length > 0 and all(.[]; gradle_path)) and
      (.coverage.testPaths | type == "array" and length > 0 and all(.[]; relpath)) and
      (.coverage.gradle | type == "object") and
      (.coverage.gradle.wrapper | relpath) and
      (.coverage.gradle.tasks | type == "array" and length > 0 and all(.[];
        type == "object" and (.scope | supported_scope) and
        (.task | kover_xml_task) and task_matches_scope($jvm_targets) and
        (.report | relpath and endswith(".xml")))) and
      (.coverage.exclude == null or (.coverage.exclude | type == "array" and all(.[]; relpath))) and
      (.coverage.kmp == null or
        ((.coverage.kmp | type) == "object" and
          ((.coverage.kmp.jvmTargets == null) or (.coverage.kmp.jvmTargets | target_list)) and
          ((.coverage.kmp.nonJvmTargets == null) or .coverage.kmp.nonJvmTargets == "unsupported"))) and
      (.coverage.android == null or
        ((.coverage.android | type) == "object" and
          ((.coverage.android.variants == null) or (.coverage.android.variants | target_list)) and
          ((.coverage.android.unitTestsOnly == null) or .coverage.android.unitTestsOnly == true)))
      )
    end
  ' "$profile" >/dev/null; then
    echo "coverage-profile: invalid coverage configuration in $profile" >&2
    return 2
  fi

  if [[ "$(coverage_profile_adapter "$root")" == "kotlin-kover" ]]; then
    root_real=$(cd "$root" && pwd -P) || return 2
    wrapper=$(jq -r '.coverage.gradle.wrapper' "$profile")
    wrapper_dir=$(dirname "$wrapper")
    if [[ ! -x "$root/$wrapper" || ! -d "$root/$wrapper_dir" ]]; then
      echo "coverage-profile: configured Gradle wrapper is missing or not executable: $wrapper" >&2
      return 2
    fi
    wrapper_real=$(cd "$root/$wrapper_dir" && pwd -P)/$(basename "$wrapper")
    case "$wrapper_real" in
      "$root_real"/*) ;;
      *) echo "coverage-profile: Gradle wrapper resolves outside the project: $wrapper" >&2; return 2 ;;
    esac

    if ! python3 - "$root_real" "$profile" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
profile = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
coverage = profile["coverage"]
paths = [coverage["gradle"]["wrapper"]]
paths.extend(coverage["testPaths"])
paths.extend(coverage.get("exclude", []))
paths.extend(task["report"] for task in coverage["gradle"]["tasks"])

for relative in paths:
    candidate = root / relative
    probe = candidate
    while not probe.exists() and probe != root:
        probe = probe.parent
    try:
        probe.resolve().relative_to(root)
    except ValueError:
        print(f"coverage-profile: configured path resolves outside the project: {relative}", file=sys.stderr)
        raise SystemExit(2)

for relative in coverage["testPaths"]:
    if not (root / relative).is_dir():
        print(f"coverage-profile: test path does not exist as a directory: {relative}", file=sys.stderr)
        raise SystemExit(2)
PY
    then
      return 2
    fi
  fi
}
