# Collaboration Architecture — macOS Event-Driven Resume

```text
Native Codex /goal
  │
  ▼
Codex verifier/orchestrator on macOS
  ├─ Environment Gate
  ├─ Goal Gate
  ├─ Capability Handshake
  ├─ Remote Branch Preparation
  ├─ Profile-aware Task Contract
  ├─ Task State: ~/.codex/collaboration/tasks/*.json
  ├─ Transport Events: ~/.codex/collaboration/events/*.jsonl
  ├─ launchd Event Supervisor
  ├─ codex app-server goal suspension / reactivation
  ├─ codex exec resume <CODEX_THREAD_ID>
  └─ Local Acceptance Runner
          ▲
          │ GitHub branch / candidate commit
          ▼
ChatGPT implementer
  ├─ local_full
  └─ github_connector
```

The native Codex thread goal is the only top-level objective authority. This repository manages finite implementation tasks beneath it.

## 1. Native Goal Layer

Codex calls `get_goal` before task discovery.

- Bind an active unfinished goal and preserve its ID and complete objective.
- Create a goal only when none exists or the previous goal is complete.
- Do not replace unrelated paused, blocked, usage-limited, budget-limited, or conflicting goals.
- Audit the complete goal after every accepted task.

Task blockers do not authorize native goal blocking.

### Temporary transport suspension

Long external ChatGPT work must not keep an active Codex turn open and must not leave the native goal active while the thread is idle.

After dispatch, the watcher manager uses the local app-server `thread/goal/set` API to temporarily set the same goal to `paused`. This is a transport suspension, not a failure status.

On a terminal event, the supervisor restores the same goal to `active` and resumes the same persisted thread through:

```text
codex exec resume <CODEX_THREAD_ID> <event prompt>
```

The goal ID and objective never change during suspension.

## 2. macOS Environment Layer

`macos-doctor.py` verifies:

- macOS 13+ and supported architecture;
- Python 3.9+ and Git 2.30+;
- Xcode Command Line Tools;
- `launchctl`, `osascript`, and `open`;
- Codex CLI;
- `codex app-server`;
- `codex exec resume`;
- `CODEX_THREAD_ID` when strict runtime mode is enabled;
- writable task, event, wake, and log stores;
- local repository and GitHub remote connectivity.

Codex is the verifier and therefore requires a complete local checkout and local command execution.

## 3. Capability Layer

Before implementation dispatch, ChatGPT returns a machine-readable capability handshake.

### `local_full`

ChatGPT has local checkout, shell, focused checks, commit, and push.

```text
implementation_validation_policy = implementer_required
candidate_commit_without_tests = false
```

### `github_connector`

ChatGPT can read, edit, commit, and push through a GitHub connector but has no local shell.

```text
implementation_validation_policy = deferred_to_codex
candidate_commit_without_tests = true
require_precreated_remote_branch = true
```

ChatGPT marks unavailable commands `not_run`; Codex runs all required acceptance locally.

### `read_only` and `none`

No candidate commit can be created. The task enters `BLOCKED_CAPABILITY` before an event supervisor starts.

## 4. Remote Branch Preparation Layer

Before dispatch, Codex runs:

```sh
prepare-handoff-branch.sh <repo> <remote> <branch> <base-sha>
```

The preparation gate:

1. verifies the local base commit;
2. verifies remote connectivity;
3. creates a missing remote branch with an exact non-force push;
4. confirms remote branch HEAD equals the recorded base SHA;
5. rejects stale or unexpected branch heads.

A local branch name is not proof that a GitHub connector can write the branch.

## 5. Control Plane

The control plane opens the approved ChatGPT conversation through the bundled browser-use CDP adapter, verifies Chat mode, sends handshake and task contracts, reads completed responses, and emits terminal transport events. The adapter runs as a non-LLM background process; Codex is resumed only after a terminal event or remote branch movement.

Required adapter operations:

- `open_conversation(url)`
- `detect_mode()`
- `send_message(dispatch_id, fingerprint, content)`
- `detect_generation_state()`
- `read_last_completed_message()`
- `parse_capability_handshake()`
- `parse_handoff_receipt()`
- `emit_transport_event()`
- `detect_terminal_error()`

