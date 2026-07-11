#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
: "${BROWSER_USE_BIN:=browser-use}"
if ! command -v "$BROWSER_USE_BIN" >/dev/null 2>&1; then
  echo "error=browser_use_not_found" >&2
  exit 2
fi
exec "$BROWSER_USE_BIN" < "$SCRIPT_DIR/browser-use-transport.py"
