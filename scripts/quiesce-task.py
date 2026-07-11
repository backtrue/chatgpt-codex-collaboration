#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

QUIESCENT_STATES = {
    "BLOCKED_GOAL",
    "BLOCKED_SPEC",
    "BLOCKED_CAPABILITY",
    "BLOCKED_DEPENDENCY",
    "BLOCKED_TRANSPORT",
    "BLOCKED_OBSERVATION",
    "BLOCKED_USER",
    "FAILED",
    "CANCELLED",
    "DISPATCHING",
    "IMPLEMENTING",
    "WAITING_HANDOFF",
    "WAITING_REPAIR",
}


def safe_task_id(task_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", task_id):
        raise ValueError("invalid task id")
    return task_id


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def run(*args: str, cwd: Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stop a collaboration supervisor and pause the same native goal"
    )
    parser.add_argument("task_id")
    parser.add_argument("--thread-id")
    parser.add_argument("--repo")
    parser.add_argument("--codex")
    parser.add_argument("--reason", default="stable_task_blocker")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        task_id = safe_task_id(args.task_id)
        skill_root = Path(__file__).resolve().parent.parent
        state_root = Path(
            os.environ.get("COLLAB_STATE_ROOT", "~/.codex/collaboration/tasks")
        ).expanduser()
        wake_root = Path(
            os.environ.get("COLLAB_WAKE_ROOT", "~/.codex/collaboration/wakes")
        ).expanduser()
        wake_root.mkdir(parents=True, exist_ok=True)

        task_state = load_json(state_root / f"{task_id}.json")
        task_status = str(task_state.get("state") or "unknown")
        if task_status not in QUIESCENT_STATES and not args.force:
            raise ValueError(
                f"task state is not quiescent: {task_status}; use --force only after review"
            )

        wake_config_path = wake_root / f"{task_id}.json"
        wake_config = load_json(wake_config_path)

        thread_id = (
            args.thread_id
            or str(wake_config.get("thread_id") or "")
            or os.environ.get("CODEX_THREAD_ID")
        )
        if not thread_id:
            raise ValueError("missing Codex thread id")

        repo_value = args.repo or str(wake_config.get("repo") or "") or os.getcwd()
        repo = Path(repo_value).expanduser().resolve()
        if not repo.is_dir():
            raise ValueError(f"repository path does not exist: {repo}")

        codex_value = args.codex or str(wake_config.get("codex") or "") or shutil.which("codex")
        if not codex_value:
            raise ValueError("codex executable not found")
        codex = str(Path(codex_value).expanduser().resolve())

        stopped = run(
            "sh",
            str(skill_root / "scripts" / "macos-watcher.sh"),
            "stop",
            task_id,
            "--keep-config",
            cwd=repo,
        )
        if stopped.returncode != 0:
            raise RuntimeError(
                f"failed to stop supervisor: {(stopped.stderr or stopped.stdout).strip()}"
            )

        paused = run(
            "sh",
            str(skill_root / "scripts" / "codex-goal-control.sh"),
            "set",
            thread_id,
            "paused",
            "--cwd",
            str(repo),
            "--codex",
            codex,
            cwd=repo,
            timeout=40,
        )
        if paused.returncode != 0:
            raise RuntimeError(
                f"failed to pause native goal: {(paused.stderr or paused.stdout).strip()}"
            )

        marker = wake_root / f"{task_id}.quiescent.json"
        temp = marker.with_suffix(".tmp")
        temp.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "task_id": task_id,
                    "task_state": task_status,
                    "thread_id": thread_id,
                    "goal_status": "paused",
                    "reason": args.reason,
                    "created_at": now(),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temp, marker)

        print(
            f"event=task_quiesced task_id={task_id} state={task_status} "
            f"thread_id={thread_id} goal_status=paused marker={marker}"
        )
        return 0
    except Exception as exc:
        print(f"error={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
