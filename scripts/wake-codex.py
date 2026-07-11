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
    subprocess.run(
        [osascript, "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )


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


def event_type(line: str) -> str | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("type")
    return value if isinstance(value, str) else None


def terminate_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


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
            f"event=wake_duplicate_ignored task_id={args.task_id} "
            f"event_id={args.event_id}"
        )
        return 0

    log_root = Path(
        os.environ.get("COLLAB_LOG_ROOT", "~/.codex/collaboration/logs")
    ).expanduser()
    log_root.mkdir(parents=True, exist_ok=True)
    log_path = log_root / f"{args.task_id}.codex-resume.log"

    try:
        event_payload = json.loads(args.event_payload)
    except json.JSONDecodeError:
        event_payload = {"raw": args.event_payload}

    prompt = f"""Use the installed chatgpt-codex-collaboration skill and resume the existing collaboration task.

Task ID: {args.task_id}
Terminal event: {args.event_type}
Event ID: {args.event_id}
Candidate SHA: {args.candidate_sha or 'none'}
Event payload: {json.dumps(event_payload, ensure_ascii=False)}

This is the same persisted Codex thread and the same native goal. The goal is temporarily paused only to prevent token-consuming continuation turns during external work. The wake controller will reactivate it after this explicit resumed turn starts. Do not create, replace, clear, block, or manually resume the goal.

Read the existing task state, wake configuration, supervisor logs, transport events, remote branch, and authoritative specifications. If the event is handoff_candidate, validate the candidate and run independent acceptance. If the event is a transport or protocol failure, execute the documented recovery path. Do not redispatch blindly and do not report completion without evidence.
"""

    started = time.time()
    goal_reactivated = False
    returncode = 2
    proc: subprocess.Popen[str] | None = None

    try:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(
                json.dumps(
                    {
                        "event": "codex_resume_started",
                        "task_id": args.task_id,
                        "thread_id": args.thread_id,
                        "event_type": args.event_type,
                        "event_id": args.event_id,
                        "goal_status": "paused",
                        "started_at": started,
                    }
                )
                + "\n"
            )
            log.flush()

            proc = subprocess.Popen(
                [codex, "exec", "--json", "resume", args.thread_id, prompt],
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            if proc.stdout is None:
                raise RuntimeError("failed to capture codex exec output")

            for line in proc.stdout:
                log.write(line)
                log.flush()
                if not goal_reactivated and event_type(line) == "turn.started":
                    active = run_goal_control(
                        skill_root,
                        args.thread_id,
                        "active",
                        repo,
                        codex,
                    )
                    log.write(
                        json.dumps(
                            {
                                "event": "native_goal_reactivation",
                                "task_id": args.task_id,
                                "returncode": active.returncode,
                                "detail": (
                                    active.stdout.strip()
                                    if active.returncode == 0
                                    else (active.stderr or active.stdout).strip()
                                )[-2000:],
                            }
                        )
                        + "\n"
                    )
                    log.flush()
                    if active.returncode != 0:
                        terminate_process(proc)
                        raise RuntimeError("native goal reactivation failed")
                    goal_reactivated = True

            returncode = proc.wait()
            log.write(
                json.dumps(
                    {
                        "event": "codex_resume_finished",
                        "task_id": args.task_id,
                        "event_id": args.event_id,
                        "returncode": returncode,
                        "goal_reactivated": goal_reactivated,
                        "duration_seconds": round(time.time() - started, 3),
                    }
                )
                + "\n"
            )
            log.flush()

        if returncode != 0 or not goal_reactivated:
            if goal_reactivated:
                run_goal_control(
                    skill_root,
                    args.thread_id,
                    "paused",
                    repo,
                    codex,
                )
            remove_lock(lock_path)
            notify(
                "ChatGPT-Codex resume failed",
                f"Task {args.task_id} remains paused. Check {log_path} and retry.",
            )
            print(
                f"error=codex_exec_resume_failed returncode={returncode} "
                f"turn_started={str(goal_reactivated).lower()} log={log_path}",
                file=sys.stderr,
            )
            return returncode or 2

        print(
            f"event=codex_session_resumed task_id={args.task_id} "
            f"thread_id={args.thread_id} event_id={args.event_id} log={log_path}"
        )
        return 0
    except Exception as exc:
        if proc is not None:
            terminate_process(proc)
        if goal_reactivated:
            run_goal_control(
                skill_root,
                args.thread_id,
                "paused",
                repo,
                codex,
            )
        remove_lock(lock_path)
        notify(
            "ChatGPT-Codex resume failed",
            f"Task {args.task_id} remains paused. Check {log_path} and retry.",
        )
        print(f"error={exc} log={log_path}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
