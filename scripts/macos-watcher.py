#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time

TASK_RE = re.compile(r"^[A-Za-z0-9._-]+$")
WATCHER_TERMINAL_EVENTS = {
    "handoff_candidate": 0,
    "lease_expired": 124,
    "interrupted": 130,
}
TRANSPORT_TERMINAL_EVENTS = {
    "implementation_blocked": 20,
    "capability_rejected": 20,
    "conversation_completed_no_commit": 21,
    "conversation_failed": 22,
    "transport_unreachable": 23,
    "mode_drifted": 24,
}


def event_root() -> Path:
    root = Path(
        os.environ.get("COLLAB_EVENT_ROOT", "~/.codex/collaboration/events")
    ).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def paths(task_id: str) -> tuple[str, Path, Path, Path, Path]:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", task_id)
    label = f"com.backtrue.chatgpt-codex.{safe}"
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    logs = Path(
        os.environ.get("COLLAB_LOG_ROOT", "~/.codex/collaboration/logs")
    ).expanduser()
    logs.mkdir(parents=True, exist_ok=True)
    transport_events = event_root() / f"{safe}.jsonl"
    return (
        label,
        plist,
        logs / f"{safe}.out.log",
        logs / f"{safe}.err.log",
        transport_events,
    )


def domain() -> str:
    return f"gui/{os.getuid()}"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def event_from_line(line: str) -> str | None:
    for field in line.strip().split():
        if field.startswith("event="):
            return field.split("=", 1)[1]
    return None


def transport_event_from_line(line: str) -> tuple[str | None, dict[str, object]]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None, {}
    if not isinstance(event, dict):
        return None, {}
    event_type = event.get("event_type")
    return (event_type if isinstance(event_type, str) else None, event)


def unload(label: str, plist: Path) -> None:
    run("launchctl", "bootout", domain(), str(plist))
    run("launchctl", "bootout", f"{domain()}/{label}")


def start(args: argparse.Namespace) -> int:
    if sys.platform != "darwin":
        print("error=requires_macos", file=sys.stderr)
        return 2
    if not TASK_RE.fullmatch(args.task_id):
        print("error=invalid_task_id", file=sys.stderr)
        return 2

    repo = Path(args.repo).expanduser().resolve()
    watcher = Path(__file__).with_name("wait-for-handoff.py").resolve()
    python = Path(sys.executable).resolve()
    label, plist, stdout_path, stderr_path, transport_path = paths(args.task_id)
    plist.parent.mkdir(parents=True, exist_ok=True)

    unload(label, plist)
    for path in (stdout_path, stderr_path, transport_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    data = {
        "Label": label,
        "ProgramArguments": [
            str(python),
            str(watcher),
            args.task_id,
            args.branch,
            args.base_sha,
            str(args.lease_seconds),
            str(args.poll_seconds),
            "--max-poll-seconds",
            str(args.max_poll_seconds),
            "--remote",
            args.remote,
            "--dispatch-epoch",
            str(args.dispatch_epoch),
        ],
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Background",
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stderr_path),
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
        },
    }
    with plist.open("wb") as handle:
        plistlib.dump(data, handle, sort_keys=False)

    result = run("launchctl", "bootstrap", domain(), str(plist))
    if result.returncode != 0:
        print(
            f"error=launchctl_bootstrap_failed detail={result.stderr.strip()}",
            file=sys.stderr,
        )
        return 2
    run("launchctl", "kickstart", "-k", f"{domain()}/{label}")
    print(
        f"event=watcher_started task_id={args.task_id} "
        f"label={label} plist={plist} transport_events={transport_path}"
    )
    return 0


def status(args: argparse.Namespace) -> int:
    label, plist, stdout_path, stderr_path, transport_path = paths(args.task_id)
    result = run("launchctl", "print", f"{domain()}/{label}")
    print(result.stdout if result.returncode == 0 else result.stderr, end="")
    print(
        f"plist={plist}\nstdout={stdout_path}\nstderr={stderr_path}"
        f"\ntransport_events={transport_path}"
    )
    return result.returncode


