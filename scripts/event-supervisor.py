#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

TASK_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
TRANSPORT_TERMINAL_EVENTS = {
    "implementation_blocked",
    "capability_rejected",
    "conversation_completed_no_commit",
    "conversation_failed",
    "transport_unreachable",
    "mode_drifted",
}
stop_requested = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_epoch(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return None


def handle_signal(_signum: int, _frame: object) -> None:
    global stop_requested
    stop_requested = True


def emit(event: str, **fields: object) -> None:
    parts = [f"event={event}"]
    parts.extend(f"{key}={value}" for key, value in fields.items())
    print(" ".join(parts), flush=True)


def remote_head(repo: Path, remote: str, branch: str) -> tuple[str, str | None, str]:
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", remote, f"refs/heads/{branch}"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "remote_unreachable", None, str(exc)
    if result.returncode != 0:
        return "remote_unreachable", None, result.stderr.strip()
    line = next((line for line in result.stdout.splitlines() if line.strip()), "")
    if not line:
        return "branch_missing", None, ""
    return "ok", line.split()[0], ""


def transport_event(
    line: str,
) -> tuple[str | None, str, dict[str, object], float | None]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None, "", {}, None
    if not isinstance(event, dict):
        return None, "", {}, None
    event_type = event.get("event_type")
    event_id = event.get("event_id")
    payload = event.get("payload")
    return (
        event_type if isinstance(event_type, str) else None,
        event_id if isinstance(event_id, str) else str(uuid.uuid4()),
        payload if isinstance(payload, dict) else {},
        parse_epoch(event.get("timestamp")),
    )


def launch_wake(
    skill_root: Path,
    task_id: str,
    thread_id: str,
    event_type: str,
    event_id: str,
    repo: Path,
    candidate_sha: str | None,
    payload: dict[str, object],
    codex: str | None,
) -> int:
    command = [
        sys.executable,
        str(skill_root / "scripts" / "wake-codex.py"),
        task_id,
        thread_id,
        event_type,
        event_id,
        "--repo",
        str(repo),
        "--skill-root",
        str(skill_root),
        "--event-payload",
        json.dumps(payload, ensure_ascii=False),
    ]
    if candidate_sha:
        command.extend(["--candidate-sha", candidate_sha])
    if codex:
        command.extend(["--codex", codex])

    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        emit(
            "wake_launch_failed",
            task_id=task_id,
            event_id=event_id,
            detail=json.dumps(str(exc)),
        )
        return 2

    emit(
        "wake_launched",
        task_id=task_id,
        event_type=event_type,
        event_id=event_id,
        pid=proc.pid,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Watch Git and transport events, then resume the same Codex thread"
    )
    parser.add_argument("task_id")
    parser.add_argument("branch")
    parser.add_argument("base_sha")
    parser.add_argument("thread_id")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--skill-root", required=True)
    parser.add_argument("--transport-events", required=True)
    parser.add_argument("--lease-seconds", type=int, default=7200)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--max-poll-seconds", type=int, default=300)
    parser.add_argument("--backoff-after", type=int, default=5)
    parser.add_argument("--dispatch-epoch", type=int, default=int(time.time()))
    parser.add_argument("--codex")
    args = parser.parse_args()

    if not TASK_RE.fullmatch(args.task_id):
        print("error=invalid_task_id", file=sys.stderr)
        return 2
    if not SHA_RE.fullmatch(args.base_sha):
        print("error=invalid_base_sha", file=sys.stderr)
        return 2
    if args.poll_seconds < 1 or args.max_poll_seconds < args.poll_seconds:
        print("error=invalid_poll_timing", file=sys.stderr)
        return 2

    repo = Path(args.repo).expanduser().resolve()
    skill_root = Path(args.skill_root).expanduser().resolve()
    transport_path = Path(args.transport_events).expanduser().resolve()
    transport_offset = 0
    current_poll = args.poll_seconds
    unchanged = 0
    last_state: str | None = None

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    emit(
        "supervisor_started",
        task_id=args.task_id,
        thread_id=args.thread_id,
        branch=args.branch,
        base_sha=args.base_sha,
        dispatch_epoch=args.dispatch_epoch,
        started_at=now_iso(),
    )

    while not stop_requested:
        elapsed = int(time.time()) - args.dispatch_epoch
        if elapsed >= args.lease_seconds:
            event_id = f"lease-{args.dispatch_epoch}-{args.lease_seconds}"
            return launch_wake(
                skill_root,
                args.task_id,
                args.thread_id,
                "observation_lease_expired",
                event_id,
                repo,
                None,
                {"elapsed_seconds": elapsed},
                args.codex,
            )

        if transport_path.exists():
            with transport_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(transport_offset)
                for line in handle:
                    event_type, event_id, payload, event_epoch = transport_event(line)
                    if event_epoch is not None and event_epoch < args.dispatch_epoch:
                        continue
                    if event_type in TRANSPORT_TERMINAL_EVENTS:
                        emit(
                            "transport_terminal",
                            task_id=args.task_id,
                            event_type=event_type,
                            event_id=event_id,
                            event_epoch=event_epoch,
                        )
                        return launch_wake(
                            skill_root,
                            args.task_id,
                            args.thread_id,
                            event_type,
                            event_id,
                            repo,
                            None,
                            payload,
                            args.codex,
                        )
                transport_offset = handle.tell()

        state, head, detail = remote_head(repo, args.remote, args.branch)
        if state == "ok" and head is not None:
            if head.lower() != args.base_sha.lower():
                event_id = f"commit-{head.lower()}"
                emit(
                    "handoff_candidate",
                    task_id=args.task_id,
                    branch=args.branch,
                    sha=head,
                )
                return launch_wake(
                    skill_root,
                    args.task_id,
                    args.thread_id,
                    "handoff_candidate",
                    event_id,
                    repo,
                    head,
                    {"branch": args.branch, "base_sha": args.base_sha},
                    args.codex,
                )
            state = "waiting"

        if state != last_state:
            emit(
                state,
                task_id=args.task_id,
                branch=args.branch,
                detail=json.dumps(detail, ensure_ascii=False),
                next_poll_seconds=current_poll,
            )
            last_state = state
            unchanged = 0
            current_poll = args.poll_seconds
        else:
            unchanged += 1
            if unchanged >= args.backoff_after:
                current_poll = min(
                    args.max_poll_seconds,
                    max(current_poll + 1, int(current_poll * 1.5)),
                )
                unchanged = 0

        time.sleep(current_poll)

    emit("supervisor_interrupted", task_id=args.task_id)
    return 130


if __name__ == "__main__":
    raise SystemExit(main())
