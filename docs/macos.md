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

The shell wrappers use `/bin/sh`; all non-trivial logic runs in Python. Homebrew Bash and GNU coreutils are not required.

Resolve `SKILL_ROOT` to the directory containing the installed `SKILL.md` and run bundled scripts with absolute paths.

## Initial Setup

```sh
xcode-select --install
python3 --version
git --version
codex --version
```

Ensure the selected `python3` is visible in the PATH used by both Codex and launchd.

## Doctor

```sh
SKILL_ROOT="$HOME/.agents/skills/chatgpt-codex-collaboration"

sh "$SKILL_ROOT/scripts/macos-doctor.sh" \
  --repo /absolute/path/to/repository \
  --remote origin
```

The doctor checks:

- macOS version and architecture;
- Python and Git versions;
- Xcode Command Line Tools;
- `launchctl`, `osascript`, and `open`;
- Codex CLI;
- a usable ChatGPT surface;
- writable collaboration state;
- optional repository and GitHub connectivity.

Runtime-only capabilities are verified by their corresponding gates rather than environment variables alone.

## Background Git Watcher

Start a per-task LaunchAgent:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" start \
  TASK-001 \
  chatgpt/TASK-001 \
  <base-sha> \
  --repo /absolute/path/to/repository \
  --remote origin \
  --dispatch-epoch <unix-epoch>
```

The LaunchAgent is stored under:

```text
~/Library/LaunchAgents/com.backtrue.chatgpt-codex.<task-id>.plist
```

Logs are stored under:

```text
~/.codex/collaboration/logs/
```

Git polling behavior:

- starts at 60 seconds;
- progressively backs off after unchanged checks;
- caps at 300 seconds;
- emits only state changes and terminal events;
- invokes no LLM.

## Blocking Await

Starting a background watcher alone is not sufficient for low-token waiting when native `/goal` remains active. If the current Codex turn ends, the goal runtime may start another continuation turn.

Immediately after starting the watcher, block the current Codex turn:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" await \
  TASK-001 \
  --timeout-seconds 7500
```

The await command:

- reads only the local watcher output log;
- performs no GitHub requests;
- invokes no LLM;
- keeps the current Codex turn active;
- returns on candidate commit, lease expiry, interrupt, or watcher failure.

If the command layer times out while the LaunchAgent is still healthy, run `await` again in the same Codex turn. Do not end the turn with a prose “still waiting” response.

If the environment repeatedly enforces very short blocking-command timeouts, enter `BLOCKED_OBSERVATION` rather than allowing an active `/goal` continuation loop. Keep the watcher running and use an authorized `/goal pause` until the workflow can resume safely.

## Inspect and Stop

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" status TASK-001
sh "$SKILL_ROOT/scripts/macos-watcher.sh" stop TASK-001
```

The completion gate must stop and remove the LaunchAgent.

## macOS Permissions

A fully automated ChatGPT transport may require macOS Automation or Accessibility permission for the terminal, Codex application, browser runtime, or `osascript` adapter.

Grant only the minimum required applications. Do not grant Full Disk Access merely to bypass a failed preflight.

## Known Boundary

The Mac-specific scripts solve operating-system portability, background Git observation, and low-token blocking wait. They do not create the ChatGPT browser adapter or code executor by themselves.

The workflow remains `BLOCKED_TRANSPORT` or `BLOCKED_CAPABILITY` until the runtime can:

1. open and inspect the approved ChatGPT conversation;
2. send a task in Chat mode;
3. let ChatGPT edit, test, commit, and push the assigned branch.
