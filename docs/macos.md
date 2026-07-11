# macOS Runtime Guide

This skill targets macOS 13 or newer. Linux, Windows, and WSL are out of scope.

## Supported Environment

- macOS Ventura 13+
- Apple Silicon or Intel
- Python 3.9+
- Git 2.30+
- Xcode Command Line Tools
- Codex CLI with:
  - `app-server`
  - `exec resume`
  - native goal support
- `CODEX_THREAD_ID` available inside Codex shell commands
- a configured GitHub remote
- Codex local checkout and command execution
- ChatGPT conversation transport
- ChatGPT `local_full` or `github_connector` profile

ChatGPT does not need a local shell when GitHub connector can create a candidate commit and Codex can verify it locally.

## Setup

```sh
xcode-select --install
python3 --version
git --version
codex --version
codex app-server --help
codex exec resume --help
```

Resolve the installed Skill root:

```sh
SKILL_ROOT="$HOME/.agents/skills/chatgpt-codex-collaboration"
```

Run bundled scripts with absolute paths.

## Doctor

Run from a Codex shell turn so `CODEX_THREAD_ID` is available:

```sh
sh "$SKILL_ROOT/scripts/macos-doctor.sh" \
  --strict-runtime \
  --repo /absolute/path/to/repository \
  --remote origin
```

The doctor checks:

- macOS and architecture;
- Python, Git, and Xcode tools;
- launchd, AppleScript, and browser surface;
- Codex CLI, app-server, and exec resume;
- `CODEX_THREAD_ID`;
- task, event, wake, and log directories;
- repository and GitHub connectivity;
- declared ChatGPT transport and executor capabilities.

Capability handshake remains the source of truth for the actual ChatGPT executor profile.

## Capability State

Save a validated handshake:

```sh
sh "$SKILL_ROOT/scripts/task-state.sh" set-executor \
  TASK-001 \
  --file /path/to/handshake.json
```

Accepted profiles:

- `local_full`
- `github_connector`

Do not dispatch `read_only` or `none`.

## Prepare the Remote Branch

Before dispatch:

```sh
sh "$SKILL_ROOT/scripts/prepare-handoff-branch.sh" \
  /absolute/path/to/repository \
  origin \
  chatgpt/TASK-001 \
  <base-sha>
```

The command creates a missing remote branch and verifies that its HEAD equals the recorded base SHA.

Do not dispatch when this gate fails.

## Strict Handoff Receipt

ChatGPT final output must conform to:

```text
contracts/handoff-receipt.schema.json
```

Validate an extracted receipt:

```sh
sh "$SKILL_ROOT/scripts/validate-handoff-receipt.sh" \
  /path/to/handoff-receipt.json
```

A completed receipt without a commit SHA is invalid.

For `github_connector`, tests may be `not_run`, but a real candidate commit is still mandatory.

## Start Event-Driven Wait

After the task contract has been sent successfully:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" start \
  TASK-001 \
  chatgpt/TASK-001 \
  <base-sha> \
  --repo /absolute/path/to/repository \
  --remote origin \
  --dispatch-epoch <unix-epoch>
