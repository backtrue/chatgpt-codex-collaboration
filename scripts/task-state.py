#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATES = {
    "DISCOVERING", "READY", "DISPATCHING", "IMPLEMENTING", "WAITING_HANDOFF",
    "HANDOFF_CANDIDATE", "VERIFYING", "REPAIR_REQUIRED", "WAITING_REPAIR",
    "BLOCKED_GOAL", "BLOCKED_SPEC", "BLOCKED_CAPABILITY", "BLOCKED_DEPENDENCY",
    "BLOCKED_TRANSPORT", "BLOCKED_OBSERVATION", "BLOCKED_USER",
    "ACCEPTED", "FAILED", "CANCELLED",
}

ALLOWED = {
    "DISCOVERING": {
        "READY", "BLOCKED_GOAL", "BLOCKED_SPEC", "BLOCKED_CAPABILITY",
        "BLOCKED_DEPENDENCY", "CANCELLED"
    },
    "READY": {"DISPATCHING", "BLOCKED_GOAL", "BLOCKED_USER", "CANCELLED"},
    "DISPATCHING": {
        "IMPLEMENTING", "BLOCKED_GOAL", "BLOCKED_TRANSPORT", "FAILED", "CANCELLED"
    },
    "IMPLEMENTING": {
        "WAITING_HANDOFF", "BLOCKED_GOAL", "BLOCKED_TRANSPORT",
        "BLOCKED_OBSERVATION", "FAILED", "CANCELLED"
    },
    "WAITING_HANDOFF": {
        "HANDOFF_CANDIDATE", "BLOCKED_GOAL", "BLOCKED_TRANSPORT",
        "BLOCKED_OBSERVATION", "FAILED", "CANCELLED"
    },
    "HANDOFF_CANDIDATE": {
        "VERIFYING", "BLOCKED_GOAL", "BLOCKED_TRANSPORT", "FAILED", "CANCELLED"
    },
    "VERIFYING": {
        "ACCEPTED", "REPAIR_REQUIRED", "BLOCKED_GOAL", "BLOCKED_CAPABILITY",
        "BLOCKED_DEPENDENCY", "FAILED", "CANCELLED"
    },
    "REPAIR_REQUIRED": {
        "WAITING_REPAIR", "BLOCKED_GOAL", "BLOCKED_USER", "FAILED", "CANCELLED"
    },
    "WAITING_REPAIR": {
        "HANDOFF_CANDIDATE", "BLOCKED_GOAL", "BLOCKED_TRANSPORT",
        "BLOCKED_OBSERVATION", "FAILED", "CANCELLED"
    },
    "BLOCKED_GOAL": {"DISCOVERING", "READY", "VERIFYING", "CANCELLED"},
    "BLOCKED_SPEC": {"DISCOVERING", "READY", "CANCELLED"},
    "BLOCKED_CAPABILITY": {"DISCOVERING", "READY", "VERIFYING", "CANCELLED"},
    "BLOCKED_DEPENDENCY": {"DISCOVERING", "READY", "VERIFYING", "CANCELLED"},
    "BLOCKED_TRANSPORT": {
        "DISPATCHING", "WAITING_HANDOFF", "WAITING_REPAIR", "CANCELLED"
    },
    "BLOCKED_OBSERVATION": {"WAITING_HANDOFF", "WAITING_REPAIR", "CANCELLED"},
    "BLOCKED_USER": {"READY", "REPAIR_REQUIRED", "CANCELLED"},
    "ACCEPTED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
}

