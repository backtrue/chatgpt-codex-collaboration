#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time
import uuid

TASK_RE = re.compile(r"^[A-Za-z0-9._-]+$")
EXECUTOR_PROFILES = {"local_full", "github_connector"}
DEFAULT_LEASE_SECONDS = {
    "local_full": 7200,
    "github_connector": 1800,
}


def event_root() -> Path:
    root = Path(
        os.environ.get("COLLAB_EVENT_ROOT", "~/.codex/collaboration/events")
    ).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def wake_root() -> Path:
    root = Path(
        os.environ.get("COLLAB_WAKE_ROOT", "~/.codex/collaboration/wakes")
    ).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def state_root() -> Path:
    return Path(
        os.environ.get("COLLAB_STATE_ROOT", "~/.codex/collaboration/tasks")
    ).expanduser()


def task_executor_profile(task_id: str) -> str | None:
    path = state_root() / f"{task_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    executor = data.get("executor")
    if not isinstance(executor, dict):
        return None
    profile = executor.get("executor_profile")
    return profile if profile in EXECUTOR_PROFILES else None


def paths(task_id: str) -> tuple[str, Path, Path, Path, Path, Path]:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", task_id)
    label = f"com.backtrue.chatgpt-codex.{safe}"
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    logs = Path(
        os.environ.get("COLLAB_LOG_ROOT", "~/.codex/collaboration/logs")
    ).expanduser()
    logs.mkdir(parents=True, exist_ok=True)
    return (
        label,
        plist,
        logs / f"{safe}.out.log",
        logs / f"{safe}.err.log",
        event_root() / f"{safe}.jsonl",
        wake_root() / f"{safe}.json",
    )


def domain() -> str:
    return f"gui/{os.getuid()}"


