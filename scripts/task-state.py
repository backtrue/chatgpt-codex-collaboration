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
    "DISCOVERING",
    "CAPABILITY_CHECK",
    "READY",
    "DISPATCHING",
    "IMPLEMENTING",
    "WAITING_HANDOFF",
    "HANDOFF_CANDIDATE",
    "VERIFYING",
    "REPAIR_REQUIRED",
    "WAITING_REPAIR",
    "BLOCKED_GOAL",
    "BLOCKED_SPEC",
    "BLOCKED_CAPABILITY",
    "BLOCKED_DEPENDENCY",
    "BLOCKED_TRANSPORT",
    "BLOCKED_OBSERVATION",
    "BLOCKED_USER",
    "ACCEPTED",
    "FAILED",
    "CANCELLED",
}

ALLOWED = {
    "DISCOVERING": {
        "CAPABILITY_CHECK",
        "BLOCKED_GOAL",
        "BLOCKED_SPEC",
        "BLOCKED_DEPENDENCY",
        "CANCELLED",
    },
    "CAPABILITY_CHECK": {
        "READY",
        "BLOCKED_CAPABILITY",
        "BLOCKED_TRANSPORT",
        "CANCELLED",
    },
    "READY": {"DISPATCHING", "BLOCKED_GOAL", "BLOCKED_USER", "CANCELLED"},
    "DISPATCHING": {
        "IMPLEMENTING",
        "BLOCKED_GOAL",
        "BLOCKED_CAPABILITY",
        "BLOCKED_TRANSPORT",
        "FAILED",
        "CANCELLED",
    },
    "IMPLEMENTING": {
        "WAITING_HANDOFF",
        "BLOCKED_GOAL",
        "BLOCKED_CAPABILITY",
        "BLOCKED_TRANSPORT",
        "BLOCKED_OBSERVATION",
        "FAILED",
        "CANCELLED",
    },
    "WAITING_HANDOFF": {
        "HANDOFF_CANDIDATE",
        "BLOCKED_GOAL",
        "BLOCKED_CAPABILITY",
        "BLOCKED_TRANSPORT",
        "BLOCKED_OBSERVATION",
        "FAILED",
        "CANCELLED",
    },
    "HANDOFF_CANDIDATE": {
        "VERIFYING",
        "BLOCKED_GOAL",
        "BLOCKED_TRANSPORT",
        "FAILED",
        "CANCELLED",
    },
    "VERIFYING": {
        "ACCEPTED",
        "REPAIR_REQUIRED",
        "BLOCKED_GOAL",
        "BLOCKED_CAPABILITY",
        "BLOCKED_DEPENDENCY",
        "FAILED",
        "CANCELLED",
    },
    "REPAIR_REQUIRED": {
        "WAITING_REPAIR",
        "BLOCKED_GOAL",
        "BLOCKED_CAPABILITY",
        "BLOCKED_USER",
        "FAILED",
        "CANCELLED",
    },
    "WAITING_REPAIR": {
        "HANDOFF_CANDIDATE",
        "BLOCKED_GOAL",
        "BLOCKED_CAPABILITY",
        "BLOCKED_TRANSPORT",
        "BLOCKED_OBSERVATION",
        "FAILED",
        "CANCELLED",
    },
    "BLOCKED_GOAL": {"DISCOVERING", "CAPABILITY_CHECK", "READY", "VERIFYING", "CANCELLED"},
    "BLOCKED_SPEC": {"DISCOVERING", "CAPABILITY_CHECK", "READY", "CANCELLED"},
    "BLOCKED_CAPABILITY": {"CAPABILITY_CHECK", "READY", "VERIFYING", "CANCELLED"},
    "BLOCKED_DEPENDENCY": {"DISCOVERING", "READY", "VERIFYING", "CANCELLED"},
    "BLOCKED_TRANSPORT": {
        "CAPABILITY_CHECK",
        "DISPATCHING",
        "WAITING_HANDOFF",
        "WAITING_REPAIR",
        "CANCELLED",
    },
    "BLOCKED_OBSERVATION": {"WAITING_HANDOFF", "WAITING_REPAIR", "CANCELLED"},
    "BLOCKED_USER": {"READY", "REPAIR_REQUIRED", "CANCELLED"},
    "ACCEPTED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
}

