#!/usr/bin/env bash
# 신규 프로필 우선. legacy 파일이 실제 있거나 명시적 opt-in일 때만 호환한다.
project_profile_path() {
  if [[ -f "$1/.tram/project.json" ]]; then
    [[ ! -f "$1/.codex/project-profile.json" ]] || echo 'Tram: .tram/project.json 우선 (legacy 프로필은 읽지 않음)' >&2
    printf '%s\n' "$1/.tram/project.json"
  elif [[ -f "$1/.codex/project-profile.json" || "${TRAM_LEGACY_PROFILE:-0}" == 1 ]]; then
    printf '%s\n' "$1/.codex/project-profile.json"
  else
    printf '%s\n' "$1/.tram/project.json"
  fi
}
