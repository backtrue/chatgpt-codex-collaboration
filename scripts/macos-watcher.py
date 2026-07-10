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


def paths(task_id: str) -> tuple[str, Path, Path, Path]:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", task_id)
    label = f"com.backtrue.chatgpt-codex.{safe}"
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    logs = Path(os.environ.get("COLLAB_LOG_ROOT", "~/.codex/collaboration/logs")).expanduser()
    logs.mkdir(parents=True, exist_ok=True)
    return label, plist, logs / f"{safe}.out.log", logs / f"{safe}.err.log"


def domain() -> str:
    return f"gui/{os.getuid()}"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


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

    data = {
        "Label": label,
        "ProgramArguments": [
            str(python), str(watcher), args.task_id, args.branch, args.base_sha,
            str(args.lease_seconds), str(args.poll_seconds), "--remote", args.remote,
            "--dispatch-epoch", str(args.dispatch_epoch),
        ],
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Background",
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stderr_path),
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")},
    }
    with plist.open("wb") as handle:
        plistlib.dump(data, handle, sort_keys=False)

    run("launchctl", "bootout", domain(), str(plist))
    result = run("launchctl", "bootstrap", domain(), str(plist))
    if result.returncode != 0:
        print(f"error=launchctl_bootstrap_failed detail={result.stderr.strip()}", file=sys.stderr)
        return 2
    run("launchctl", "kickstart", "-k", f"{domain()}/{label}")
    print(f"event=watcher_started task_id={args.task_id} label={label} plist={plist}")
    return 0


def status(args: argparse.Namespace) -> int:
    label, plist, stdout_path, stderr_path = paths(args.task_id)
    result = run("launchctl", "print", f"{domain()}/{label}")
    print(result.stdout if result.returncode == 0 else result.stderr, end="")
    print(f"plist={plist}\nstdout={stdout_path}\nstderr={stderr_path}")
    return result.returncode


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
    s.add_argument("--poll-seconds", type=int, default=30)
    s.add_argument("--dispatch-epoch", type=int, default=int(time.time()))
    s.set_defaults(func=start)

    st = sub.add_parser("status")
    st.add_argument("task_id")
    st.set_defaults(func=status)

    x = sub.add_parser("stop")
    x.add_argument("task_id")
    x.add_argument("--keep-plist", action="store_true")
    x.set_defaults(func=stop)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
