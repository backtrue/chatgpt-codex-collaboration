#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

QUIESCENT_TASK_STATES = {
    "BLOCKED_GOAL",
    "BLOCKED_SPEC",
    "BLOCKED_CAPABILITY",
    "BLOCKED_DEPENDENCY",
    "BLOCKED_TRANSPORT",
    "BLOCKED_OBSERVATION",
    "BLOCKED_USER",
    "FAILED",
    "CANCELLED",
}
ORPHANED_ASYNC_STATES = {
    "DISPATCHING",
    "IMPLEMENTING",
    "WAITING_HANDOFF",
    "WAITING_REPAIR",
}


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


def safe_task_id(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", task_id)


def launch_paths(task_id: str) -> tuple[str, Path, Path]:
    safe = safe_task_id(task_id)
    label = f"com.backtrue.chatgpt-codex.{safe}"
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    config = Path(
        os.environ.get("COLLAB_WAKE_ROOT", "~/.codex/collaboration/wakes")
    ).expanduser() / f"{safe}.json"
    return label, plist, config


def cleanup_generation(task_id: str, generation_id: str) -> bool:
    label, plist, config_path = launch_paths(task_id)
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        if config.get("generation_id") != generation_id:
            return False
    elif plist.exists():
        return False

    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{label}"],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        plist.unlink()
    except FileNotFoundError:
        pass
    try:
        config_path.unlink()
    except FileNotFoundError:
        pass
    return True


def task_state_path(task_id: str) -> Path:
    root = Path(
        os.environ.get("COLLAB_STATE_ROOT", "~/.codex/collaboration/tasks")
    ).expanduser()
    return root / f"{safe_task_id(task_id)}.json"


def read_task_state(task_id: str) -> dict[str, Any]:
    path = task_state_path(task_id)
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def current_generation(task_id: str) -> str | None:
    _label, _plist, config_path = launch_paths(task_id)
    if not config_path.exists():
        return None
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = loaded.get("generation_id") if isinstance(loaded, dict) else None
    return value if isinstance(value, str) else None


def has_successor_generation(task_id: str, generation_id: str) -> bool:
    value = current_generation(task_id)
    return value is not None and value != generation_id


def should_quiesce(task_id: str, generation_id: str) -> tuple[bool, str]:
    if has_successor_generation(task_id, generation_id):
        return False, "successor_supervisor_active"
    state = read_task_state(task_id).get("state")
    if state in QUIESCENT_TASK_STATES:
        return True, str(state)
    if state in ORPHANED_ASYNC_STATES:
        return True, f"orphaned_{state}"
    return False, str(state or "unknown")


def wake_root() -> Path:
    root = Path(
        os.environ.get("COLLAB_WAKE_ROOT", "~/.codex/collaboration/wakes")
    ).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def dispatch_id(task_id: str) -> str | None:
    value = read_task_state(task_id).get("dispatch_id")
    return value if isinstance(value, str) else None


def condition_fingerprint(
    task_id: str,
    event_name: str,
    candidate_sha: str | None,
    payload: dict[str, Any],
) -> str:
    material = {
        "task_id": task_id,
        "dispatch_id": dispatch_id(task_id),
        "event_type": event_name,
        "candidate_sha": candidate_sha,
        "payload": payload,
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def processed_marker(task_id: str) -> Path:
    return wake_root() / f"{safe_task_id(task_id)}.last-condition.json"


def already_processed(task_id: str, fingerprint: str) -> bool:
    path = processed_marker(task_id)
    if not path.exists():
        return False
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(loaded, dict) and loaded.get("fingerprint") == fingerprint


def mark_processed(
    task_id: str,
    fingerprint: str,
    event_name: str,
    state: str,
) -> None:
    path = processed_marker(task_id)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "event_type": event_name,
                "task_state": state,
                "processed_at_epoch": int(time.time()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def inflight_marker(task_id: str) -> Path:
    return wake_root() / f"{safe_task_id(task_id)}.in-flight.json"


def read_inflight_marker(task_id: str) -> dict[str, Any] | None:
    path = inflight_marker(task_id)
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def process_is_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_inflight_marker(
    task_id: str,
    fingerprint: str,
    event_name: str,
    event_id: str,
) -> bool:
    path = inflight_marker(task_id)
    payload = {
        "task_id": task_id,
        "fingerprint": fingerprint,
        "event_type": event_name,
        "event_id": event_id,
        "pid": os.getpid(),
        "started_at_epoch": int(time.time()),
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        existing = read_inflight_marker(task_id)
        if existing and process_is_alive(existing.get("pid")):
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return False
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def clear_inflight_marker(task_id: str, fingerprint: str) -> None:
    path = inflight_marker(task_id)
    marker = read_inflight_marker(task_id)
    if not marker or marker.get("fingerprint") != fingerprint:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def write_quiescent_marker(
    task_id: str,
    fingerprint: str,
    state: str,
    event_name: str,
) -> None:
    path = wake_root() / f"{safe_task_id(task_id)}.quiescent.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "task_state": state,
                "event_type": event_name,
                "fingerprint": fingerprint,
                "goal_status": "paused",
                "reason": "suppress_unchanged_native_goal_continuations",
                "created_at_epoch": int(time.time()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def acquire_task_wake_lock(task_id: str):
    path = wake_root() / f"{safe_task_id(task_id)}.wake.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resume the same Codex session after a collaboration event"
    )
    parser.add_argument("task_id")
    parser.add_argument("thread_id")
    parser.add_argument("generation_id")
    parser.add_argument("event_type")
    parser.add_argument("event_id")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--skill-root", required=True)
    parser.add_argument("--candidate-sha")
    parser.add_argument("--event-payload", default="{}")
    parser.add_argument("--resume-timeout-seconds", type=int, default=300)
    parser.add_argument("--codex")
    args = parser.parse_args()

    if args.resume_timeout_seconds < 1:
        print("error=invalid_resume_timeout", file=sys.stderr)
        return 2

    repo = Path(args.repo).expanduser().resolve()
    skill_root = Path(args.skill_root).expanduser().resolve()
    codex = args.codex or shutil.which("codex")
    if not codex:
        print("error=codex_not_found", file=sys.stderr)
        notify("ChatGPT-Codex handoff", "Codex CLI not found; resume manually.")
        return 2
    codex = str(Path(codex).expanduser().resolve())

    try:
        event_payload = json.loads(args.event_payload)
    except json.JSONDecodeError:
        event_payload = {"raw": args.event_payload}
    if not isinstance(event_payload, dict):
        event_payload = {"value": event_payload}

    fingerprint = condition_fingerprint(
        args.task_id,
        args.event_type,
        args.candidate_sha,
        event_payload,
    )

    wake_lock = acquire_task_wake_lock(args.task_id)
    if wake_lock is None:
        print(
            f"event=wake_concurrent_ignored task_id={args.task_id} "
            f"fingerprint={fingerprint}"
        )
        return 0

    try:
        if already_processed(args.task_id, fingerprint):
            quiesce, state = should_quiesce(args.task_id, args.generation_id)
            if quiesce:
                run_goal_control(
                    skill_root,
                    args.thread_id,
                    "paused",
                    repo,
                    codex,
                )
            print(
                f"event=wake_condition_duplicate_ignored task_id={args.task_id} "
                f"fingerprint={fingerprint} state={state}"
            )
            return 0

        if not acquire_inflight_marker(
            args.task_id,
            fingerprint,
            args.event_type,
            args.event_id,
        ):
            print(
                f"event=wake_inflight_duplicate_ignored task_id={args.task_id} "
                f"fingerprint={fingerprint}"
            )
            return 0

        log_root = Path(
            os.environ.get("COLLAB_LOG_ROOT", "~/.codex/collaboration/logs")
        ).expanduser()
        log_root.mkdir(parents=True, exist_ok=True)
        log_path = log_root / f"{args.task_id}.codex-resume.log"

        prompt = f"""Use the installed chatgpt-codex-collaboration skill and resume the existing collaboration task.

Task ID: {args.task_id}
Supervisor generation: {args.generation_id}
Terminal event: {args.event_type}
Event ID: {args.event_id}
Condition fingerprint: {fingerprint}
Candidate SHA: {args.candidate_sha or 'none'}
Event payload: {json.dumps(event_payload, ensure_ascii=False)}

This is the same persisted Codex thread and native goal. The goal is temporarily paused only to prevent token-consuming continuation turns during external work. The wake controller will reactivate it after this explicit resumed turn starts. Do not create, replace, clear, block, or manually resume the goal.

Read the existing task state, wake configuration, supervisor logs, transport events, remote branch, and authoritative specifications. If the event adds no new evidence and the task is already in the same stable blocked state, do not emit another user-visible status message. If the event is handoff_candidate, validate the candidate and run independent acceptance. If the event is a transport or protocol failure, execute one documented recovery path. Do not redispatch blindly and do not report completion without evidence.

Transport guard: this resumed turn must not inspect or control the ChatGPT UI. Do not run screencapture, screenshot inspection, browser inspection, osascript against ChatGPT, or another repair/status prompt. Use only persisted task state, local transport events, the remote branch, and the authoritative specifications. If those sources add no new evidence, stop this turn with the existing blocker preserved.
"""

        started = time.time()
        goal_reactivated = False
        quiescent_paused = False
        quiescent_state = ""
        intentional_interrupt = False
        returncode = 2
        proc: subprocess.Popen[str] | None = None
        turn_started_count = 0
        resume_timed_out = threading.Event()
        timeout_timer: threading.Timer | None = None

        try:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(
                    json.dumps(
                        {
                            "event": "codex_resume_started",
                            "task_id": args.task_id,
                            "thread_id": args.thread_id,
                            "generation_id": args.generation_id,
                            "event_type": args.event_type,
                            "event_id": args.event_id,
                            "condition_fingerprint": fingerprint,
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

                def stop_timed_out_resume() -> None:
                    resume_timed_out.set()
                    terminate_process(proc)

                timeout_timer = threading.Timer(
                    args.resume_timeout_seconds,
                    stop_timed_out_resume,
                )
                timeout_timer.daemon = True
                timeout_timer.start()

                try:
                    for line in proc.stdout:
                        log.write(line)
                        log.flush()
                        current_event = event_type(line)

                        if current_event == "turn.started":
                            turn_started_count += 1
                            if quiescent_paused and turn_started_count > 1:
                                log.write(
                                    json.dumps(
                                        {
                                            "event": "unexpected_continuation_interrupted",
                                            "task_id": args.task_id,
                                            "condition_fingerprint": fingerprint,
                                        }
                                    )
                                    + "\n"
                                )
                                log.flush()
                                intentional_interrupt = True
                                terminate_process(proc)
                                break

                            if not goal_reactivated:
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
                                            "generation_id": args.generation_id,
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

                        if current_event == "turn.completed" and goal_reactivated:
                            quiesce, state = should_quiesce(
                                args.task_id,
                                args.generation_id,
                            )
                            if quiesce and not quiescent_paused:
                                paused = run_goal_control(
                                    skill_root,
                                    args.thread_id,
                                    "paused",
                                    repo,
                                    codex,
                                )
                                log.write(
                                    json.dumps(
                                        {
                                            "event": "native_goal_quiescent_pause",
                                            "task_id": args.task_id,
                                            "generation_id": args.generation_id,
                                            "task_state": state,
                                            "returncode": paused.returncode,
                                            "condition_fingerprint": fingerprint,
                                            "detail": (
                                                paused.stdout.strip()
                                                if paused.returncode == 0
                                                else (paused.stderr or paused.stdout).strip()
                                            )[-2000:],
                                        }
                                    )
                                    + "\n"
                                )
                                log.flush()
                                if paused.returncode != 0:
                                    terminate_process(proc)
                                    raise RuntimeError("native goal quiescent pause failed")
                                quiescent_paused = True
                                quiescent_state = state
                                write_quiescent_marker(
                                    args.task_id,
                                    fingerprint,
                                    state,
                                    args.event_type,
                                )
                finally:
                    if timeout_timer is not None:
                        timeout_timer.cancel()

                returncode = proc.wait()
                if resume_timed_out.is_set():
                    log.write(
                        json.dumps(
                            {
                                "event": "codex_resume_timeout",
                                "task_id": args.task_id,
                                "generation_id": args.generation_id,
                                "condition_fingerprint": fingerprint,
                                "timeout_seconds": args.resume_timeout_seconds,
                            }
                        )
                        + "\n"
                    )
                    log.flush()
                cleaned = cleanup_generation(args.task_id, args.generation_id)
                log.write(
                    json.dumps(
                        {
                            "event": "codex_resume_finished",
                            "task_id": args.task_id,
                            "generation_id": args.generation_id,
                            "event_id": args.event_id,
                            "condition_fingerprint": fingerprint,
                            "returncode": returncode,
                            "goal_reactivated": goal_reactivated,
                            "quiescent_paused": quiescent_paused,
                            "quiescent_state": quiescent_state,
                            "intentional_interrupt": intentional_interrupt,
                            "resume_timed_out": resume_timed_out.is_set(),
                            "supervisor_generation_cleaned": cleaned,
                            "duration_seconds": round(time.time() - started, 3),
                        }
                    )
                    + "\n"
                )
                log.flush()

            success = (
                goal_reactivated
                and not resume_timed_out.is_set()
                and (returncode == 0 or intentional_interrupt)
            )
            if not success:
                if goal_reactivated and not quiescent_paused:
                    run_goal_control(
                        skill_root,
                        args.thread_id,
                        "paused",
                        repo,
                        codex,
                    )
                notify(
                    "ChatGPT-Codex resume failed",
                    f"Task {args.task_id} remains paused. Check {log_path} and retry.",
                )
                print(
                    f"error=codex_exec_resume_failed returncode={returncode} "
                    f"turn_started={str(goal_reactivated).lower()} log={log_path}",
                    file=sys.stderr,
                )
                return 2 if resume_timed_out.is_set() else (returncode or 2)

            final_state = str(read_task_state(args.task_id).get("state") or "unknown")
            mark_processed(
                args.task_id,
                fingerprint,
                args.event_type,
                final_state,
            )
            if quiescent_paused:
                notify(
                    "ChatGPT-Codex task paused",
                    f"{args.task_id} is {quiescent_state}. Resume after the blocker changes.",
                )

            print(
                f"event=codex_session_resumed task_id={args.task_id} "
                f"generation_id={args.generation_id} thread_id={args.thread_id} "
                f"event_id={args.event_id} fingerprint={fingerprint} "
                f"quiescent_paused={str(quiescent_paused).lower()} log={log_path}"
            )
            return 0
        except Exception as exc:
            if proc is not None:
                terminate_process(proc)
            if goal_reactivated and not quiescent_paused:
                run_goal_control(
                    skill_root,
                    args.thread_id,
                    "paused",
                    repo,
                    codex,
                )
            cleanup_generation(args.task_id, args.generation_id)
            notify(
                "ChatGPT-Codex resume failed",
                f"Task {args.task_id} remains paused. Check {log_path} and retry.",
            )
            print(f"error={exc} log={log_path}", file=sys.stderr)
            return 2
    finally:
        clear_inflight_marker(args.task_id, fingerprint)
        fcntl.flock(wake_lock.fileno(), fcntl.LOCK_UN)
        wake_lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
