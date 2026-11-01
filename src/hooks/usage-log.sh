#!/usr/bin/env bash
# 명시적인 Skill/UserPromptSubmit 이벤트만 기록. 원문 프롬프트/인자는 보존하지 않는다.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/hook-profile.sh"
hook_dependencies
input=$(cat)
skill=$(printf '%s' "$input" | python3 -c '
import json,re,sys
p=json.load(sys.stdin)
event=p.get("hook_event_name", "")
name=""
if event == "PreToolUse" and p.get("tool_name") == "Skill":
    name=p.get("tool_input",{}).get("skill", "")
elif event == "UserPromptSubmit":
    match=re.match(r"^[/\$]([A-Za-z][A-Za-z0-9:_-]*)",p.get("prompt", ""))
    name=match.group(1) if match else ""
if isinstance(name,str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9:_-]{0,127}",name):
    print(name)
')
[ -n "$skill" ] || exit 0
root=$(hook_project "$input")
hook_local_ready "$root" || exit 0
printf '%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${skill##*:}" >> "$root/.tram/local/logs/skill-usage.log"
