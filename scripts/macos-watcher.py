#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time

TASK_RE = re.compile(r"^[A-Za-z0-9._-]+$")
TERMINAL_EVENTS = {
    "handoff_candidate": 0,
    "lease_expired": 124,
    "interrupted": 130,
}


def paths(task_id: str) -> tuple[str, Path, Path, Path]:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", task_id)
    label = f"com.backtrue.chatgpt-codex.{safe}"
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    logs = Path(
        os.environ.get("COLLAB_LOG_ROOT", "~/.codex/collaboration/logs")
    ).expanduser()
    logs.mkdir(parents=True, exist_ok=True)
    return label, plist, logs / f"{safe}.out.log", logs / f"{safe}.err.log"


def domain() -> str:
    return f"gui/{os.getuid()}"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def event_from_line(line: str) -> str | None:
    for field in line.strip().split():
        if field.startswith("event="):
            return field.split("=", 1)[1]
    return None


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
    label, plist, stdout_path, stderr_path = paths(args.task_id)
    plist.parent.mkdir(parents=True, exist_ok=True)

    run("launchctl", "bootout", domain(), str(plist))
    for log_path in (stdout_path, stderr_path):
        try:
            log_path.unlink()
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
        f"label={label} plist={plist}"
    )
    return 0


def status(args: argparse.Namespace) -> int:
    label, plist, stdout_path, stderr_path = paths(args.task_id)
    result = run("launchctl", "print", f"{domain()}/{label}")
    print(result.stdout if result.returncode == 0 else result.stderr, end="")
    print(f"plist={plist}\nstdout={stdout_path}\nstderr={stderr_path}")
    return result.returncode


def await_event(args: argparse.Namespace) -> int:
    if sys.platform != "darwin":
        print("error=requires_macos", file=sys.stderr)
        return 2
    label, plist, stdout_path, stderr_path = paths(args.task_id)
    deadline = time.monotonic() + args.timeout_seconds
    offset = 0
    missing_since: float | None = None

    print(
        f"event=await_started task_id={args.task_id} "
        f"timeout_seconds={args.timeout_seconds}",
        flush=True,
    )

    while time.monotonic() < deadline:
        if stdout_path.exists():
            with stdout_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                for line in handle:
                    print(line.rstrip("\n"), flush=True)
                    event = event_from_line(line)
                    if event in TERMINAL_EVENTS:
                        return TERMINAL_EVENTS[event]
                offset = handle.tell()

        loaded = run("launchctl", "print", f"{domain()}/{label}").returncode == 0
        if loaded or plist.exists():
            missing_since = None
        elif missing_since is None:
            missing_since = time.monotonic()
        elif time.monotonic() - missing_since >= args.missing_grace_seconds:
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
    label, plist, _stdout_path, _stderr_path = paths(args.task_id)
    run("launchctl", "bootout", domain(), str(plist))
    if plist.exists() and not args.keep_plist:
        plist.unlink()
    print(f"event=watcher_stopped task_id={args.task_id} label={label}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage macOS launchd handoff watchers")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("start")
    s.add_argument("task_id")
    s.add_argument("branch")
    s.add_argument("base_sha")
    s.add_argument("--repo", required=True)
    s.add_argument("--remote", default="origin")
    s.add_argument("--lease-seconds", type=int, default=7200)
    s.add_argument("--poll-seconds", type=int, default=60)
    s.add_argument("--max-poll-seconds", type=int, default=300)
    s.add_argument("--dispatch-epoch", type=int, default=int(time.time()))
    s.set_defaults(func=start)

    st = sub.add_parser("status")
    st.add_argument("task_id")
    st.set_defaults(func=status)

    a = sub.add_parser("await")
    a.add_argument("task_id")
    a.add_argument("--timeout-seconds", type=int, default=7500)
    a.add_argument("--local-poll-seconds", type=float, default=2.0)
    a.add_argument("--missing-grace-seconds", type=float, default=5.0)
    a.set_defaults(func=await_event)

    x = sub.add_parser("stop")
    x.add_argument("task_id")
    x.add_argument("--keep-plist", action="store_true")
    x.set_defaults(func=stop)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
