#!/usr/bin/env bash
# Resolve Chrome/Chromium from CHROME_PATH, known app locations, then PATH.
find_chrome() {
  if [ -n "${CHROME_PATH:-}" ]; then
    [ -x "$CHROME_PATH" ] && { printf '%s\n' "$CHROME_PATH"; return 0; }
    echo "CHROME_PATH 실행 파일을 찾을 수 없습니다: $CHROME_PATH" >&2
    return 1
  fi
  for candidate in "$@"; do
    if [ -x "$candidate" ]; then printf '%s\n' "$candidate"; return 0; fi
  done
  for name in google-chrome google-chrome-stable chromium chromium-browser; do
    candidate=$(command -v "$name" 2>/dev/null || true)
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then printf '%s\n' "$candidate"; return 0; fi
  done
  echo "Chrome/Chromium을 찾을 수 없습니다. CHROME_PATH를 지정하세요." >&2
  return 1
}
