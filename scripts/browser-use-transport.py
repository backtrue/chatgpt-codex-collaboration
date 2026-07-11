"""Deterministic ChatGPT browser transport executed by the browser-use CLI.

The file is intentionally run as a browser-use program, not as a standalone
Python module. The browser-use runner provides page_info, new_tab, ensure_real_tab,
js, cdp, and click_at_xy.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


TERMINAL_FAILURES = {
    "mode_drifted",
    "transport_unreachable",
}


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing_{name.lower()}")
    return value


def integer_env(name: str, default: int, minimum: int = 1) -> int:
    value = int(os.environ.get(name, str(default)))
    if value < minimum:
        raise RuntimeError(f"invalid_{name.lower()}")
    return value


def emit(event_type: str, reason: str, **payload: object) -> None:
    task_id = required("COLLAB_TASK_ID")
    event_root = Path(
        os.environ.get("COLLAB_EVENT_ROOT", "~/.codex/collaboration/events")
    ).expanduser()
    event_root.mkdir(parents=True, exist_ok=True)
    path = event_root / f"{task_id}.jsonl"
    event = {
        "schema_version": "2.0",
        "event_id": str(uuid.uuid4()),
        "task_id": task_id,
        "event_type": event_type,
        "source": "chatgpt-ui",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "payload": {
            "reason": reason,
            "dispatch_id": os.environ.get("COLLAB_DISPATCH_ID", ""),
            "message_fingerprint": os.environ.get(
                "COLLAB_MESSAGE_FINGERPRINT", ""
            ),
            **payload,
        },
    }
    with path.open("a", encoding="utf-8") as handle:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    print(f"transport_event={event_type} task_id={task_id}", flush=True)


def visible_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def page_state() -> dict[str, object]:
    result = js(
        """
        (() => {
          const visible = (node) => {
            if (!node) return false;
            const style = getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' &&
              rect.width > 0 && rect.height > 0;
          };
          const text = (node) => (node.innerText || node.textContent || '').trim();
          const controls = [...document.querySelectorAll('button,[role="button"]')]
            .filter(visible).map(text).filter(Boolean);
          const composer = document.querySelector(
            'textarea, [contenteditable="true"], [role="textbox"]'
          );
          const assistants = [...document.querySelectorAll(
            '[data-message-author-role="assistant"]'
          )].map(text).filter(Boolean);
          return JSON.stringify({
            controls,
            composer: Boolean(composer && visible(composer)),
            assistant_count: assistants.length,
            last_assistant: assistants[assistants.length - 1] || '',
            generating: controls.some((value) => /stop generating|停止生成/i.test(value)),
            page_title: document.title || ''
          });
        })()
        """
    )
    if isinstance(result, dict):
        return result
    try:
        decoded = json.loads(str(result))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid_browser_state:{exc}") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("invalid_browser_state_shape")
    return decoded


def ensure_chat_mode(state: dict[str, object]) -> None:
    controls = state.get("controls")
    control_values = controls if isinstance(controls, list) else []
    normalized = {str(value).strip().lower() for value in control_values}
    forbidden = {"work", "task", "scheduled task", "project", "canvas"}
    if normalized.intersection(forbidden):
        raise RuntimeError("mode_drifted")
    expected = os.environ.get("CHATGPT_MODE_TEXT", "chat").strip().lower()
    if expected not in normalized:
        raise RuntimeError("mode_not_confirmed")


def open_conversation() -> None:
    url = required("CHATGPT_CONVERSATION_URL")
    new_tab(url)
    ensure_real_tab()


def send_message(prompt: str) -> None:
    state = page_state()
    ensure_chat_mode(state)
    if not state.get("composer"):
        raise RuntimeError("composer_not_found")
    composer_rect = js(
        """
        (() => {
          const node = document.querySelector(
            'textarea, [contenteditable="true"], [role="textbox"]'
          );
          if (!node) return null;
          const rect = node.getBoundingClientRect();
          return JSON.stringify({x: rect.left + rect.width / 2, y: rect.top + rect.height / 2});
        })()
        """
    )
    if isinstance(composer_rect, str):
        composer_rect = json.loads(composer_rect)
    if not isinstance(composer_rect, dict):
        raise RuntimeError("composer_coordinates_missing")
    click_at_xy(float(composer_rect["x"]), float(composer_rect["y"]))
    cdp("Input.insertText", {"text": prompt})
    cdp(
        "Input.dispatchKeyEvent",
        {
            "type": "keyDown",
            "key": "Enter",
            "code": "Enter",
            "windowsVirtualKeyCode": 13,
            "nativeVirtualKeyCode": 13,
        },
    )
    cdp(
        "Input.dispatchKeyEvent",
        {
            "type": "keyUp",
            "key": "Enter",
            "code": "Enter",
            "windowsVirtualKeyCode": 13,
            "nativeVirtualKeyCode": 13,
        },
    )


def remote_branch_advanced() -> bool:
    repo = required("COLLAB_REPO")
    remote = os.environ.get("COLLAB_REMOTE", "origin")
    branch = required("COLLAB_BRANCH")
    base_sha = required("COLLAB_BASE_SHA").lower()
    result = subprocess.run(
        ["git", "ls-remote", "--heads", remote, f"refs/heads/{branch}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError("remote_unreachable")
    line = next((item for item in result.stdout.splitlines() if item.strip()), "")
    return bool(line and line.split()[0].lower() != base_sha)


def fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def main() -> None:
    if os.environ.get("CHATGPT_BROWSER_DRY_RUN") == "1":
        print("browser_transport_dry_run=pass", flush=True)
        return

    prompt_path = Path(required("CHATGPT_PROMPT_FILE")).expanduser().resolve()
    prompt = prompt_path.read_text(encoding="utf-8")
    expected = os.environ.get("COLLAB_MESSAGE_FINGERPRINT")
    if expected and expected != fingerprint(prompt):
        raise RuntimeError("message_fingerprint_mismatch")

    try:
        open_conversation()
        baseline = page_state()
        ensure_chat_mode(baseline)
        send_message(prompt)
    except RuntimeError as exc:
        event = str(exc)
        emit(
            event if event in TERMINAL_FAILURES else "transport_unreachable",
            event,
        )
        return

    lease_seconds = integer_env("COLLAB_LEASE_SECONDS", 7200)
    poll_seconds = integer_env("COLLAB_POLL_SECONDS", 60)
    max_poll_seconds = integer_env("COLLAB_MAX_POLL_SECONDS", 300)
    started = time.monotonic()
    current_poll = poll_seconds
    unchanged = 0
    baseline_count = int(baseline.get("assistant_count") or 0)

    while time.monotonic() - started < lease_seconds:
        time.sleep(current_poll)
        try:
            state = page_state()
            ensure_chat_mode(state)
        except RuntimeError as exc:
            event = str(exc)
            emit(
                event if event in TERMINAL_FAILURES else "transport_unreachable",
                event,
            )
            return

        assistant_count = int(state.get("assistant_count") or 0)
        if assistant_count > baseline_count and not state.get("generating"):
            if remote_branch_advanced():
                emit("conversation_completed", "assistant_completed_branch_pending")
            else:
                emit("conversation_completed_no_commit", "assistant_completed_without_remote_commit")
            return

        unchanged += 1
        if unchanged >= 5:
            current_poll = min(max_poll_seconds, max(current_poll + 1, int(current_poll * 1.5)))
            unchanged = 0

    emit("transport_unreachable", "browser_observation_lease_expired")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emit("transport_unreachable", str(exc))
