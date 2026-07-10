#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  wait-for-handoff.sh <task-id> <branch> <base-sha> [lease-seconds] [poll-seconds]

Wait until the assigned remote branch HEAD differs from the recorded base SHA.
The script performs transport-level polling only; it does not invoke a model.

Environment:
  REMOTE          Git remote to inspect (default: origin)
  DISPATCH_EPOCH  Original dispatch time as Unix epoch. Set this when restarting
                  the watcher so a tool timeout does not reset the lease.

Exit codes:
  0    A candidate handoff commit appeared.
  2    Invalid arguments or repository state.
  124  The observation lease expired. This is not an implementation failure.
EOF
}

if [[ $# -lt 3 || $# -gt 5 ]]; then
  usage >&2
  exit 2
fi

TASK_ID="$1"
BRANCH="$2"
BASE_SHA="$3"
LEASE_SECONDS="${4:-7200}"
POLL_SECONDS="${5:-30}"
REMOTE="${REMOTE:-origin}"
START_EPOCH="${DISPATCH_EPOCH:-$(date +%s)}"

if [[ ! "$TASK_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "error=invalid_task_id" >&2
  exit 2
fi

if ! git check-ref-format --branch "$BRANCH" >/dev/null 2>&1; then
  echo "error=invalid_branch branch=$BRANCH" >&2
  exit 2
fi

if [[ ! "$BASE_SHA" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "error=invalid_base_sha" >&2
  exit 2
fi

if [[ ! "$LEASE_SECONDS" =~ ^[1-9][0-9]*$ || ! "$POLL_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "error=invalid_timing" >&2
  exit 2
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error=not_a_git_worktree" >&2
  exit 2
fi

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  echo "error=missing_remote remote=$REMOTE" >&2
  exit 2
fi

last_state=""

emit_state() {
  local state="$1"
  local now elapsed
  now="$(date +%s)"
  elapsed=$((now - START_EPOCH))
  echo "event=$state task_id=$TASK_ID branch=$BRANCH elapsed_seconds=$elapsed"
}

trap 'emit_state interrupted; exit 130' INT TERM

while true; do
  now="$(date +%s)"
  elapsed=$((now - START_EPOCH))

  if (( elapsed >= LEASE_SECONDS )); then
    emit_state lease_expired
    exit 124
  fi

  remote_sha=""
  if output="$(git ls-remote --heads "$REMOTE" "refs/heads/$BRANCH" 2>/dev/null)"; then
    remote_sha="$(awk 'NR == 1 { print $1 }' <<<"$output")"

    if [[ -z "$remote_sha" ]]; then
      state="branch_missing"
    elif [[ "${remote_sha,,}" == "${BASE_SHA,,}" ]]; then
      state="waiting"
    else
      echo "event=handoff_candidate task_id=$TASK_ID branch=$BRANCH sha=$remote_sha elapsed_seconds=$elapsed"
      exit 0
    fi
  else
    state="remote_unreachable"
  fi

  if [[ "$state" != "$last_state" ]]; then
    emit_state "$state"
    last_state="$state"
  fi

  sleep "$POLL_SECONDS"
done