def await_event(args: argparse.Namespace) -> int:
    if sys.platform != "darwin":
        print("error=requires_macos", file=sys.stderr)
        return 2

    label, plist, stdout_path, stderr_path, transport_path = paths(args.task_id)
    deadline = time.monotonic() + args.timeout_seconds
    watcher_offset = 0
    transport_offset = 0
    missing_since: float | None = None
    last_health_check = 0.0

    print(
        f"event=await_started task_id={args.task_id} "
        f"timeout_seconds={args.timeout_seconds}",
        flush=True,
    )

    while time.monotonic() < deadline:
        if stdout_path.exists():
            with stdout_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(watcher_offset)
                for line in handle:
                    print(line.rstrip("\n"), flush=True)
                    event = event_from_line(line)
                    if event in WATCHER_TERMINAL_EVENTS:
                        return WATCHER_TERMINAL_EVENTS[event]
                watcher_offset = handle.tell()

        if transport_path.exists():
            with transport_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(transport_offset)
                for line in handle:
                    event_type, event = transport_event_from_line(line)
                    if event_type is None:
                        continue
                    print(
                        "event=transport_terminal "
                        f"task_id={args.task_id} event_type={event_type} "
                        f"payload={json.dumps(event.get('payload', {}), ensure_ascii=False)}",
                        flush=True,
                    )
                    if event_type in TRANSPORT_TERMINAL_EVENTS:
                        unload(label, plist)
                        return TRANSPORT_TERMINAL_EVENTS[event_type]
                transport_offset = handle.tell()

        now = time.monotonic()
        if now - last_health_check >= args.health_check_seconds:
            loaded = run("launchctl", "print", f"{domain()}/{label}").returncode == 0
            last_health_check = now
            if loaded or plist.exists():
                missing_since = None
            elif missing_since is None:
                missing_since = now
            elif now - missing_since >= args.missing_grace_seconds:
                stderr_tail = ""
                if stderr_path.exists():
                    stderr_tail = stderr_path.read_text(
                        encoding="utf-8", errors="replace"
                    )[-2000:]
                print(
                    f"error=watcher_missing task_id={args.task_id} "
                    f"stderr_tail={stderr_tail!r}",
                    file=sys.stderr,
                )
                return 2

        time.sleep(args.local_poll_seconds)

    print(
        f"event=await_timeout task_id={args.task_id} "
        f"timeout_seconds={args.timeout_seconds} implementation_failed=false",
        flush=True,
    )
    return 124


def stop(args: argparse.Namespace) -> int:
    label, plist, _stdout_path, _stderr_path, _transport_path = paths(args.task_id)
    unload(label, plist)
    if plist.exists() and not args.keep_plist:
        plist.unlink()
    print(f"event=watcher_stopped task_id={args.task_id} label={label}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage macOS launchd handoff watchers")
    sub = parser.add_subparsers(dest="command", required=True)

    start_parser = sub.add_parser("start")
    start_parser.add_argument("task_id")
    start_parser.add_argument("branch")
    start_parser.add_argument("base_sha")
    start_parser.add_argument("--repo", required=True)
    start_parser.add_argument("--remote", default="origin")
    start_parser.add_argument("--lease-seconds", type=int, default=7200)
    start_parser.add_argument("--poll-seconds", type=int, default=60)
    start_parser.add_argument("--max-poll-seconds", type=int, default=300)
    start_parser.add_argument("--dispatch-epoch", type=int, default=int(time.time()))
    start_parser.set_defaults(func=start)

    status_parser = sub.add_parser("status")
    status_parser.add_argument("task_id")
    status_parser.set_defaults(func=status)

    await_parser = sub.add_parser("await")
    await_parser.add_argument("task_id")
    await_parser.add_argument("--timeout-seconds", type=int, default=7500)
    await_parser.add_argument("--local-poll-seconds", type=float, default=5.0)
    await_parser.add_argument("--health-check-seconds", type=float, default=30.0)
    await_parser.add_argument("--missing-grace-seconds", type=float, default=10.0)
    await_parser.set_defaults(func=await_event)

    stop_parser = sub.add_parser("stop")
    stop_parser.add_argument("task_id")
    stop_parser.add_argument("--keep-plist", action="store_true")
    stop_parser.set_defaults(func=stop)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
