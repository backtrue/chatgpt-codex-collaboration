#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def run(*args: str, cwd: Path | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False, timeout=timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description="macOS repository execution preflight")
    parser.add_argument("repository_path")
    parser.add_argument("remote")
    parser.add_argument("branch")
    parser.add_argument("required_commands", nargs="*")
    args = parser.parse_args()

    repo = Path(args.repository_path).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if sys.platform != "darwin":
        errors.append("unsupported-platform:requires-macos")
    if not repo.is_dir():
        errors.append("repository-path-missing")
    elif run("git", "rev-parse", "--is-inside-work-tree", cwd=repo).returncode != 0:
        errors.append("not-a-git-worktree")

    if not errors:
        if run("git", "remote", "get-url", args.remote, cwd=repo).returncode != 0:
            errors.append(f"missing-remote:{args.remote}")
        if run("git", "check-ref-format", "--branch", args.branch).returncode != 0:
            errors.append(f"invalid-branch:{args.branch}")
        status = run("git", "status", "--porcelain", cwd=repo)
        if status.returncode != 0:
            errors.append("git-status-failed")
        elif status.stdout.strip():
            errors.append("worktree-not-clean")
        if run("git", "ls-remote", args.remote, cwd=repo).returncode != 0:
            errors.append("remote-unreachable-or-auth-failed")
        if run("git", "show-ref", "--verify", "--quiet", f"refs/heads/{args.branch}", cwd=repo).returncode == 0:
            warnings.append(f"local-branch-exists:{args.branch}")

    for command in args.required_commands:
        if not any(os.access(Path(path) / command, os.X_OK) for path in os.environ.get("PATH", "").split(os.pathsep)):
            errors.append(f"missing-command:{command}")

    result = {"ready": not errors, "platform": sys.platform, "repository": str(repo), "errors": errors, "warnings": warnings}
    print(json.dumps(result, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
