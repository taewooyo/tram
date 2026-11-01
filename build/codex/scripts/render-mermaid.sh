#!/usr/bin/env bash
# Mermaid(.mmd) 파일을 PNG로 렌더한다. 시스템 Chrome을 headless로 사용한다.
# 사용법: render-mermaid.sh <input.mmd> <output.png>

set -euo pipefail

in="${1:?입력 .mmd 경로 필요}"
out="${2:?출력 .png 경로 필요}"
source "$(dirname "$0")/lib/chrome-path.sh"
chrome=$(find_chrome \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Chromium.app/Contents/MacOS/Chromium")

cfg="$(mktemp)"
trap 'rm -f "$cfg"' EXIT
printf '{"executablePath":"%s","args":["--no-sandbox"]}\n' "$chrome" > "$cfg"

mkdir -p "$(dirname "$out")"

# Puppeteer가 별도 Chromium을 내려받지 않고 시스템 Chrome을 사용하게 한다.
PUPPETEER_SKIP_DOWNLOAD=true \
  npx -y @mermaid-js/mermaid-cli@12.0.0 \
    -i "$in" -o "$out" -p "$cfg" -b transparent -s 2

echo "rendered: $out"
