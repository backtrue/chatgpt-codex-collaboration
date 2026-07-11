#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def run(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def remote_head(repo: Path, remote: str, branch: str) -> tuple[int, str | None, str]:
    result = run(
        repo,
        "git",
        "ls-remote",
        "--heads",
        remote,
        f"refs/heads/{branch}",
    )
    if result.returncode != 0:
        return result.returncode, None, result.stderr.strip()
    line = next((line for line in result.stdout.splitlines() if line.strip()), "")
    return 0, (line.split()[0] if line else None), ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create and verify the remote branch used for ChatGPT handoff"
    )
    parser.add_argument("repo_path")
    parser.add_argument("remote")
    parser.add_argument("branch")
    parser.add_argument("base_sha")
    parser.add_argument(
        "--allow-existing-different-head",
        action="store_true",
        help="Allow an already-existing branch whose head differs from base SHA.",
    )
    args = parser.parse_args()

    repo = Path(args.repo_path).expanduser().resolve()
    errors: list[str] = []
    created = False

    if not repo.is_dir():
        errors.append("repository-path-missing")
    if not SHA_RE.fullmatch(args.base_sha):
        errors.append("invalid-base-sha")
    if run(repo, "git", "rev-parse", "--is-inside-work-tree").returncode != 0:
        errors.append("not-a-git-worktree")
    if run(repo, "git", "check-ref-format", "--branch", args.branch).returncode != 0:
        errors.append("invalid-branch")
    if run(repo, "git", "remote", "get-url", args.remote).returncode != 0:
        errors.append("missing-remote")
    if run(repo, "git", "cat-file", "-e", f"{args.base_sha}^{{commit}}").returncode != 0:
        errors.append("base-sha-not-local-commit")

    head: str | None = None
    if not errors:
        code, head, detail = remote_head(repo, args.remote, args.branch)
        if code != 0:
            errors.append(f"remote-unreachable:{detail}")
        elif head is None:
            push = run(
                repo,
                "git",
                "push",
                args.remote,
                f"{args.base_sha}:refs/heads/{args.branch}",
                timeout=120,
            )
            if push.returncode != 0:
                errors.append(f"remote-branch-create-failed:{push.stderr.strip()}")
            else:
                created = True
                code, head, detail = remote_head(repo, args.remote, args.branch)
                if code != 0:
                    errors.append(f"remote-branch-verify-failed:{detail}")
        if head is not None and head.lower() != args.base_sha.lower():
            if not args.allow_existing_different_head:
                errors.append(
                    f"remote-branch-head-mismatch:expected={args.base_sha}:actual={head}"
                )

    ready = not errors and head is not None
    print(
        json.dumps(
            {
                "ready": ready,
                "created": created,
                "remote": args.remote,
                "branch": args.branch,
                "base_sha": args.base_sha,
                "remote_head": head,
                "errors": errors,
            },
            indent=2,
        )
    )
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
