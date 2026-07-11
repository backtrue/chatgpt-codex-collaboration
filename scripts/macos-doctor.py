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
    try:
        return subprocess.run(
            args,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 127, "", str(exc))


def check(
    name: str,
    ok: bool,
    detail: str,
    required: bool = True,
    remediation: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": "pass" if ok else ("fail" if required else "warn"),
        "required": required,
        "detail": detail,
        "remediation": remediation,
    }


def writable_directory(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, str(path)
    except OSError as exc:
        return False, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose the macOS environment for ChatGPT-Codex collaboration"
    )
    parser.add_argument("--repo", help="Optional repository path for GitHub checks")
    parser.add_argument("--remote", default="origin")
    parser.add_argument(
        "--strict-runtime",
        action="store_true",
        help="Require CODEX_THREAD_ID in addition to event-driven Codex CLI features.",
    )
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    is_macos = sys.platform == "darwin"
    checks.append(
        check(
            "platform",
            is_macos,
            f"platform={sys.platform}",
            remediation="Run this skill on macOS.",
        )
    )

    mac_version = platform.mac_ver()[0] if is_macos else ""
    checks.append(
        check(
            "macos_version",
            is_macos and version_tuple(mac_version) >= MIN_MACOS,
            f"macOS={mac_version or 'unknown'}; required>=13.0",
            remediation="Upgrade macOS to Ventura 13 or newer.",
        )
    )

    arch = platform.machine()
    checks.append(
        check(
            "architecture",
            arch in {"arm64", "x86_64"},
            f"architecture={arch}",
            remediation="Use a supported Apple Silicon or Intel Mac.",
        )
    )

    checks.append(
        check(
            "python3",
            sys.version_info >= MIN_PYTHON,
            f"python={platform.python_version()}; required>=3.9",
            remediation="Install Python 3.9+ with Homebrew or pyenv.",
        )
    )

    git_path = shutil.which("git")
    git_version = "missing"
    git_ok = False
    if git_path:
        result = run(git_path, "--version")
        git_version = result.stdout.strip() or result.stderr.strip()
        parts = git_version.split()
        parsed = version_tuple(parts[-1]) if parts else ()
        git_ok = result.returncode == 0 and parsed >= MIN_GIT
    checks.append(
        check(
            "git",
            git_ok,
            f"{git_version}; required>=2.30",
            remediation="Install Xcode Command Line Tools or a newer Git.",
        )
    )

    xcode = run("xcode-select", "-p") if shutil.which("xcode-select") else None
    xcode_ok = bool(xcode and xcode.returncode == 0 and xcode.stdout.strip())
    checks.append(
        check(
            "xcode_command_line_tools",
            xcode_ok,
            xcode.stdout.strip() if xcode_ok and xcode else "not configured",
            remediation="Run: xcode-select --install",
        )
    )

    for command in ("launchctl", "osascript", "open"):
        path = shutil.which(command)
        checks.append(
            check(
                command,
                bool(path),
                path or "missing",
                remediation=f"{command} must be available from macOS system tools.",
            )
        )

    codex_path = shutil.which("codex")
    codex_detail = codex_path or "missing"
    codex_ok = bool(codex_path)
    app_server_ok = False
    exec_resume_ok = False
    if codex_path:
        version = run(codex_path, "--version")
        codex_detail = version.stdout.strip() or version.stderr.strip() or codex_path
        app_server_ok = run(codex_path, "app-server", "--help").returncode == 0
        exec_resume_ok = run(codex_path, "exec", "resume", "--help").returncode == 0
    checks.append(
        check(
            "codex_cli",
            codex_ok,
            codex_detail,
            remediation="Install or update the Codex CLI.",
        )
    )
    checks.append(
        check(
            "codex_app_server",
            app_server_ok,
            "available" if app_server_ok else "unavailable",
            remediation="Update Codex to a version with app-server support.",
        )
    )
    checks.append(
        check(
            "codex_exec_resume",
            exec_resume_ok,
            "available" if exec_resume_ok else "unavailable",
            remediation="Update Codex to a version with `codex exec resume`.",
        )
    )

    thread_id = os.environ.get("CODEX_THREAD_ID")
    checks.append(
        check(
            "codex_thread_id",
            bool(thread_id),
            f"CODEX_THREAD_ID={thread_id or 'unset'}",
            required=args.strict_runtime,
            remediation="Run the doctor from a Codex shell turn so CODEX_THREAD_ID is injected.",
        )
    )

    chrome = Path("/Applications/Google Chrome.app").exists() or Path.home().joinpath(
        "Applications/Google Chrome.app"
    ).exists()
    safari = Path("/Applications/Safari.app").exists()
    chatgpt_app = Path("/Applications/ChatGPT.app").exists() or Path.home().joinpath(
        "Applications/ChatGPT.app"
    ).exists()
    checks.append(
        check(
            "chatgpt_surface",
            chrome or safari or chatgpt_app,
            f"chrome={chrome}, safari={safari}, chatgpt_app={chatgpt_app}",
            remediation="Install Google Chrome or the ChatGPT macOS app.",
        )
    )

    directory_specs = {
        "state_store": Path(
            os.environ.get("COLLAB_STATE_ROOT", "~/.codex/collaboration/tasks")
        ).expanduser(),
        "event_store": Path(
            os.environ.get("COLLAB_EVENT_ROOT", "~/.codex/collaboration/events")
        ).expanduser(),
        "wake_store": Path(
            os.environ.get("COLLAB_WAKE_ROOT", "~/.codex/collaboration/wakes")
        ).expanduser(),
        "log_store": Path(
            os.environ.get("COLLAB_LOG_ROOT", "~/.codex/collaboration/logs")
        ).expanduser(),
    }
    for name, path in directory_specs.items():
        ok, detail = writable_directory(path)
        checks.append(
            check(
                name,
                ok,
                detail,
                remediation="Make ~/.codex/collaboration writable.",
            )
        )

    # These declarations are advisory only. The capability handshake is the
    # source of truth for ChatGPT transport and executor capabilities.
    runtime_vars = {
        "chatgpt_transport_declaration": os.environ.get("COLLAB_CHATGPT_TRANSPORT"),
        "chatgpt_executor_declaration": os.environ.get("COLLAB_CHATGPT_EXECUTOR"),
    }
    for name, value in runtime_vars.items():
        available = value in {"1", "true", "available", "yes"}
        checks.append(
            check(
                name,
                available,
                f"declaration={value or 'unset'}",
                required=False,
                remediation="Use capability handshake as the authoritative runtime check.",
            )
        )

    if args.repo:
        repo = Path(args.repo).expanduser().resolve()
        repo_ok = repo.is_dir() and run(
            "git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"
        ).returncode == 0
        checks.append(
            check(
                "repository",
                repo_ok,
                str(repo),
                remediation="Provide a valid local Git checkout.",
            )
        )
        if repo_ok:
            remote = run("git", "-C", str(repo), "ls-remote", args.remote)
            checks.append(
                check(
                    "github_remote",
                    remote.returncode == 0,
                    remote.stderr.strip() or f"remote={args.remote} reachable",
                    remediation="Fix GitHub authentication, remote URL, or network access.",
                )
            )

    failures = [item for item in checks if item["status"] == "fail"]
    warnings = [item for item in checks if item["status"] == "warn"]
    payload = {
        "ready": not failures,
        "target": "macOS 13+ event-driven resume",
        "architecture": arch,
        "checks": checks,
        "failure_count": len(failures),
        "warning_count": len(warnings),
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