TASK_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
GOAL_STATUSES = {
    "active", "paused", "blocked", "usage_limited", "budget_limited", "complete"
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def state_root() -> Path:
    root = os.environ.get("COLLAB_STATE_ROOT", "~/.codex/collaboration/tasks")
    path = Path(root).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_path(task_id: str) -> Path:
    if not TASK_ID_RE.fullmatch(task_id):
        raise ValueError("invalid task id")
    return state_root() / f"{task_id}.json"


def read_state(task_id: str) -> dict[str, Any]:
    path = task_path(task_id)
    if not path.exists():
        raise FileNotFoundError(f"task state not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(data: dict[str, Any]) -> None:
    path = task_path(data["task_id"])
    temp = path.with_suffix(".json.tmp")
    data["updated_at"] = now()
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def create(args: argparse.Namespace) -> None:
    path = task_path(args.task_id)
    if path.exists() and not args.force:
        raise FileExistsError(f"task state already exists: {path}")
    if args.goal_status not in GOAL_STATUSES:
        raise ValueError(f"invalid goal status: {args.goal_status}")
    timestamp = now()
    data = {
        "schema_version": "1.1",
        "task_id": args.task_id,
        "goal": {
            "goal_id": args.goal_id,
            "objective": args.goal_objective,
            "status": args.goal_status,
            "token_budget": args.goal_token_budget,
            "created_by_skill": args.goal_created_by_skill,
            "bound_at": timestamp,
        },
        "state": "DISCOVERING",
        "attempt": 1,
        "repository": args.repository,
        "conversation_url": args.conversation_url,
        "branch": args.branch,
        "base_sha": args.base_sha,
        "candidate_sha": None,
        "accepted_sha": None,
        "dispatch_id": args.dispatch_id,
        "message_fingerprint": None,
        "dispatched_at": None,
        "observation": {
            "lease_seconds": args.lease_seconds,
            "poll_seconds": args.poll_seconds,
            "dispatch_epoch": None,
            "absolute_deadline_epoch": None,
            "last_observed_state": None,
        },
        "repair_count": 0,
        "last_error": None,
        "history": [
            {
                "from": None,
                "to": "DISCOVERING",
                "event": "created_and_bound_to_goal",
                "timestamp": timestamp,
            }
        ],
        "updated_at": timestamp,
    }
    write_state(data)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def transition(args: argparse.Namespace) -> None:
    data = read_state(args.task_id)
    current = data["state"]
    target = args.to
    if target not in STATES:
        raise ValueError(f"unknown state: {target}")
    if target not in ALLOWED[current] and not args.force:
        raise ValueError(f"invalid transition: {current} -> {target}")
    data["state"] = target
    data["history"].append(
        {"from": current, "to": target, "event": args.event, "timestamp": now()}
    )
    if args.error is not None:
        data["last_error"] = args.error
    write_state(data)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def set_field(args: argparse.Namespace) -> None:
    data = read_state(args.task_id)
    if args.field not in {
        "base_sha", "candidate_sha", "accepted_sha", "message_fingerprint",
        "dispatched_at", "last_error"
    }:
        raise ValueError("field is not mutable through this command")
    value: Any = None if args.value == "null" else args.value
    data[args.field] = value
    write_state(data)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def set_goal(args: argparse.Namespace) -> None:
    data = read_state(args.task_id)
    if args.status not in GOAL_STATUSES:
        raise ValueError(f"invalid goal status: {args.status}")
    previous_goal_id = data["goal"]["goal_id"]
    if previous_goal_id != args.goal_id and not args.allow_rebind:
        raise ValueError(
            f"goal rebind refused: {previous_goal_id} -> {args.goal_id}; "
            "use --allow-rebind only after an explicit user goal change"
        )
    data["goal"] = {
        "goal_id": args.goal_id,
        "objective": args.objective,
        "status": args.status,
        "token_budget": args.token_budget,
        "created_by_skill": args.created_by_skill,
        "bound_at": now(),
    }
    write_state(data)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def repair(args: argparse.Namespace) -> None:
    data = read_state(args.task_id)
    data["repair_count"] += 1
    data["attempt"] += 1
    data["base_sha"] = args.base_sha
    data["candidate_sha"] = None
    write_state(data)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def show(args: argparse.Namespace) -> None:
    print(json.dumps(read_state(args.task_id), ensure_ascii=False, indent=2))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Persist collaboration task state and bind it to a Codex thread goal"
    )
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("create")
    c.add_argument("task_id")
    c.add_argument("--repository", required=True)
    c.add_argument("--conversation-url", required=True)
    c.add_argument("--branch", required=True)
    c.add_argument("--base-sha")
    c.add_argument("--dispatch-id", required=True)
    c.add_argument("--goal-id", required=True)
    c.add_argument("--goal-objective", required=True)
    c.add_argument("--goal-status", default="active", choices=sorted(GOAL_STATUSES))
    c.add_argument("--goal-token-budget", type=int)
    c.add_argument("--goal-created-by-skill", action="store_true")
    c.add_argument("--lease-seconds", type=int, default=7200)
    c.add_argument("--poll-seconds", type=int, default=30)
    c.add_argument("--force", action="store_true")
    c.set_defaults(func=create)

    t = sub.add_parser("transition")
    t.add_argument("task_id")
    t.add_argument("to")
    t.add_argument("--event", required=True)
    t.add_argument("--error")
    t.add_argument("--force", action="store_true")
    t.set_defaults(func=transition)

    s = sub.add_parser("set")
    s.add_argument("task_id")
    s.add_argument("field")
    s.add_argument("value")
    s.set_defaults(func=set_field)

    g = sub.add_parser("set-goal")
    g.add_argument("task_id")
    g.add_argument("--goal-id", required=True)
    g.add_argument("--objective", required=True)
    g.add_argument("--status", required=True, choices=sorted(GOAL_STATUSES))
    g.add_argument("--token-budget", type=int)
    g.add_argument("--created-by-skill", action="store_true")
    g.add_argument("--allow-rebind", action="store_true")
    g.set_defaults(func=set_goal)

    r = sub.add_parser("repair")
    r.add_argument("task_id")
    r.add_argument("--base-sha", required=True)
    r.set_defaults(func=repair)

    sh = sub.add_parser("show")
    sh.add_argument("task_id")
    sh.set_defaults(func=show)
    return p


def main() -> int:
    try:
        args = parser().parse_args()
        args.func(args)
        return 0
    except Exception as exc:
        print(f"error={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
