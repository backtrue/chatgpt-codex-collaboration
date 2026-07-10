#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: preflight.sh <repository-path> <remote> <branch> [required-command ...]" >&2
}

[[ $# -ge 3 ]] || { usage; exit 2; }
repo="$1"; remote="$2"; branch="$3"; shift 3
errors=()
warnings=()

[[ -d "$repo" ]] || errors+=("repository-path-missing")
if [[ -d "$repo" ]]; then
  git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1 || errors+=("not-a-git-worktree")
fi

if ((${#errors[@]} == 0)); then
  git -C "$repo" remote get-url "$remote" >/dev/null 2>&1 || errors+=("missing-remote:$remote")
  git check-ref-format --branch "$branch" >/dev/null 2>&1 || errors+=("invalid-branch:$branch")
  [[ -z "$(git -C "$repo" status --porcelain)" ]] || errors+=("worktree-not-clean")
  git -C "$repo" ls-remote "$remote" >/dev/null 2>&1 || errors+=("remote-unreachable")
  if git -C "$repo" show-ref --verify --quiet "refs/heads/$branch"; then
    warnings+=("local-branch-exists:$branch")
  fi
fi

for cmd in "$@"; do
  command -v "$cmd" >/dev/null 2>&1 || errors+=("missing-command:$cmd")
done

ready=true
((${#errors[@]} > 0)) && ready=false
errors_text="$(printf '%s\n' "${errors[@]-}")"
warnings_text="$(printf '%s\n' "${warnings[@]-}")"
python3 - "$ready" "$errors_text" "$warnings_text" <<'PY'
import json, sys
ready = sys.argv[1] == "true"
errors = [x for x in sys.argv[2].splitlines() if x]
warnings = [x for x in sys.argv[3].splitlines() if x]
print(json.dumps({"ready": ready, "errors": errors, "warnings": warnings}, indent=2))
PY
$ready || exit 2
