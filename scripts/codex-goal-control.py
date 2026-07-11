#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import time
from typing import Any

ALLOWED_STATUSES = {
    "active",
    "paused",
    "blocked",
    "usageLimited",
    "budgetLimited",
    "complete",
}


class AppServerError(RuntimeError):
    pass


class AppServerClient:
    def __init__(self, codex: str, cwd: Path, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self.proc = subprocess.Popen(
            [codex, "app-server", "--listen", "stdio://"],
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        if self.proc.stdin is None or self.proc.stdout is None:
            raise AppServerError("failed to open app-server stdio")
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)
        self.next_id = 1
        self._initialize()

    def _write(self, payload: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def _read_response(self, request_id: int) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        assert self.proc.stdout is not None
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                stderr = ""
                if self.proc.stderr is not None:
                    stderr = self.proc.stderr.read()[-4000:]
                raise AppServerError(
                    f"app-server exited before response id={request_id}: {stderr}"
                )
            events = self.selector.select(max(0.0, deadline - time.monotonic()))
            if not events:
                break
            line = self.proc.stdout.readline()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise AppServerError(json.dumps(message["error"], ensure_ascii=False))
            result = message.get("result")
            if not isinstance(result, dict):
                raise AppServerError(f"invalid app-server response: {message!r}")
            return result
        raise AppServerError(f"app-server request timed out id={request_id}")

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        payload: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._write(payload)
        return self._read_response(request_id)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        self._write(payload)

    def _initialize(self) -> None:
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "chatgpt_codex_collaboration",
                    "title": "ChatGPT-Codex Collaboration",
                    "version": "1.0.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        self.notify("initialized")

    def close(self) -> None:
        try:
            self.selector.close()
        except Exception:
            pass
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)


def resolve_codex(explicit: str | None) -> str:
    if explicit:
        path = shutil.which(explicit) if os.path.sep not in explicit else explicit
    else:
        path = shutil.which("codex")
    if not path:
        raise AppServerError("codex executable not found")
    return str(Path(path).expanduser().resolve())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read or update a persisted Codex thread goal without invoking a model"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    get_parser = sub.add_parser("get")
    get_parser.add_argument("thread_id")

    set_parser = sub.add_parser("set")
    set_parser.add_argument("thread_id")
    set_parser.add_argument("status", choices=sorted(ALLOWED_STATUSES))

    for child in (get_parser, set_parser):
        child.add_argument("--cwd", default=os.getcwd())
        child.add_argument("--codex")
        child.add_argument("--timeout-seconds", type=float, default=20.0)

    args = parser.parse_args()
    client: AppServerClient | None = None
    try:
        codex = resolve_codex(args.codex)
        cwd = Path(args.cwd).expanduser().resolve()
        client = AppServerClient(codex, cwd, args.timeout_seconds)
        if args.command == "get":
            result = client.request("thread/goal/get", {"threadId": args.thread_id})
        else:
            result = client.request(
                "thread/goal/set",
                {"threadId": args.thread_id, "status": args.status},
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"error={exc}", file=sys.stderr)
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
