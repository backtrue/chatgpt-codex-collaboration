#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
import re
import subprocess

SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
FORBIDDEN = ["*.zip", "*.tar", "*.tar.gz", "*.tgz", "*.pem", "*.key", ".env", "*/.env", "*.tmp", "*.swp"]


def run(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=repo, text=True, capture_output=True, check=False, timeout=timeout)


def allowed(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/") and path.startswith(pattern):
            return True
        if path == pattern or fnmatch.fnmatch(path, pattern):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a GitHub handoff candidate")
    parser.add_argument("repo_path")
    parser.add_argument("remote")
    parser.add_argument("branch")
    parser.add_argument("base_sha")
    parser.add_argument("candidate_sha")
    parser.add_argument("allowed_paths", nargs="+")
    args = parser.parse_args()

    repo = Path(args.repo_path).expanduser().resolve()
    errors: list[str] = []
    changed: list[str] = []

    if not SHA_RE.fullmatch(args.base_sha):
        errors.append("invalid-base-sha")
    if not SHA_RE.fullmatch(args.candidate_sha):
        errors.append("invalid-candidate-sha")
    if not repo.is_dir():
        errors.append("repository-path-missing")

    if not errors:
        remote_result = run(repo, "git", "ls-remote", "--heads", args.remote, f"refs/heads/{args.branch}")
        if remote_result.returncode != 0:
            errors.append("remote-unreachable-or-auth-failed")
            remote_sha = ""
        else:
            line = next((line for line in remote_result.stdout.splitlines() if line.strip()), "")
            remote_sha = line.split()[0] if line else ""
        if not remote_sha:
            errors.append("remote-branch-missing")
        elif remote_sha.lower() != args.candidate_sha.lower():
            errors.append("candidate-not-current-remote-head")
        if args.candidate_sha.lower() == args.base_sha.lower():
            errors.append("candidate-equals-base-sha")

        if run(repo, "git", "cat-file", "-e", f"{args.candidate_sha}^{{commit}}").returncode != 0:
            fetch = run(repo, "git", "fetch", "--quiet", args.remote, args.branch)
            if fetch.returncode != 0:
                errors.append("candidate-fetch-failed")
        diff = run(repo, "git", "diff", "--name-only", args.base_sha, args.candidate_sha)
        if diff.returncode != 0:
            errors.append("diff-failed")
        else:
            changed = [line for line in diff.stdout.splitlines() if line]

    for path in changed:
        if not allowed(path, args.allowed_paths):
            errors.append(f"out-of-scope:{path}")
        if any(fnmatch.fnmatch(path, pattern) for pattern in FORBIDDEN):
            errors.append(f"forbidden-artifact:{path}")

    print(json.dumps({"valid": not errors, "changed_files": changed, "errors": errors}, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