```

The command:

1. verifies or creates the remote handoff branch;
2. reads `CODEX_THREAD_ID`;
3. temporarily pauses the same native goal through app-server;
4. installs a per-task LaunchAgent;
5. records wake configuration;
6. returns immediately.

End the current Codex turn after `start` succeeds.

Do **not** run `macos-watcher.sh await`. Blocking await is disabled because the execution platform may terminate long-running commands after several minutes.

## What Runs While Codex Sleeps

The LaunchAgent runs `event-supervisor.py` and monitors:

- remote branch HEAD;
- ChatGPT terminal-event JSONL;
- the browser-use CDP transport when browser transport arguments are supplied;
- observation lease.

Git polling starts at 60 seconds and backs off to 300 seconds. No LLM is invoked.

Files:

```text
~/Library/LaunchAgents/com.backtrue.chatgpt-codex.<task-id>.plist
~/.codex/collaboration/events/<task-id>.jsonl
~/.codex/collaboration/wakes/<task-id>.json
~/.codex/collaboration/logs/<task-id>.out.log
~/.codex/collaboration/logs/<task-id>.err.log
~/.codex/collaboration/logs/<task-id>.codex-resume.log
```

## Automatic Resume

When the remote branch advances or a terminal transport event appears, the supervisor:

1. restores the same native goal to `active`;
2. runs:

   ```text
   codex exec --json resume <CODEX_THREAD_ID> <event prompt>
   ```

3. continues the same persisted Codex thread;
4. validates the candidate or executes transport recovery.

Event-specific wake locks prevent duplicate resume.

If resume fails:

- the same goal returns to `paused`;
- a macOS notification is shown;
- the resume log is preserved;
- the wake lock is removed so the event can be retried.

## ChatGPT Terminal Events

The transport adapter writes JSONL under:

```text
~/.codex/collaboration/events/<task-id>.jsonl
```

Example invalid completion:

```sh
sh "$SKILL_ROOT/scripts/transport-event.sh" emit \
  TASK-001 conversation_completed_no_commit \
  --source chatgpt-ui \
  --reason "ChatGPT completed without a valid candidate commit SHA"
```

Other terminal events:

- `implementation_blocked`
- `capability_rejected`
- `conversation_failed`
- `transport_unreachable`
- `mode_drifted`

A valid branch commit wakes Codex directly; no UI event is required.

## Browser-use ChatGPT Transport

The formal web path uses the bundled browser-use adapter. Pass these values to
`macos-watcher.sh start` after the capability handshake and before ending the current
Codex turn:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" start \
  TASK-001 chatgpt/TASK-001 <base-sha> \
  --repo /absolute/path/to/repository \
  --remote origin \
  --executor-profile github_connector \
  --browser-script "$SKILL_ROOT/scripts/browser-use-transport.py" \
  --conversation-url https://chatgpt.com/c/<approved-conversation-id> \
  --prompt-file /absolute/path/to/task-contract.txt \
  --dispatch-id task-001-dispatch-1 \
  --message-fingerprint <sha256-of-prompt>
```

The adapter opens the approved conversation, confirms plain `Chat` mode, sends the
prompt once, and observes the response through Chrome CDP. It writes terminal events
to `~/.codex/collaboration/events/<task-id>.jsonl`. It does not use `computer-use`,
`screencapture`, or `osascript` for waiting. If CDP is unavailable, it emits
`transport_unreachable` and stops; it does not retry the prompt.

## Inspect and Stop

Inspect:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" status TASK-001
```

Stop and leave the native goal unchanged:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" stop TASK-001
```

Stop and reactivate the same goal:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" stop \
  TASK-001 \
  --resume-goal
```

## Recover a Legacy Blocking Wait

1. update the Skill;
2. stop the stale LaunchAgent and reactivate the same goal;
3. migrate existing task state;
4. rerun capability handshake;
5. verify the remote branch at base SHA;
6. reject any previous ChatGPT response without a commit SHA;
7. redispatch with the strict receipt;
8. start event-driven wait.

Do not create a replacement goal.

## macOS Permissions

The ChatGPT transport adapter may require Automation or Accessibility permission for Terminal, Codex, the browser runtime, or AppleScript.

Grant only the minimum required permission. Do not grant Full Disk Access merely to bypass a failed gate.

## Known Boundary

This repository provides goal control, branch preparation, state, contracts, the browser-use ChatGPT transport adapter, event supervisor, session wakeup, and verifier workflow.

A complete installation still needs a running Chrome/Chromium CDP session with the approved ChatGPT conversation available. The adapter must:

1. open the approved conversation;
2. confirm Chat mode;
3. send and parse capability handshake;
4. send profile-aware task contracts;
5. parse the strict handoff receipt;
6. emit terminal events for invalid, blocked, or failed responses.
7. keep the browser observer outside active Codex model turns.
