#!/usr/bin/env bash
# SessionEnd 훅: 세션이 끝날 때 /retro 실행을 안내한다(자동 실행 아님).
# /retro는 맥락이 살아있는 세션에서 사람이 직접 실행하는 대화형 회고다.
# 종료 후에는 해당 세션을 다시 열어 회고하도록 안내한다.
# Codex나 Claude를 호출하지 않으므로 재귀 실행이 없다. 종료를 막지 않는다.
# 입력(stdin JSON): { transcript_path, session_id, ... }
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/hook-profile.sh"
hook_dependencies
input=$(cat)
hook_event "$input" SessionEnd || exit 0
# 실질 세션만 안내: transcript 20줄 이상. 짧은 세션 알림 노이즈 방지.
tp=$(printf '%s' "$input" | jq -r '.transcript_path // empty' 2>/dev/null || true)
lines=0
[ -n "$tp" ] && [ -f "$tp" ] && lines=$(wc -l < "$tp" 2>/dev/null | tr -d ' ')
[ "${lines:-0}" -ge 20 ] || exit 0
# macOS 알림. 테스트에서는 RETRO_REMINDER_SILENT=1로 억제한다.
title="🔁 세션 종료 · 회고 리마인더"
msg="이번 세션을 다시 열어 /retro 회고를 실행하세요 (스킬 개선 + 도메인 변경점)"
if [ "${RETRO_REMINDER_SILENT:-}" != "1" ] && command -v osascript >/dev/null 2>&1; then
  osascript -e "display notification \"$msg\" with title \"$title\"" >/dev/null 2>&1 || true
fi
# 관측·테스트용 표식. 종료 후라 화면에 보이지 않을 수 있다.
echo "retro-reminder: 세션 종료 — /retro 회고 권장"
exit 0
