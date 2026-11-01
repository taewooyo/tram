#!/usr/bin/env bash
# Check tools required by the common OS or a selected optional integration.
set -u

mode="${1:-core}"
[[ $# -eq 0 ]] || shift
target="$PWD"
coverage_python="python3"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) target="${2:?--project 경로 필요}"; shift 2 ;;
    --python) coverage_python="${2:?--python 실행 파일 필요}"; shift 2 ;;
    *) echo "알 수 없는 인자: $1" >&2; exit 2 ;;
  esac
done
script_dir="${BASH_SOURCE[0]%/*}"
source "$script_dir/lib/chrome-path.sh"
case "$mode" in
  core|hooks|coverage|coverage-kotlin|diagram|mermaid|github) ;;
  -h|--help|help)
    echo "Usage: check-environment.sh [core|hooks|coverage|coverage-kotlin|diagram|mermaid|github] [--project ROOT] [--python PYTHON]"
    echo "  core      Python 3.10+ only; hooks: Bash, jq, Python"
    echo "  coverage  core tools plus pytest and pytest-cov in python3"
    echo "  coverage-kotlin  core tools plus a Java runtime for the configured Gradle wrapper"
    echo "  diagram   core tools plus Chrome/Chromium"
    echo "  mermaid   core tools plus Chrome/Chromium, Node.js and npx"
    echo "  github    core tools plus GitHub CLI (gh)"
    exit 0
    ;;
  *)
    echo "알 수 없는 검사 모드: $mode" >&2
    echo "사용법: $0 [core|coverage|coverage-kotlin|diagram|mermaid|github]" >&2
    exit 2
    ;;
esac

missing=0
check_command() {
  name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    printf '✅ %s: %s\n' "$name" "$(command -v "$name")"
  else
    printf '❌ 필수 도구 없음: %s\n' "$name"
    missing=1
  fi
}

echo "개발 OS 환경 검사: $mode"
for tool in python3; do
  check_command "$tool"
done

if command -v python3 >/dev/null 2>&1; then
  python_version=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)
  if [ -z "$python_version" ]; then
    echo "❌ Python 버전을 확인할 수 없습니다."
    missing=1
  else
    python_major=${python_version%%.*}
    python_minor=${python_version#*.}
    if [ "$python_major" -lt 3 ] || { [ "$python_major" -eq 3 ] && [ "$python_minor" -lt 10 ]; }; then
      echo "❌ Python 3.10 이상 필요: 현재 $python_version"
      missing=1
    else
      echo "✅ Python 버전: $python_version"
    fi
  fi
fi

case "$mode" in
  hooks) for tool in bash jq; do check_command "$tool"; done ;;
  coverage)
    for tool in bash jq git; do check_command "$tool"; done
    git -C "$target" rev-parse --show-toplevel >/dev/null 2>&1 || { echo '❌ coverage는 Git 프로젝트가 필요합니다.'; missing=1; }
    if command -v "$coverage_python" >/dev/null 2>&1; then
      if "$coverage_python" -c 'import pytest, pytest_cov' >/dev/null 2>&1; then
        echo "✅ pytest + pytest-cov ($coverage_python)"
      else
        echo "❌ pytest와 pytest-cov가 python3 환경에 필요합니다. docs/setup.md를 참고하세요."
        missing=1
      fi
    else
      echo "❌ 선택한 Python 실행 파일 없음: $coverage_python"
      missing=1
    fi
    ;;
  coverage-kotlin)
    for tool in bash jq git; do check_command "$tool"; done
    git -C "$target" rev-parse --show-toplevel >/dev/null 2>&1 || { echo '❌ coverage는 Git 프로젝트가 필요합니다.'; missing=1; }
    source "$script_dir/lib/coverage-profile.sh"
    coverage_profile_validate "$target" || missing=1
    check_command java
    if command -v java >/dev/null 2>&1; then
      if java -version >/dev/null 2>&1; then
        echo "✅ Java runtime is executable"
      else
        echo "❌ Java runtime 실행에 실패했습니다."
        missing=1
      fi
    fi
    echo "ℹ️ Gradle은 시스템 전역 설치 대신 프로젝트에서 설정한 실행 가능한 wrapper를 사용하세요."
    ;;
  diagram)
    if chrome=$(find_chrome \
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      "/Applications/Chromium.app/Contents/MacOS/Chromium"); then
      printf '✅ Chrome: %s\n' "$chrome"
    else
      echo "❌ Chrome/Chromium을 찾을 수 없습니다. CHROME_PATH를 지정하세요."
      missing=1
    fi
    ;;
  mermaid)
    if chrome=$(find_chrome \
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      "/Applications/Chromium.app/Contents/MacOS/Chromium"); then
      printf '✅ Chrome: %s\n' "$chrome"
    else
      echo "❌ Chrome/Chromium 필요: CHROME_PATH를 지정하세요."
      missing=1
    fi
    check_command node
    check_command npx
    ;;
  github)
    check_command gh
    ;;
esac

if [ "$missing" -eq 0 ]; then
  echo "검사 통과: $mode"
  exit 0
fi
echo "필수 도구를 확인한 뒤 다시 실행하세요: $0 $mode" >&2
exit 1
