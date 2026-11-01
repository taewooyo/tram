#!/usr/bin/env bash
# PreToolUse(Bash): push 전 /retro 호출 흔적 검사. 실제 push는 실행하지 않는다.
# 마커는 마지막 게이트 통과 시각과 HEAD. 최초 실행은 설치 기준만 남긴다.
# 실행 의존성: Bash, jq, python3, git. legacy 기록은 읽기만 한다.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/hook-profile.sh"
hook_dependencies
payload=$(cat)
hook_event "$payload" PreToolUse || exit 0
root=$(hook_project "$payload")
export TRAM_TARGET_ROOT="$root"
RETRO_GATE_PAYLOAD="$payload" python3 - <<'PY'
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


def git(*args, cwd=None):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True,
                                   stderr=subprocess.DEVNULL).strip()


# 토큰 단위로 실행 명령을 구별한다. echo의 인자·주석 속 git push는 제외한다.
command = json.loads(os.environ["RETRO_GATE_PAYLOAD"]).get("tool_input", {}).get("command", "")
lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|\n")
lexer.whitespace = " \t\r"
tokens = list(lexer)
segments = [[]]
for token in tokens:
    if token and all(c in ";&|\n" for c in token):
        segments.append([])
    else:
        segments[-1].append(token)
pushes = []
for segment in segments:
    bypass = os.environ.get("SKIP_RETRO_GATE") == "1"
    if segment[:1] == ["env"]:
        segment = segment[1:]
    while segment and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", segment[0]):
        key, value = segment.pop(0).split("=", 1)
        if key == "SKIP_RETRO_GATE":
            bypass = value == "1"
    if segment[:2] == ["git", "push"]:
        pushes.append(bypass)
if not pushes or all(pushes):
    sys.exit(0)

root = Path(os.environ["TRAM_TARGET_ROOT"])
try:
    root = Path(git("rev-parse", "--show-toplevel", cwd=root))
except (subprocess.CalledProcessError, FileNotFoundError):
    sys.exit(0)
logs = [root / ".tram/local/logs/skill-usage.log", root / ".codex/skill-usage.log"]
marker = root / ".tram/local/markers/retro-gate"
legacy_marker = root / ".codex/.retro-gate-marker"
if not marker.exists() and legacy_marker.exists():
    previous_marker = legacy_marker
else:
    previous_marker = marker
head = git("rev-parse", "HEAD", cwd=root)
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def mark():
    ignore = root / ".gitignore"
    if not ignore.is_file() or ".tram/local/" not in ignore.read_text().splitlines():
        print("retro-gate: init으로 .tram/local/ 제외 규칙을 먼저 연결하세요.", file=sys.stderr)
        raise SystemExit(2)
    try:
        marker.resolve().relative_to(root.resolve())
    except ValueError:
        raise SystemExit(2)
    if subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', str(marker)]).returncode:
        print('retro-gate: local marker 제외 규칙이 충돌합니다.', file=sys.stderr)
        raise SystemExit(2)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{now}\n{head}\n", encoding="utf-8")


if not previous_marker.exists():
    mark()
    sys.exit(0)
lines = previous_marker.read_text(encoding="utf-8").splitlines()
if len(lines) >= 2 and lines[1] == head:
    sys.exit(0)  # 새 커밋 없음: 같은 push 재시도 안전
if not any(log.exists() for log in logs):
    sys.exit(0)  # 사용자 지정 정책: 로그 없으면 판단 불가, 통과
since = lines[0] if lines else now
for line in (line for log in logs if log.exists() for line in log.read_text(encoding="utf-8").splitlines()):
    fields = line.split("\t")
    if len(fields) >= 2 and fields[1] == "retro" and fields[0] >= since:
        mark()
        sys.exit(0)
print("이번에 푸시할 작업에 /retro 회고 흔적이 없습니다(마지막 게이트 통과 이후).", file=sys.stderr)
print("먼저 /retro로 회고한 뒤 다시 push 하세요. 불필요한 경우 SKIP_RETRO_GATE=1 git push ... 로 우회할 수 있습니다.", file=sys.stderr)
sys.exit(2)
PY
