# macOS Runtime Guide

This skill targets macOS 13 or newer. Linux, Windows, and WSL are out of scope for the first implementation.

## Supported Environment

- macOS Ventura 13+
- Apple Silicon or Intel
- Python 3.9+
- Git 2.30+
- Xcode Command Line Tools
- Codex CLI with native Goal tools
- a configured GitHub remote
- Codex local checkout and command execution
- ChatGPT conversation transport
- at least one accepted ChatGPT executor profile

Accepted ChatGPT profiles:

- `local_full`
- `github_connector`

ChatGPT does not need a local shell when GitHub connector can create a candidate commit and Codex can verify it locally.

## Setup

```sh
xcode-select --install
python3 --version
git --version
codex --version
```

Resolve the installed Skill root:

```sh
SKILL_ROOT="$HOME/.agents/skills/chatgpt-codex-collaboration"
```

Run bundled scripts with absolute paths.

## Doctor

```sh
sh "$SKILL_ROOT/scripts/macos-doctor.sh" \
  --repo /absolute/path/to/repository \
  --remote origin
```

The doctor verifies the Mac and Codex verifier environment. ChatGPT executor capabilities are verified separately through the runtime capability handshake.

## Capability State

Save a validated handshake:

```sh
sh "$SKILL_ROOT/scripts/task-state.sh" set-executor \
  TASK-001 \
  --file /path/to/handshake.json
```

Example handshake:

```text
$SKILL_ROOT/config/capability-handshake.example.json
```

Do not start a watcher for `read_only` or `none` profiles.

## Background Git Watcher

Start only after capability readiness and task dispatch:

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

Git watcher logs:

```text
~/.codex/collaboration/logs/
```

The watcher invokes no LLM and backs off from 60 to 300 seconds.

## ChatGPT Terminal Events

The transport adapter writes JSONL events under:

```text
~/.codex/collaboration/events/<task-id>.jsonl
```

Example blocker:

```sh
sh "$SKILL_ROOT/scripts/transport-event.sh" emit \
  TASK-001 implementation_blocked \
  --source chatgpt-ui \
  --code NO_LOCAL_EXECUTOR \
  --reason "No local checkout or shell is available"
```

Other terminal events:

- `conversation_completed_no_commit`
- `conversation_failed`
- `transport_unreachable`
- `mode_drifted`

## Blocking Await

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" await \
  TASK-001 \
  --timeout-seconds 7500
```

Await reads both:

- local Git watcher output;
- local ChatGPT transport events.

It performs no GitHub request and invokes no LLM. A terminal ChatGPT event stops the Git watcher and returns control immediately.

This prevents both token-heavy `/goal` continuation loops and capability deadlocks.

## Inspect and Stop

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" status TASK-001
sh "$SKILL_ROOT/scripts/macos-watcher.sh" stop TASK-001
```

The completion and blocker gates must stop and remove the LaunchAgent.

## macOS Permissions

A ChatGPT transport adapter may require Automation or Accessibility permission for the terminal, Codex application, browser runtime, or `osascript` adapter.

Grant only the minimum required permission. Do not grant Full Disk Access merely to bypass a failed gate.

## Known Boundary

The repository provides the contracts, state, event channel, watcher, and verifier workflow. A complete installation still needs a ChatGPT transport adapter that can:

1. open the approved conversation;
2. confirm Chat mode;
3. send and parse the capability handshake;
4. send profile-aware task contracts;
5. emit terminal events from completed ChatGPT responses.
