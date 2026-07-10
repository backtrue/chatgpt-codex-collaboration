#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any

MIN_MACOS = (13, 0)
MIN_GIT = (2, 30)
MIN_PYTHON = (3, 9)


def version_tuple(text: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in text.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


def run(*args: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False, timeout=timeout)


def check(name: str, ok: bool, detail: str, required: bool = True, remediation: str | None = None) -> dict[str, Any]:
    return {"name": name, "status": "pass" if ok else ("fail" if required else "warn"), "required": required, "detail": detail, "remediation": remediation}


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose the macOS environment for ChatGPT-Codex collaboration")
    parser.add_argument("--repo", help="Optional repository path for GitHub connectivity checks")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--strict-runtime", action="store_true", help="Require runtime capability declarations in environment variables")
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    is_macos = sys.platform == "darwin"
    checks.append(check("platform", is_macos, f"platform={sys.platform}", remediation="Run this skill on macOS."))

    mac_version = platform.mac_ver()[0] if is_macos else ""
    mac_ok = is_macos and version_tuple(mac_version) >= MIN_MACOS
    checks.append(check("macos_version", mac_ok, f"macOS={mac_version or 'unknown'}; required>=13.0", remediation="Upgrade macOS to Ventura 13 or newer."))

    arch = platform.machine()
    checks.append(check("architecture", arch in {"arm64", "x86_64"}, f"architecture={arch}", remediation="Use a supported Apple Silicon or Intel Mac."))

    python_ok = sys.version_info >= MIN_PYTHON
    checks.append(check("python3", python_ok, f"python={platform.python_version()}; required>=3.9", remediation="Install Python 3.9+ with Homebrew or pyenv."))

    git_path = shutil.which("git")
    git_version = "missing"
    git_ok = False
    if git_path:
        result = run(git_path, "--version")
        git_version = result.stdout.strip() or result.stderr.strip()
        parts = git_version.split()
        parsed = version_tuple(parts[-1]) if parts else ()
        git_ok = result.returncode == 0 and parsed >= MIN_GIT
    checks.append(check("git", git_ok, f"{git_version}; required>=2.30", remediation="Install Xcode Command Line Tools or a newer Git with Homebrew."))

    xcode = run("xcode-select", "-p") if shutil.which("xcode-select") else None
    xcode_ok = bool(xcode and xcode.returncode == 0 and xcode.stdout.strip())
    checks.append(check("xcode_command_line_tools", xcode_ok, xcode.stdout.strip() if xcode_ok and xcode else "not configured", remediation="Run: xcode-select --install"))

    for command in ("launchctl", "osascript", "open"):
        path = shutil.which(command)
        checks.append(check(command, bool(path), path or "missing", remediation=f"{command} must be available from macOS system tools."))

    codex_path = shutil.which("codex")
    codex_detail = codex_path or "missing"
    codex_ok = bool(codex_path)
    if codex_path:
        version = run(codex_path, "--version")
        codex_detail = version.stdout.strip() or version.stderr.strip() or codex_path
    checks.append(check("codex_cli", codex_ok, codex_detail, remediation="Install or update the Codex CLI."))

    chrome = Path("/Applications/Google Chrome.app").exists() or Path.home().joinpath("Applications/Google Chrome.app").exists()
    safari = Path("/Applications/Safari.app").exists()
    chatgpt_app = Path("/Applications/ChatGPT.app").exists() or Path.home().joinpath("Applications/ChatGPT.app").exists()
    checks.append(check("chatgpt_surface", chrome or safari or chatgpt_app, f"chrome={chrome}, safari={safari}, chatgpt_app={chatgpt_app}", remediation="Install Google Chrome or the ChatGPT macOS app."))

    state_root = Path(os.environ.get("COLLAB_STATE_ROOT", "~/.codex/collaboration/tasks")).expanduser()
    try:
        state_root.mkdir(parents=True, exist_ok=True)
        probe = state_root / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        state_ok = True
        state_detail = str(state_root)
    except OSError as exc:
        state_ok = False
        state_detail = str(exc)
    checks.append(check("state_store", state_ok, state_detail, remediation="Make ~/.codex/collaboration writable."))

    runtime_vars = {
        "native_goal_tools": os.environ.get("COLLAB_NATIVE_GOAL_TOOLS"),
        "chatgpt_transport": os.environ.get("COLLAB_CHATGPT_TRANSPORT"),
        "chatgpt_executor": os.environ.get("COLLAB_CHATGPT_EXECUTOR"),
    }
    for name, value in runtime_vars.items():
        available = value in {"1", "true", "available", "yes"}
        checks.append(check(name, available, f"declaration={value or 'unset'}", required=args.strict_runtime, remediation=f"Set the corresponding COLLAB_* capability only after the runtime actually provides {name}."))

    if args.repo:
        repo = Path(args.repo).expanduser().resolve()
        repo_ok = repo.is_dir() and run("git", "-C", str(repo), "rev-parse", "--is-inside-work-tree").returncode == 0
        checks.append(check("repository", repo_ok, str(repo), remediation="Provide a valid local Git checkout."))
        if repo_ok:
            remote = run("git", "-C", str(repo), "ls-remote", args.remote)
            checks.append(check("github_remote", remote.returncode == 0, remote.stderr.strip() or f"remote={args.remote} reachable", remediation="Fix GitHub authentication, remote URL, or network access."))

    failures = [item for item in checks if item["status"] == "fail"]
    warnings = [item for item in checks if item["status"] == "warn"]
    payload = {
        "ready": not failures,
        "target": "macOS 13+",
        "architecture": arch,
        "checks": checks,
        "failure_count": len(failures),
        "warning_count": len(warnings),
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