def run(
    *args: str,
    cwd: Path | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def unload(label: str, plist: Path) -> None:
    run("launchctl", "bootout", domain(), str(plist))
    run("launchctl", "bootout", f"{domain()}/{label}")


def resolve_codex(explicit: str | None) -> str | None:
    candidate = explicit or shutil.which("codex")
    if not candidate:
        return None
    return str(Path(candidate).expanduser().resolve())


def goal_control(
    skill_root: Path,
    thread_id: str,
    status: str,
    repo: Path,
    codex: str,
) -> subprocess.CompletedProcess[str]:
    return run(
        "sh",
        str(skill_root / "scripts" / "codex-goal-control.sh"),
        "set",
        thread_id,
        status,
        "--cwd",
        str(repo),
        "--codex",
        codex,
        cwd=repo,
        timeout=40,
    )


def prepare_branch(
    skill_root: Path,
    repo: Path,
    remote: str,
    branch: str,
    base_sha: str,
) -> subprocess.CompletedProcess[str]:
    return run(
        "sh",
        str(skill_root / "scripts" / "prepare-handoff-branch.sh"),
        str(repo),
        remote,
        branch,
        base_sha,
        cwd=repo,
        timeout=150,
    )


def start(args: argparse.Namespace) -> int:
    if sys.platform != "darwin":
        print("error=requires_macos", file=sys.stderr)
        return 2
    if not TASK_RE.fullmatch(args.task_id):
        print("error=invalid_task_id", file=sys.stderr)
        return 2

    thread_id = args.thread_id or os.environ.get("CODEX_THREAD_ID")
    if not thread_id:
        print("error=missing_codex_thread_id", file=sys.stderr)
        return 2

    executor_profile = args.executor_profile or task_executor_profile(args.task_id)
    if executor_profile not in EXECUTOR_PROFILES:
        print(
            "error=missing_executor_profile "
            "detail=Run capability handshake and persist local_full or github_connector before starting.",
            file=sys.stderr,
        )
        return 2
    lease_seconds = (
        args.lease_seconds
        if args.lease_seconds is not None
        else DEFAULT_LEASE_SECONDS[executor_profile]
    )
    if lease_seconds < 1:
        print("error=invalid_lease_seconds", file=sys.stderr)
        return 2

    browser_fields = {
        "browser_script": args.browser_script,
        "conversation_url": args.conversation_url,
        "prompt_file": args.prompt_file,
        "dispatch_id": args.dispatch_id,
        "message_fingerprint": args.message_fingerprint,
    }
    if any(browser_fields.values()) and not all(browser_fields.values()):
        print(
            "error=incomplete_browser_transport_fields "
            f"missing={','.join(name for name, value in browser_fields.items() if not value)}",
            file=sys.stderr,
        )
        return 2
    if args.browser_script and not Path(args.browser_script).expanduser().is_file():
        print("error=browser_transport_script_not_found", file=sys.stderr)
        return 2
    if args.prompt_file and not Path(args.prompt_file).expanduser().is_file():
        print("error=browser_transport_prompt_not_found", file=sys.stderr)
        return 2

    repo = Path(args.repo).expanduser().resolve()
    skill_root = Path(__file__).resolve().parent.parent
    supervisor = skill_root / "scripts" / "event-supervisor.py"
    python = Path(sys.executable).resolve()
    codex = resolve_codex(args.codex)
    if codex is None:
        print("error=codex_not_found", file=sys.stderr)
        return 2

    generation_id = f"{args.dispatch_epoch}-{uuid.uuid4()}"
    label, plist, stdout_path, stderr_path, transport_path, config_path = paths(
        args.task_id
    )
    plist.parent.mkdir(parents=True, exist_ok=True)

    prepared = prepare_branch(
        skill_root,
        repo,
        args.remote,
        args.branch,
        args.base_sha,
    )
    if prepared.returncode != 0:
        detail = (prepared.stderr or prepared.stdout).strip()
        print(f"error=handoff_branch_not_ready detail={detail}", file=sys.stderr)
        return 2

    paused = goal_control(skill_root, thread_id, "paused", repo, codex)
    if paused.returncode != 0:
        detail = (paused.stderr or paused.stdout).strip()
        print(f"error=native_goal_pause_failed detail={detail}", file=sys.stderr)
        return 2

    unload(label, plist)
    for path in (stdout_path, stderr_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    program_arguments = [
        str(python),
        str(supervisor),
        args.task_id,
        args.branch,
        args.base_sha,
        thread_id,
        generation_id,
        "--repo",
        str(repo),
        "--remote",
        args.remote,
        "--skill-root",
        str(skill_root),
        "--transport-events",
        str(transport_path),
        "--lease-seconds",
        str(lease_seconds),
        "--poll-seconds",
        str(args.poll_seconds),
        "--max-poll-seconds",
        str(args.max_poll_seconds),
        "--dispatch-epoch",
        str(args.dispatch_epoch),
        "--codex",
        codex,
    ]
    if args.browser_script:
        program_arguments.extend(
            [
                "--browser-script",
                str(Path(args.browser_script).expanduser().resolve()),
                "--browser-use",
                args.browser_use or "browser-use",
                "--conversation-url",
                args.conversation_url,
                "--prompt-file",
                str(Path(args.prompt_file).expanduser().resolve()),
                "--dispatch-id",
                args.dispatch_id,
                "--message-fingerprint",
                args.message_fingerprint,
                "--browser-poll-seconds",
                str(args.browser_poll_seconds),
            ]
        )

    data = {
        "Label": label,
        "ProgramArguments": program_arguments,
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Background",
        "ThrottleInterval": 10,
        "AbandonProcessGroup": True,
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stderr_path),
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
            "CODEX_THREAD_ID": thread_id,
        },
    }
    with plist.open("wb") as handle:
        plistlib.dump(data, handle, sort_keys=False)

    config_path.write_text(
        json.dumps(
            {
                "schema_version": "1.2",
                "task_id": args.task_id,
                "generation_id": generation_id,
                "thread_id": thread_id,
                "executor_profile": executor_profile,
                "repo": str(repo),
                "remote": args.remote,
                "branch": args.branch,
                "base_sha": args.base_sha,
                "dispatch_epoch": args.dispatch_epoch,
                "lease_seconds": lease_seconds,
                "skill_root": str(skill_root),
                "codex": codex,
                "goal_status_during_wait": "paused",
                "wake_mode": "codex_exec_resume",
                "browser_transport": bool(args.browser_script),
                "conversation_url": args.conversation_url,
                "dispatch_id": args.dispatch_id,
                "created_at_epoch": int(time.time()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = run("launchctl", "bootstrap", domain(), str(plist))
    if result.returncode != 0:
        goal_control(skill_root, thread_id, "active", repo, codex)
        print(
            f"error=launchctl_bootstrap_failed detail={result.stderr.strip()}",
            file=sys.stderr,
        )
        return 2

    run("launchctl", "kickstart", "-k", f"{domain()}/{label}")
    print(
        f"event=event_supervisor_started task_id={args.task_id} "
        f"generation_id={generation_id} thread_id={thread_id} label={label} "
        f"executor_profile={executor_profile} lease_seconds={lease_seconds} "
        f"branch={args.branch} goal_status=paused "
        f"wake_mode=codex_exec_resume plist={plist}"
    )
    print(
        "instruction=end_current_turn_no_await "
        "detail=The native goal is paused and the supervisor will resume this same session on a terminal event."
    )
    return 0


def status(args: argparse.Namespace) -> int:
    label, plist, stdout_path, stderr_path, transport_path, config_path = paths(
        args.task_id
    )
    result = run("launchctl", "print", f"{domain()}/{label}")
    print(result.stdout if result.returncode == 0 else result.stderr, end="")
    print(
        f"plist={plist}\nstdout={stdout_path}\nstderr={stderr_path}"
        f"\ntransport_events={transport_path}\nwake_config={config_path}"
    )
    return result.returncode


def deprecated_await(args: argparse.Namespace) -> int:
    print(
        "error=blocking_await_disabled "
        "detail=Use event-driven start; the supervisor pauses the goal and resumes the same CODEX_THREAD_ID on events.",
        file=sys.stderr,
    )
    return 2


def stop(args: argparse.Namespace) -> int:
    label, plist, _stdout_path, _stderr_path, _transport_path, config_path = paths(
        args.task_id
    )
    unload(label, plist)

    if args.resume_goal and config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            repo = Path(config["repo"]).expanduser().resolve()
            skill_root = Path(config["skill_root"]).expanduser().resolve()
            result = goal_control(
                skill_root,
                config["thread_id"],
                "active",
                repo,
                config["codex"],
            )
            if result.returncode != 0:
                print(
                    f"error=goal_resume_failed detail={(result.stderr or result.stdout).strip()}",
                    file=sys.stderr,
                )
                return 2
        except Exception as exc:
            print(f"error=invalid_wake_config detail={exc}", file=sys.stderr)
            return 2

    if plist.exists() and not args.keep_plist:
        plist.unlink()
    if config_path.exists() and not args.keep_config:
        config_path.unlink()
    print(
        f"event=event_supervisor_stopped task_id={args.task_id} "
        f"goal_resumed={str(args.resume_goal).lower()}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage event-driven macOS handoff supervisors"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start_parser = sub.add_parser("start")
    start_parser.add_argument("task_id")
    start_parser.add_argument("branch")
    start_parser.add_argument("base_sha")
    start_parser.add_argument("--repo", required=True)
    start_parser.add_argument("--remote", default="origin")
    start_parser.add_argument(
        "--executor-profile",
        choices=sorted(EXECUTOR_PROFILES),
    )
    start_parser.add_argument("--thread-id")
    start_parser.add_argument("--codex")
    start_parser.add_argument("--lease-seconds", type=int)
    start_parser.add_argument("--poll-seconds", type=int, default=60)
    start_parser.add_argument("--max-poll-seconds", type=int, default=300)
    start_parser.add_argument("--browser-script")
    start_parser.add_argument("--browser-use")
    start_parser.add_argument("--conversation-url")
    start_parser.add_argument("--prompt-file")
    start_parser.add_argument("--dispatch-id")
    start_parser.add_argument("--message-fingerprint")
    start_parser.add_argument("--browser-poll-seconds", type=int, default=60)
    start_parser.add_argument("--dispatch-epoch", type=int, default=int(time.time()))
    start_parser.set_defaults(func=start)

    status_parser = sub.add_parser("status")
    status_parser.add_argument("task_id")
    status_parser.set_defaults(func=status)

    await_parser = sub.add_parser("await")
    await_parser.add_argument("task_id")
    await_parser.set_defaults(func=deprecated_await)

    stop_parser = sub.add_parser("stop")
    stop_parser.add_argument("task_id")
    stop_parser.add_argument("--keep-plist", action="store_true")
    stop_parser.add_argument("--keep-config", action="store_true")
    stop_parser.add_argument("--resume-goal", action="store_true")
    stop_parser.set_defaults(func=stop)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
