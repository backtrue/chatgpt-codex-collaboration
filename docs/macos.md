# macOS Runtime Guide

This skill intentionally targets macOS only. Linux, Windows, and WSL are out of scope for the first implementation.

## Supported Environment

- macOS Ventura 13 or newer
- Apple Silicon (`arm64`) or Intel (`x86_64`)
- Python 3.9 or newer
- Git 2.30 or newer
- Xcode Command Line Tools
- Codex CLI with native goal tools
- A configured GitHub remote with push access
- A ChatGPT conversation transport and code executor available to Codex

The orchestration scripts use `/bin/sh` only as a thin entrypoint. All non-trivial logic runs in Python, so Homebrew Bash and GNU coreutils are not required.

## Initial Setup

Run:

```sh
xcode-select --install
python3 --version
git --version
codex --version
```

When Python 3.9+ is missing, install it with Homebrew or pyenv. Ensure the selected `python3` is visible in the same PATH used by Codex and `launchd`.

## Doctor

Run before using the skill:

```sh
./scripts/macos-doctor.sh --repo /absolute/path/to/repository
```

The doctor checks:

- macOS version and architecture;
- Python and Git versions;
- Xcode Command Line Tools;
- `launchctl`, `osascript`, and `open`;
- Codex CLI presence;
- a usable ChatGPT browser or app surface;
- writable collaboration state storage;
- optional repository and GitHub remote connectivity.

Runtime-only capabilities cannot be proven by the operating system alone. The skill verifies native goal tools by calling `get_goal`; it verifies ChatGPT transport and executor capabilities before dispatch.

For an installation test that requires explicit runtime declarations:

```sh
COLLAB_NATIVE_GOAL_TOOLS=available \
COLLAB_CHATGPT_TRANSPORT=available \
COLLAB_CHATGPT_EXECUTOR=available \
./scripts/macos-doctor.sh --strict-runtime --repo /absolute/path/to/repository
```

Only set these declarations after the corresponding capability actually exists.

## Background Watcher

Use the macOS watcher manager instead of leaving a terminal loop running:

```sh
./scripts/macos-watcher.sh start TASK-001 chatgpt/TASK-001 <base-sha> \
  --repo /absolute/path/to/repository \
  --remote origin \
  --dispatch-epoch <unix-epoch>
```

The manager creates a per-task LaunchAgent under:

```text
~/Library/LaunchAgents/com.backtrue.chatgpt-codex.<task-id>.plist
```

Logs are written under:

```text
~/.codex/collaboration/logs/
```

Inspect or stop it with:

```sh
./scripts/macos-watcher.sh status TASK-001
./scripts/macos-watcher.sh stop TASK-001
```

The watcher does not invoke an LLM. It polls only the assigned Git remote branch and exits when a candidate commit appears, the observation lease expires, or it is stopped.

## macOS Permissions

A fully automated ChatGPT transport may require macOS Automation or Accessibility permission for the terminal, Codex application, browser automation runtime, or `osascript` adapter. Grant only the minimum required applications.

Do not grant Full Disk Access merely to bypass a failed preflight. Repository and state directories should be explicitly accessible without broad system privileges.

## Known Boundary

The Mac-specific scripts solve operating-system portability and watcher persistence. They do not create the ChatGPT browser adapter or code executor by themselves. The workflow remains `BLOCKED_TRANSPORT` or `BLOCKED_CAPABILITY` until the Codex runtime can:

1. open and inspect the approved ChatGPT conversation;
2. send a task in Chat mode;
3. let ChatGPT edit, test, commit, and push the assigned branch.
