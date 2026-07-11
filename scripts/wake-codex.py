#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def notify(title: str, message: str) -> None:
    osascript = shutil.which("osascript")
    if not osascript:
        return
    script = (
        "display notification "
        + json.dumps(message)
        + " with title "
        + json.dumps(title)
    )
    subprocess.run([osascript, "-e", script], capture_output=True, text=True, check=False)


def run_goal_control(
    skill_root: Path,
    thread_id: str,
    status: str,
    repo: Path,
    codex: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "sh",
            str(skill_root / "scripts" / "codex-goal-control.sh"),
            "set",
            thread_id,
            status,
            "--cwd",
            str(repo),
            "--codex",
            codex,
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=40,
    )


def remove_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resume the same Codex session after a collaboration event"
    )
    parser.add_argument("task_id")
    parser.add_argument("thread_id")
    parser.add_argument("event_type")
    parser.add_argument("event_id")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--skill-root", required=True)
    parser.add_argument("--candidate-sha")
    parser.add_argument("--event-payload", default="{}")
    parser.add_argument("--codex")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    skill_root = Path(args.skill_root).expanduser().resolve()
    codex = args.codex or shutil.which("codex")
    if not codex:
        print("error=codex_not_found", file=sys.stderr)
        notify("ChatGPT-Codex handoff", "Codex CLI not found; resume manually.")
        return 2
    codex = str(Path(codex).expanduser().resolve())

    wake_root = Path(
        os.environ.get("COLLAB_WAKE_ROOT", "~/.codex/collaboration/wakes")
    ).expanduser()
    wake_root.mkdir(parents=True, exist_ok=True)
    safe_event = "".join(
        ch if ch.isalnum() or ch in "._-" else "-" for ch in args.event_id
    )
    lock_path = wake_root / f"{args.task_id}.{safe_event}.lock"
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    except FileExistsError:
        print(
            f"event=wake_duplicate_ignored task_id={args.task_id} event_id={args.event_id}"
        )
        return 0

    log_root = Path(
        os.environ.get("COLLAB_LOG_ROOT", "~/.codex/collaboration/logs")
    ).expanduser()
    log_root.mkdir(parents=True, exist_ok=True)
    log_path = log_root / f"{args.task_id}.codex-resume.log"

    active = run_goal_control(skill_root, args.thread_id, "active", repo, codex)
    if active.returncode != 0:
        remove_lock(lock_path)
        detail = (active.stderr or active.stdout).strip()[-2000:]
        print(f"error=goal_resume_failed detail={detail}", file=sys.stderr)
        notify(
            "ChatGPT-Codex handoff ready",
            f"Could not reactivate Codex goal for {args.task_id}; resume manually.",
        )
        return 2

    try:
        payload = json.loads(args.event_payload)
    except json.JSONDecodeError:
        payload = {"raw": args.event_payload}

    prompt = f"""Use the installed chatgpt-codex-collaboration skill and resume the existing collaboration task.

Task ID: {args.task_id}
Terminal event: {args.event_type}
Event ID: {args.event_id}
Candidate SHA: {args.candidate_sha or 'none'}
Event payload: {json.dumps(payload, ensure_ascii=False)}

This is the same persisted Codex thread and the same native goal. The goal was temporarily paused only to avoid token-consuming continuation turns during the external wait. Do not create, replace, clear, block, or pause the goal unless the current skill explicitly requires a new external wait.

Read the existing task state, watcher logs, transport events, and authoritative specs. If the event is handoff_candidate, validate the remote branch and candidate SHA, then run independent Codex acceptance. If the event is a transport or capability terminal event, execute the documented recovery path. Do not redispatch blindly and do not report completion without evidence.
"""

    started = time.time()
    with log_path.open("a", encoding="utf-8") as log:
        log.write(
            json.dumps(
                {
                    "event": "codex_resume_started",
                    "task_id": args.task_id,
                    "thread_id": args.thread_id,
                    "event_type": args.event_type,
                    "event_id": args.event_id,
                    "started_at": started,
                }
            )
            + "\n"
        )
        log.flush()
        result = subprocess.run(
            [codex, "exec", "--json", "resume", args.thread_id, prompt],
            cwd=repo,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        log.write(
            json.dumps(
                {
                    "event": "codex_resume_finished",
                    "task_id": args.task_id,
                    "event_id": args.event_id,
                    "returncode": result.returncode,
                    "duration_seconds": round(time.time() - started, 3),
                }
            )
            + "\n"
        )

    if result.returncode != 0:
        run_goal_control(skill_root, args.thread_id, "paused", repo, codex)
        remove_lock(lock_path)
        notify(
            "ChatGPT-Codex resume failed",
            f"Task {args.task_id} is paused. Check {log_path} and resume manually.",
        )
        print(
            f"error=codex_exec_resume_failed returncode={result.returncode} log={log_path}",
            file=sys.stderr,
        )
        return result.returncode or 2

    print(
        f"event=codex_session_resumed task_id={args.task_id} "
        f"thread_id={args.thread_id} event_id={args.event_id} log={log_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
