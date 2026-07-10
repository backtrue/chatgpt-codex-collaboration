#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: validate-handoff.sh <repo-path> <remote> <branch> <base-sha> <candidate-sha> <allowed-path>..." >&2
}

[[ $# -ge 6 ]] || { usage; exit 2; }
repo="$1"; remote="$2"; branch="$3"; base="$4"; candidate="$5"; shift 5
allowed=("$@")
errors=()
changed=()

[[ "$base" =~ ^[0-9a-fA-F]{40}$ ]] || errors+=("invalid-base-sha")
[[ "$candidate" =~ ^[0-9a-fA-F]{40}$ ]] || errors+=("invalid-candidate-sha")

if ((${#errors[@]} == 0)); then
  remote_sha="$(git -C "$repo" ls-remote --heads "$remote" "refs/heads/$branch" | awk 'NR==1{print $1}')"
  [[ -n "$remote_sha" ]] || errors+=("remote-branch-missing")
  [[ "$remote_sha" == "$candidate" ]] || errors+=("candidate-not-current-remote-head")
  [[ "$candidate" != "$base" ]] || errors+=("candidate-equals-base-sha")
  git -C "$repo" cat-file -e "$candidate^{commit}" 2>/dev/null || git -C "$repo" fetch --quiet "$remote" "$branch"
  mapfile -t changed < <(git -C "$repo" diff --name-only "$base" "$candidate")
fi

path_allowed() {
  local path="$1" pattern
  for pattern in "${allowed[@]}"; do
    if [[ "$pattern" == */ ]]; then
      [[ "$path" == "$pattern"* ]] && return 0
    elif [[ "$path" == "$pattern" ]]; then
      return 0
    fi
  done
  return 1
}

for path in "${changed[@]}"; do
  path_allowed "$path" || errors+=("out-of-scope:$path")
  case "$path" in
    *.zip|*.tar|*.tar.gz|*.tgz|*.pem|*.key|.env|*/.env|*.tmp|*.swp) errors+=("forbidden-artifact:$path") ;;
  esac
done

valid=true
((${#errors[@]} > 0)) && valid=false
changed_text="$(printf '%s\n' "${changed[@]-}")"
errors_text="$(printf '%s\n' "${errors[@]-}")"
python3 - "$valid" "$changed_text" "$errors_text" <<'PY'
import json, sys
valid = sys.argv[1] == "true"
changed = [x for x in sys.argv[2].splitlines() if x]
errors = [x for x in sys.argv[3].splitlines() if x]
print(json.dumps({"valid": valid, "changed_files": changed, "errors": errors}, indent=2))
PY
$valid || exit 2
