#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

TASK_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def state_path(task_id: str) -> Path:
    if not TASK_RE.fullmatch(task_id):
        raise ValueError("invalid task id")
    root = Path(
        os.environ.get("COLLAB_STATE_ROOT", "~/.codex/collaboration/tasks")
    ).expanduser()
    return root / f"{task_id}.json"


def unassessed_executor() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "status": "blocked",
        "executor_profile": "none",
        "repository_read": False,
        "repository_write": False,
        "local_checkout": False,
        "shell": False,
        "git_commit": False,
        "git_push": False,
        "external_network": False,
        "can_run_acceptance": False,
        "blocker_code": "UNASSESSED",
        "blocker_detail": "Capability handshake has not run.",
        "observed_at": now(),
    }


def migrate(task_id: str) -> int:
    path = state_path(task_id)
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    if data.get("schema_version") != "2.0":
        data["schema_version"] = "2.0"
        changed = True
    if "executor" not in data:
        data["executor"] = unassessed_executor()
        changed = True
    if not changed:
        return 0
    data["updated_at"] = now()
    temp = path.with_suffix(".json.migrate.tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)
    print(f"event=task_state_migrated task_id={task_id} schema_version=2.0")
    return 0


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise ValueError("usage: migrate-task-state.py <task-id>")
        return migrate(sys.argv[1])
    except Exception as exc:
        print(f"error={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