TASK_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
GOAL_STATUSES = {
    "active",
    "paused",
    "blocked",
    "usage_limited",
    "budget_limited",
    "complete",
}
EXECUTOR_PROFILES = {"local_full", "github_connector", "read_only", "none"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def state_root() -> Path:
    root = Path(
        os.environ.get("COLLAB_STATE_ROOT", "~/.codex/collaboration/tasks")
    ).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


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


def unassessed_executor() -> dict[str, Any]:
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


def validate_executor(data: dict[str, Any]) -> dict[str, Any]:
    required = {
        "status",
        "executor_profile",
        "repository_read",
        "repository_write",
        "local_checkout",
        "shell",
        "git_commit",
        "git_push",
        "external_network",
        "can_run_acceptance",
    }
    missing = sorted(required.difference(data))
    if missing:
        raise ValueError(f"executor handshake missing fields: {', '.join(missing)}")
    profile = data["executor_profile"]
    if profile not in EXECUTOR_PROFILES:
        raise ValueError(f"invalid executor profile: {profile}")
    if data["status"] not in {"ready", "blocked"}:
        raise ValueError("executor status must be ready or blocked")
    for field in required.difference({"status", "executor_profile"}):
        if not isinstance(data[field], bool):
            raise ValueError(f"executor field must be boolean: {field}")

    if profile == "local_full":
        must_be_true = {
            "repository_read",
            "repository_write",
            "local_checkout",
            "shell",
            "git_commit",
            "git_push",
            "can_run_acceptance",
        }
        if data["status"] != "ready" or any(not data[field] for field in must_be_true):
            raise ValueError("local_full profile does not satisfy required capabilities")
    elif profile == "github_connector":
        must_be_true = {"repository_read", "repository_write", "git_commit", "git_push"}
        if data["status"] != "ready" or any(not data[field] for field in must_be_true):
            raise ValueError("github_connector profile does not satisfy required capabilities")
        if data["can_run_acceptance"]:
            raise ValueError("github_connector must defer acceptance to Codex")
    elif data["status"] != "blocked":
        raise ValueError("read_only and none profiles must be blocked")

    return {
        "schema_version": "2.0",
        "status": data["status"],
        "executor_profile": profile,
        "repository_read": data["repository_read"],
        "repository_write": data["repository_write"],
        "local_checkout": data["local_checkout"],
        "shell": data["shell"],
        "git_commit": data["git_commit"],
        "git_push": data["git_push"],
        "external_network": data["external_network"],
        "can_run_acceptance": data["can_run_acceptance"],
        "blocker_code": data.get("blocker_code"),
        "blocker_detail": data.get("blocker_detail"),
        "observed_at": data.get("observed_at") or now(),
    }


def create(args: argparse.Namespace) -> None:
    path = task_path(args.task_id)
    if path.exists() and not args.force:
        raise FileExistsError(f"task state already exists: {path}")
    if args.goal_status not in GOAL_STATUSES:
        raise ValueError(f"invalid goal status: {args.goal_status}")
    timestamp = now()
    data = {
        "schema_version": "2.0",
        "task_id": args.task_id,
        "goal": {
            "goal_id": args.goal_id,
            "objective": args.goal_objective,
            "status": args.goal_status,
            "token_budget": args.goal_token_budget,
            "created_by_skill": args.goal_created_by_skill,
            "bound_at": timestamp,
        },
        "executor": unassessed_executor(),
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
        "base_sha",
        "candidate_sha",
        "accepted_sha",
        "message_fingerprint",
        "dispatched_at",
        "last_error",
    }:
        raise ValueError("field is not mutable through this command")
    data[args.field] = None if args.value == "null" else args.value
    write_state(data)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def set_goal(args: argparse.Namespace) -> None:
    data = read_state(args.task_id)
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


def set_executor(args: argparse.Namespace) -> None:
    data = read_state(args.task_id)
    if args.file:
        handshake = json.loads(Path(args.file).expanduser().read_text(encoding="utf-8"))
    else:
        handshake = json.loads(args.json)
    if not isinstance(handshake, dict):
        raise ValueError("executor handshake must be a JSON object")
    data["executor"] = validate_executor(handshake)
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
    root = argparse.ArgumentParser(
        description="Persist collaboration task, goal, and executor state"
    )
    sub = root.add_subparsers(dest="command", required=True)

    create_parser = sub.add_parser("create")
    create_parser.add_argument("task_id")
    create_parser.add_argument("--repository", required=True)
    create_parser.add_argument("--conversation-url", required=True)
    create_parser.add_argument("--branch", required=True)
    create_parser.add_argument("--base-sha")
    create_parser.add_argument("--dispatch-id", required=True)
    create_parser.add_argument("--goal-id", required=True)
    create_parser.add_argument("--goal-objective", required=True)
    create_parser.add_argument("--goal-status", default="active", choices=sorted(GOAL_STATUSES))
    create_parser.add_argument("--goal-token-budget", type=int)
    create_parser.add_argument("--goal-created-by-skill", action="store_true")
    create_parser.add_argument("--lease-seconds", type=int, default=7200)
    create_parser.add_argument("--poll-seconds", type=int, default=60)
    create_parser.add_argument("--force", action="store_true")
    create_parser.set_defaults(func=create)

    transition_parser = sub.add_parser("transition")
    transition_parser.add_argument("task_id")
    transition_parser.add_argument("to")
    transition_parser.add_argument("--event", required=True)
    transition_parser.add_argument("--error")
    transition_parser.add_argument("--force", action="store_true")
    transition_parser.set_defaults(func=transition)

    set_parser = sub.add_parser("set")
    set_parser.add_argument("task_id")
    set_parser.add_argument("field")
    set_parser.add_argument("value")
    set_parser.set_defaults(func=set_field)

    goal_parser = sub.add_parser("set-goal")
    goal_parser.add_argument("task_id")
    goal_parser.add_argument("--goal-id", required=True)
    goal_parser.add_argument("--objective", required=True)
    goal_parser.add_argument("--status", required=True, choices=sorted(GOAL_STATUSES))
    goal_parser.add_argument("--token-budget", type=int)
    goal_parser.add_argument("--created-by-skill", action="store_true")
    goal_parser.add_argument("--allow-rebind", action="store_true")
    goal_parser.set_defaults(func=set_goal)

    executor_parser = sub.add_parser("set-executor")
    executor_parser.add_argument("task_id")
    source = executor_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--json")
    source.add_argument("--file")
    executor_parser.set_defaults(func=set_executor)

    repair_parser = sub.add_parser("repair")
    repair_parser.add_argument("task_id")
    repair_parser.add_argument("--base-sha", required=True)
    repair_parser.set_defaults(func=repair)

    show_parser = sub.add_parser("show")
    show_parser.add_argument("task_id")
    show_parser.set_defaults(func=show)
    return root


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
