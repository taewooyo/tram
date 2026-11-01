#!/usr/bin/env bash
# 검사 대상: 직접 gh pr create --body/--body-file 호출. 복잡한 shell은 명시적 사전 검사 필요.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/hook-profile.sh"
hook_dependencies
input=$(cat)
hook_event "$input" PreToolUse || exit 0
root=$(hook_project "$input")
tool_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
printf '%s' "$input" | python3 "$tool_root/scripts/check-pr-body.py" --project "$root" --tool-root "$tool_root"
