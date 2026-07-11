#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
TASK_RE = re.compile(r"^[A-Za-z0-9._-]+$")
VALID_PROFILES = {"local_full", "github_connector"}
VALID_TEST_STATUS = {"passed", "failed", "timed_out", "not_run"}


def validate(data: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["receipt-must-be-json-object"]

    required = {
        "schema_version",
        "task_id",
        "status",
        "executor_profile",
        "branch",
        "base_sha",
        "commit_sha",
        "changed_files",
        "test_results",
        "verification_status",
        "blockers",
    }
    missing = sorted(required.difference(data))
    errors.extend(f"missing-field:{field}" for field in missing)
    if missing:
        return errors

    if data["schema_version"] != "1.0":
        errors.append("invalid-schema-version")
    if not isinstance(data["task_id"], str) or not TASK_RE.fullmatch(data["task_id"]):
        errors.append("invalid-task-id")
    if data["status"] not in {"completed", "blocked"}:
        errors.append("invalid-status")
    if data["executor_profile"] not in VALID_PROFILES:
        errors.append("invalid-executor-profile")
    if not isinstance(data["branch"], str) or not data["branch"]:
        errors.append("invalid-branch")
    if not isinstance(data["base_sha"], str) or not SHA_RE.fullmatch(data["base_sha"]):
        errors.append("invalid-base-sha")
    if not isinstance(data["changed_files"], list) or not all(
        isinstance(item, str) and item for item in data["changed_files"]
    ):
        errors.append("invalid-changed-files")
    if not isinstance(data["blockers"], list) or not all(
        isinstance(item, str) and item for item in data["blockers"]
    ):
        errors.append("invalid-blockers")
    if not isinstance(data["test_results"], list):
        errors.append("invalid-test-results")
    else:
        for index, item in enumerate(data["test_results"]):
            if not isinstance(item, dict):
                errors.append(f"invalid-test-result:{index}")
                continue
            if not isinstance(item.get("command"), str) or not item.get("command"):
                errors.append(f"invalid-test-command:{index}")
            if item.get("status") not in VALID_TEST_STATUS:
                errors.append(f"invalid-test-status:{index}")

    status = data["status"]
    commit_sha = data["commit_sha"]
    verification_status = data["verification_status"]
    if status == "completed":
        if not isinstance(commit_sha, str) or not SHA_RE.fullmatch(commit_sha):
            errors.append("completed-receipt-requires-commit-sha")
        if not data["changed_files"]:
            errors.append("completed-receipt-requires-changed-files")
        if data["blockers"]:
            errors.append("completed-receipt-must-have-no-blockers")
        if verification_status not in {
            "implementer_verified",
            "pending_codex_verification",
        }:
            errors.append("invalid-completed-verification-status")
    elif status == "blocked":
        if commit_sha is not None:
            errors.append("blocked-receipt-commit-sha-must-be-null")
        if not data["blockers"]:
            errors.append("blocked-receipt-requires-blocker")
        if verification_status != "blocked":
            errors.append("blocked-receipt-verification-status-must-be-blocked")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a ChatGPT handoff receipt")
    parser.add_argument("receipt_file")
    args = parser.parse_args()

    path = Path(args.receipt_file).expanduser().resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"valid": False, "errors": [f"read-failed:{exc}"]}, indent=2))
        return 2

    errors = validate(data)
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
