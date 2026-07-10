#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import time

TASK_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
stop_requested = False


def emit(event: str, task_id: str, branch: str, start_epoch: int, **extra: object) -> None:
    elapsed = max(0, int(time.time()) - start_epoch)
    fields = [f"event={event}", f"task_id={task_id}", f"branch={branch}", f"elapsed_seconds={elapsed}"]
    fields.extend(f"{key}={value}" for key, value in extra.items())
    print(" ".join(fields), flush=True)


def handle_signal(_signum: int, _frame: object) -> None:
    global stop_requested
    stop_requested = True


def remote_head(remote: str, branch: str) -> tuple[str, str | None]:
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", remote, f"refs/heads/{branch}"],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "remote_unreachable", None
    if result.returncode != 0:
        return "remote_unreachable", None
    line = next((line for line in result.stdout.splitlines() if line.strip()), "")
    if not line:
        return "branch_missing", None
    return "ok", line.split()[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Wait for a GitHub handoff commit without invoking an LLM")
    parser.add_argument("task_id")
    parser.add_argument("branch")
    parser.add_argument("base_sha")
    parser.add_argument("lease_seconds", nargs="?", type=int, default=7200)
    parser.add_argument("poll_seconds", nargs="?", type=int, default=30)
    parser.add_argument("--remote", default=os.environ.get("REMOTE", "origin"))
    parser.add_argument("--dispatch-epoch", type=int, default=int(os.environ.get("DISPATCH_EPOCH", time.time())))
    args = parser.parse_args()

    if not TASK_RE.fullmatch(args.task_id):
        print("error=invalid_task_id", file=sys.stderr)
        return 2
    if not SHA_RE.fullmatch(args.base_sha):
        print("error=invalid_base_sha", file=sys.stderr)
        return 2
    if args.lease_seconds < 1 or args.poll_seconds < 1:
        print("error=invalid_timing", file=sys.stderr)
        return 2
    if subprocess.run(["git", "check-ref-format", "--branch", args.branch], capture_output=True).returncode != 0:
        print(f"error=invalid_branch branch={args.branch}", file=sys.stderr)
        return 2
    if subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True).returncode != 0:
        print("error=not_a_git_worktree", file=sys.stderr)
        return 2
    if subprocess.run(["git", "remote", "get-url", args.remote], capture_output=True).returncode != 0:
        print(f"error=missing_remote remote={args.remote}", file=sys.stderr)
        return 2

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    last_state: str | None = None

    while not stop_requested:
        elapsed = int(time.time()) - args.dispatch_epoch
        if elapsed >= args.lease_seconds:
            emit("lease_expired", args.task_id, args.branch, args.dispatch_epoch)
            return 124

        state, head = remote_head(args.remote, args.branch)
        if state == "ok" and head is not None:
            if head.lower() != args.base_sha.lower():
                emit("handoff_candidate", args.task_id, args.branch, args.dispatch_epoch, sha=head)
                return 0
            state = "waiting"

        if state != last_state:
            emit(state, args.task_id, args.branch, args.dispatch_epoch)
            last_state = state
        time.sleep(args.poll_seconds)

    emit("interrupted", args.task_id, args.branch, args.dispatch_epoch)
    return 130


if __name__ == "__main__":
    raise SystemExit(main())