The formal web transport is `scripts/browser-use-transport.sh`. It performs one
dispatch, then observes the same conversation without sending status or repair prompts.
Normal mode uses DOM and CDP state. If Chrome CDP is unavailable, it emits
`transport_unreachable` instead of falling back to repeated screenshot or `osascript`
inspection.

A completed UI response is not a code handoff.

## 6. Strict Handoff Receipt Layer

ChatGPT's final implementation response must conform to `contracts/handoff-receipt.schema.json`.

A completed receipt requires:

- `status=completed`;
- a non-null 40-character `commit_sha`;
- at least one changed file;
- no blockers;
- an allowed verification status.

A blocked receipt requires:

- `status=blocked`;
- `commit_sha=null`;
- at least one explicit blocker;
- `verification_status=blocked`.

The following is invalid and must generate `conversation_completed_no_commit`:

```text
verification_status = pending_codex_verification
all tests = not_run
blockers = none
commit_sha = missing
```

## 7. Data Plane

GitHub carries:

- assigned remote branch;
- base SHA;
- candidate SHA;
- changed files;
- implementer test evidence or `not_run` results;
- verification status.

For a valid commit, branch movement is the primary wake signal.

## 8. Event Supervisor Layer

`macos-watcher.sh start` is the formal wait entrypoint.

It performs:

1. remote branch preparation and verification;
2. `CODEX_THREAD_ID` capture;
3. temporary native-goal pause via app-server;
4. LaunchAgent creation;
5. wake configuration persistence;
6. immediate return from the current Codex turn.

The LaunchAgent runs `event-supervisor.py`.

The supervisor monitors:

- assigned remote branch HEAD;
- local transport event JSONL;
- observation lease.

Git polling starts at 60 seconds and backs off to 300 seconds. No model is invoked while waiting.

## 9. Event-Driven Resume Layer

When a terminal event occurs, `wake-codex.py`:

1. acquires an event-specific idempotency lock;
2. reactivates the same native goal through app-server;
3. runs `codex exec --json resume <thread-id> <event prompt>`;
4. continues the same task in the same persisted Codex thread;
5. logs the resumed run;
6. pauses the goal again and sends a macOS notification if resume fails.

Blocking `await` is disabled. The design does not depend on a command surviving longer than the platform's tool timeout.

## 10. Terminal Transport Events

The ChatGPT adapter writes events under:

```text
~/.codex/collaboration/events/<task-id>.jsonl
```

Terminal events include:

- `implementation_blocked`
- `capability_rejected`
- `conversation_completed_no_commit`
- `conversation_failed`
- `transport_unreachable`
- `mode_drifted`

A valid Git candidate does not require a separate transport event because branch movement wakes Codex directly.

## 11. State Machine

Normal task:

```text
DISCOVERING
→ CAPABILITY_CHECK
→ READY
→ DISPATCHING
→ IMPLEMENTING
→ WAITING_HANDOFF
→ HANDOFF_CANDIDATE
→ VERIFYING
→ ACCEPTED
```

Capability drift:

```text
WAITING_HANDOFF
→ implementation_blocked
→ CAPABILITY_CHECK
→ github_connector downgrade or BLOCKED_CAPABILITY
```

Protocol failure:

```text
WAITING_HANDOFF
→ conversation_completed_no_commit
→ focused commit request or CAPABILITY_CHECK
```

Repair:

```text
VERIFYING
→ REPAIR_REQUIRED
→ WAITING_REPAIR
→ HANDOFF_CANDIDATE
→ VERIFYING
```

Only `VERIFYING` may transition a finite task to `ACCEPTED`.

## 12. Acceptance Layer

Codex always performs independent acceptance.

For `local_full`, Codex reruns focused and required regression checks.

For `github_connector`, Codex runs all commands because implementer validation was deferred.

Acceptance covers:

- authoritative specification alignment;
- changed-file scope;
- focused tests;
- typecheck, lint, and required regression tests;
- browser behavior when required;
- boundary and error paths;
- security and forbidden fallback behavior.

## 13. Failure and Recovery

- If branch preparation fails, no task is dispatched.
- If ChatGPT returns no commit, the response is protocol failure rather than a valid waiting state.
- If automatic Codex resume fails, the goal is returned to paused and a macOS notification is emitted.
- Wake locks are removed on failed resume so the same event can be retried.
- Legacy blocking-await LaunchAgents must be stopped and recreated with event-driven `start`.
- Goal ID and objective remain stable throughout recovery.
