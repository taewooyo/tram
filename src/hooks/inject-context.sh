#!/usr/bin/env bash
# PreToolUse(Edit|Write|MultiEdit): 프로젝트 프로필의 경로별 컨벤션 카드를 주입한다.
# 입력: tool_input.file_path, session_id. 출력: additionalContext JSON.
# 신규 프로젝트는 암묵적 Android 매핑을 사용하지 않는다.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/hook-profile.sh"
hook_dependencies
input=$(cat)
hook_event "$input" PreToolUse || exit 0
proj=$(hook_project "$input")
proj=$(cd "$proj" && pwd -P)
fp=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)
if [ -z "$fp" ]; then
  patch=$(printf '%s' "$input" | jq -r '.tool_input.command // .tool_input.patch // empty' 2>/dev/null || true)
  # Codex apply_patch는 한 호출에 여러 파일을 편집할 수 있다.
  fp=$(printf '%s\n' "$patch" | sed -nE 's/^\*\*\* (Add|Update|Delete) File: //p; s/^\*\*\* Move to: //p')
fi
[ -n "$fp" ] || exit 0
# ../·절대경로를 정규화해 프로젝트 바깥 파일이 매칭되지 않게 한다.
rels=$(python3 - "$proj" "$fp" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
for name in sys.argv[2].splitlines():
    path = Path(name)
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.resolve().relative_to(root).as_posix()
    except ValueError:
        continue
    print(relative)
PY
)
sid=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null || true)
if ! cards=$(python3 - "$proj" "$(project_profile_path "$proj")" "$rels" <<'PY'
import fnmatch
import json
import sys
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1]).resolve()
profile = Path(sys.argv[2])
relative_paths = sys.argv[3].splitlines()

def fail(message):
    print(f"inject-context: {message}", file=sys.stderr)
    raise SystemExit(2)

if not profile.is_file():
    mappings = []
else:
    try:
        config = json.loads(profile.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"프로젝트 프로필을 읽을 수 없습니다: {error}")
    if not isinstance(config, dict):
        fail("프로젝트 프로필은 객체여야 합니다.")
    # schema 1/legacy and current schema 2 share the convention mapping format.
    # bool is an int subclass in Python, but is never a valid schema version.
    schema = config.get("schema_version", config.get("version"))
    if type(schema) is not int or schema not in (1, 2):
        fail("지원하지 않는 프로젝트 프로필 형식입니다 (schema 1 또는 2 필요).")
    mappings = config.get("conventions", config.get("contextMappings", config.get("conventionMappings", [])))
    if not isinstance(mappings, list):
        fail("contextMappings는 배열이어야 합니다.")

validated = []
for index, mapping in enumerate(mappings):
    if not isinstance(mapping, dict):
        fail(f"contextMappings[{index}]는 객체여야 합니다.")
    pattern, card = mapping.get("path"), mapping.get("card")
    if not isinstance(pattern, str) or not isinstance(card, str):
        fail(f"contextMappings[{index}]에는 문자열 path와 card가 필요합니다.")
    if any(char in pattern + card for char in "\r\n\t"):
        fail(f"contextMappings[{index}]에 제어 문자가 있습니다.")
    pattern_path = PurePosixPath(pattern)
    card_path = Path(card)
    if pattern_path.is_absolute() or ".." in pattern_path.parts:
        fail(f"프로젝트 상대 경로 패턴이 아닙니다: {pattern}")
    if card_path.is_absolute() or ".." in card_path.parts:
        fail(f"프로젝트 내부 카드 경로가 아닙니다: {card}")
    resolved = (root / card_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        fail(f"프로젝트 바깥 컨텍스트 카드는 허용되지 않습니다: {card}")
    if not resolved.is_file():
        fail(f"컨텍스트 카드 파일을 찾을 수 없습니다: {card}")
    validated.append((pattern, resolved.relative_to(root).as_posix()))

seen = set()
for relative in relative_paths:
    for pattern, card in validated:
        if fnmatch.fnmatchcase(relative, pattern) and card not in seen:
            print(card)
            seen.add(card)
PY
); then
  echo "inject-context: 컨텍스트 프로필이 잘못되어 이번 편집에는 카드를 주입하지 않습니다." >&2
  exit 0
fi
ctx=""
while IFS= read -r card_rel; do
  [ -n "$card_rel" ] || continue
  card="$proj/$card_rel"
  content=$(cat "$card")
  # 같은 세션에서 같은 카드가 다시 편집돼도 한 번만 주입한다.
  if [ -n "$sid" ]; then
    key=$(printf '%s\n' "$proj" "$sid" "$card_rel" | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')
    hook_local_ready "$proj" || continue
    mark="$proj/.tram/local/markers/context-${key}"
    # 원자적 mkdir으로 같은 세션의 동시 편집도 한 번만 주입한다.
    if ! mkdir "$mark" 2>/dev/null; then
      [ -d "$mark" ] && continue
    fi
  fi
  [ -z "$ctx" ] || ctx="$ctx

"
  ctx="$ctx$content"
done <<< "$cards"
[ -n "$ctx" ] || exit 0
jq -n --arg c "$ctx" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $c}}'
