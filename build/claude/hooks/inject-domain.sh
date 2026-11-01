#!/usr/bin/env bash
# PreToolUse(Edit|Write|MultiEdit): 편집 경로가 속한 서비스 도메인 문서를 주입한다.
# 매핑은 docs/domain/_territory.tsv의 <glob> <slug>에서 읽는다.
# 컨벤션 카드 훅의 형제: 목차 + 상세(작으면 전체·크면 머리와 포인터).
# 프로젝트·세션·도메인별 1회 주입한다.
# 입력: file_path 또는 Codex apply_patch command. 출력: additionalContext JSON.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/hook-profile.sh"
hook_dependencies
TIER_MAX_LINES=60
TIER_HEAD_LINES=16
input=$(cat)
hook_event "$input" PreToolUse || exit 0
proj=$(hook_project "$input")
proj=$(cd "$proj" && pwd -P)
map="$proj/docs/domain/_territory.tsv"
profile=$(project_profile_path "$proj")
# 신규 profile의 territories가 있으면 그것이 우선이다. legacy TSV는 조회 호환이다.
mapping=$(python3 - "$profile" "$map" <<'PY'
import json
from pathlib import Path, PurePosixPath
import re
import sys
profile, legacy = map(Path, sys.argv[1:])
if profile.is_file():
    config = json.loads(profile.read_text())
    entries = config.get('territories')
else:
    entries = None
if entries is None:
    if legacy.is_file():
        print(legacy.read_text(), end='')
else:
    if not isinstance(entries, list):
        raise SystemExit('inject-domain: territories는 배열이어야 합니다.')
    for entry in entries:
        pattern, slug = entry.get('path'), entry.get('slug')
        if not isinstance(pattern, str) or not isinstance(slug, str):
            raise SystemExit('inject-domain: 문자열 path/slug가 필요합니다.')
        if any(c.isspace() for c in pattern) or PurePosixPath(pattern).is_absolute() or '..' in PurePosixPath(pattern).parts:
            raise SystemExit('inject-domain: 프로젝트 상대 패턴이 필요합니다.')
        if not re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', slug):
            raise SystemExit('inject-domain: 잘못된 slug입니다.')
        print(pattern, slug)
PY
)
[ -n "$mapping" ] || exit 0
fp=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)
if [ -z "$fp" ]; then
  patch=$(printf '%s' "$input" | jq -r '.tool_input.command // .tool_input.patch // empty' 2>/dev/null || true)
  fp=$(printf '%s\n' "$patch" | sed -nE 's/^\*\*\* (Add|Update|Delete) File: //p; s/^\*\*\* Move to: //p')
fi
[ -n "$fp" ] || exit 0
# 경로를 정규화해 프로젝트 밖 편집은 매칭하지 않는다.
rels=$(python3 - "$proj" "$fp" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
for name in sys.argv[2].splitlines():
    path = Path(name)
    if not path.is_absolute():
        path = root / path
    try:
        print(path.resolve().relative_to(root).as_posix())
    except ValueError:
        continue
PY
)
[ -n "$rels" ] || exit 0
sid=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null || true)
ctx=""
while IFS= read -r rel; do
  # 각 파일의 첫 매핑을 사용한다. case의 *는 중첩 경로에도 매칭한다.
  slug=""
  while read -r glob s || [ -n "${glob:-}" ]; do
    case "$glob" in ''|'#'*) continue ;; esac
    case "$rel" in $glob) slug="$s"; break ;; esac
  done <<< "$mapping"
  [ -n "$slug" ] || continue
  # 매핑 slug로 도메인 디렉토리 밖 파일을 읽지 않는다.
  [[ "$slug" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || continue
  doc="$proj/docs/domain/$slug.md"
  [ -f "$doc" ] || continue
  python3 - "$proj" "$doc" <<'PY' || continue
import sys
from pathlib import Path
try:
    Path(sys.argv[2]).resolve().relative_to(Path(sys.argv[1]).resolve())
except ValueError:
    raise SystemExit(1)
PY
  header="📎 이 파일이 속한 서비스 도메인 문서 (docs/domain/$slug.md) — 코드를 만지기 전 이 도메인의 정체·경계·관계를 참고하라:"
  # 다중 파일 패치에서도 한 도메인은 한 번만 포함한다.
  case "$ctx" in *"$header"*) continue ;; esac
  lines=$(awk 'END {print NR}' "$doc")
  if [ "$lines" -le "$TIER_MAX_LINES" ]; then
    content=$(cat "$doc")
    note="전체"
  else
    content="$(head -n "$TIER_HEAD_LINES" "$doc")
…(이하 생략) — 더 깊은 맥락이 필요하면 docs/domain/$slug.md 를 exec_command로 직접 읽어라(Read)."
    note="요약 · 큰 문서라 머리만"
  fi
  # 세션 ID가 없으면 다른 세션까지 침묵시키지 않도록 dedup 없이 주입한다.
  if [ -n "$sid" ]; then
    key=$(printf '%s\n' "$proj" "$sid" "$slug" | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')
    hook_local_ready "$proj" || continue
    mark="$proj/.tram/local/markers/domain-${key}"
    if ! mkdir "$mark" 2>/dev/null; then
      [ -d "$mark" ] && continue
    fi
  fi
  [ -z "$ctx" ] || ctx="$ctx

"
  ctx="$ctx$header

== $slug 상세 ($note) ==
$content"
done <<< "$rels"
[ -n "$ctx" ] || exit 0
toc="(목차 파일 없음)"
readme="$proj/docs/domain/README.md"
[ ! -f "$readme" ] || toc=$(cat "$readme")
ctx="== 도메인 목차(라우팅) ==
$toc

$ctx"
jq -n --arg c "$ctx" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $c}}'
