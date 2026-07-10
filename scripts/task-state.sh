#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ "$#" -ge 2 ] && [ "$1" != "create" ]; then
  python3 "$SCRIPT_DIR/migrate-task-state.py" "$2"
fi

exec python3 "$SCRIPT_DIR/task-state.py" "$@"
