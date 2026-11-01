#!/usr/bin/env bash
# 디자인된 HTML 도식을 PNG 이미지로 뽑는다 (헤드리스 Chrome 스크린샷).
# 사용법: screenshot-html.sh <input.html> <output.png> [width] [height]
# 스크린샷은 viewport만 캡처하므로, 아래가 잘리면 height를 키워 다시 실행한다.

set -euo pipefail

in="${1:?입력 .html 경로 필요}"
out="${2:?출력 .png 경로 필요}"
w="${3:-1040}"
h="${4:-900}"
source "$(dirname "$0")/lib/chrome-path.sh"
chrome=$(find_chrome \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Chromium.app/Contents/MacOS/Chromium")

mkdir -p "$(dirname "$out")"
abs="$(cd "$(dirname "$in")" && pwd)/$(basename "$in")"
profile=$(mktemp -d "${TMPDIR:-/tmp}/tram-screenshot.XXXXXXXX")
trap 'rm -rf "$profile"' EXIT

"$chrome" --headless=new --disable-gpu --no-sandbox --disable-dev-shm-usage \
  --hide-scrollbars --no-first-run --no-default-browser-check --user-data-dir="$profile" \
  --force-device-scale-factor=2 --window-size="${w},${h}" \
  --screenshot="$out" "file://${abs}" >/dev/null 2>&1

echo "screenshot: $out (${w}x${h})"
