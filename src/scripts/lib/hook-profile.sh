#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/project-profile.sh"
hook_dependencies() {
  local tool
  for tool in jq python3; do
    command -v "$tool" >/dev/null || { echo "Tram hook: $tool 필요; 카드 읽기/명시적 사전 검사를 사용하세요." >&2; return 2; }
  done
}
hook_project() {
  local cwd
  cwd=$(printf '%s' "$1" | jq -r '.cwd // empty')
  cwd="${cwd:-${CODEX_PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-$PWD}}}"
  python3 - "$cwd" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve(strict=True)
for candidate in (root, *root.parents):
    if (candidate / '.tram/project.json').is_file():
        print(candidate)
        break
else:
    print(root)
PY
}
hook_event() {
  local event
  event=$(printf '%s' "$1" | jq -r '.hook_event_name // empty')
  [[ -z "$event" || "$event" == "$2" ]]
}
hook_local_ready() {
  # init이 관리하는 제외 규칙이 없으면 개인 로그/marker를 만들지 않는다.
  [[ -f "$1/.gitignore" ]] && grep -qxF '.tram/local/' "$1/.gitignore" || {
    echo 'Tram hook: .tram/local/ 제외 규칙 필요 (init)' >&2; return 1;
  }
  python3 - "$1" <<'PY' || return 1
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
for name in ('.tram/local/markers', '.tram/local/logs'):
    try:
        (root / name).resolve().relative_to(root)
    except ValueError:
        raise SystemExit(1)
PY
  if command -v git >/dev/null && git -C "$1" rev-parse --show-toplevel >/dev/null 2>&1; then
    git -C "$1" check-ignore -q .tram/local/logs/skill-usage.log || return 1
    git -C "$1" check-ignore -q .tram/local/markers/probe || return 1
  elif grep -q '^!' "$1/.gitignore"; then
    echo 'Tram hook: nonGit 제외 규칙 충돌을 확인하세요.' >&2; return 1
  fi
  mkdir -p "$1/.tram/local/markers" "$1/.tram/local/logs"
}
