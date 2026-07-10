#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: recover-capability.sh <task-id>" >&2
  exit 2
fi

TASK_ID=$1
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

sh "$SCRIPT_DIR/macos-watcher.sh" stop "$TASK_ID" >/dev/null 2>&1 || true
sh "$SCRIPT_DIR/transport-event.sh" clear "$TASK_ID" >/dev/null 2>&1 || true
sh "$SCRIPT_DIR/task-state.sh" transition \
  "$TASK_ID" CAPABILITY_CHECK \
  --event capability_reassessment \
  --force

echo "event=capability_recovery_ready task_id=$TASK_ID native_goal_unchanged=true"
