#!/usr/bin/env bash
set -euo pipefail

version_ge() {
  local actual="$1" required="$2"
  [[ "$(printf '%s\n%s\n' "$required" "$actual" | sort -V | head -n1)" == "$required" ]]
}

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"
}

required_missing=()
optional_missing=()

check_command() {
  local command="$1" minimum="$2" actual
  if ! command -v "$command" >/dev/null 2>&1; then
    required_missing+=("command:$command")
    return
  fi
  case "$command" in
    git) actual="$(git --version | awk '{print $3}')" ;;
    bash) actual="${BASH_VERSION%%(*}" ;;
    python3) actual="$(python3 -c 'import platform; print(platform.python_version())')" ;;
    *) return ;;
  esac
  if ! version_ge "$actual" "$minimum"; then
    required_missing+=("command:$command>=$minimum (found $actual)")
  fi
}

check_command git 2.30
check_command bash 4.0
check_command python3 3.9
command -v jq >/dev/null 2>&1 || optional_missing+=("command:jq")

ready=true
((${#required_missing[@]} > 0)) && ready=false

printf '{\n  "ready": %s,\n  "required_missing": [' "$ready"
for i in "${!required_missing[@]}"; do
  ((i > 0)) && printf ', '
  json_escape "${required_missing[$i]}" | tr -d '\n'
done
printf '],\n  "optional_missing": ['
for i in "${!optional_missing[@]}"; do
  ((i > 0)) && printf ', '
  json_escape "${optional_missing[$i]}" | tr -d '\n'
done
printf '],\n  "fallbacks": [{"dependency":"capability:github_webhook","fallback":"branch_polling"}]\n}\n'

$ready || exit 2
