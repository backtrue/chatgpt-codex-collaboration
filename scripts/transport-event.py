#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import uuid

TASK_RE = re.compile(r"^[A-Za-z0-9._-]+$")
EVENT_TYPES = {
    "capability_ready",
    "capability_rejected",
    "conversation_completed",
    "conversation_completed_no_commit",
    "conversation_failed",
    "implementation_blocked",
    "mode_drifted",
    "transport_unreachable",
}
SOURCES = {"codex", "chatgpt-ui", "user", "watcher"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def event_root() -> Path:
    root = Path(
        os.environ.get("COLLAB_EVENT_ROOT", "~/.codex/collaboration/events")
    ).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def event_path(task_id: str) -> Path:
    if not TASK_RE.fullmatch(task_id):
        raise ValueError("invalid task id")
    return event_root() / f"{task_id}.jsonl"


def append_event(args: argparse.Namespace) -> int:
    if args.event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported event type: {args.event_type}")
    if args.source not in SOURCES:
        raise ValueError(f"unsupported source: {args.source}")

    payload: dict[str, object] = {}
    if args.payload_json:
        loaded = json.loads(args.payload_json)
        if not isinstance(loaded, dict):
            raise ValueError("payload JSON must be an object")
        payload.update(loaded)
    if args.code:
        payload["code"] = args.code
    if args.reason:
        payload["reason"] = args.reason
    if args.commit_sha:
        payload["commit_sha"] = args.commit_sha

    event = {
        "schema_version": "2.0",
        "event_id": str(uuid.uuid4()),
        "task_id": args.task_id,
        "event_type": args.event_type,
        "source": args.source,
        "timestamp": now(),
        "payload": payload,
    }
    path = event_path(args.task_id)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    print(json.dumps(event, ensure_ascii=False, indent=2))
    return 0


def clear_events(args: argparse.Namespace) -> int:
    path = event_path(args.task_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    print(f"event=transport_events_cleared task_id={args.task_id}")
    return 0


def show_events(args: argparse.Namespace) -> int:
    path = event_path(args.task_id)
    if not path.exists():
        return 0
    print(path.read_text(encoding="utf-8"), end="")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Write local collaboration transport events")
    sub = root.add_subparsers(dest="command", required=True)

    emit = sub.add_parser("emit")
    emit.add_argument("task_id")
    emit.add_argument("event_type", choices=sorted(EVENT_TYPES))
    emit.add_argument("--source", default="chatgpt-ui", choices=sorted(SOURCES))
    emit.add_argument("--code")
    emit.add_argument("--reason")
    emit.add_argument("--commit-sha")
    emit.add_argument("--payload-json")
    emit.set_defaults(func=append_event)

    clear = sub.add_parser("clear")
    clear.add_argument("task_id")
    clear.set_defaults(func=clear_events)

    show = sub.add_parser("show")
    show.add_argument("task_id")
    show.set_defaults(func=show_events)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        return args.func(args)
    except Exception as exc:
        print(f"error={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
