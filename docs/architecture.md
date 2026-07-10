# Collaboration Architecture — macOS First

```text
Native Codex /goal
  │
  ▼
Codex verifier/orchestrator on macOS
  ├─ Environment Gate
  ├─ Goal Gate
  ├─ Capability Handshake
  ├─ Profile-aware Task Contract
  ├─ State Store: ~/.codex/collaboration/tasks/*.json
  ├─ launchd Git watcher
  ├─ Transport Events: ~/.codex/collaboration/events/*.jsonl
  ├─ Blocking local await
  └─ Local acceptance runner
          ▲
          │ GitHub branch / commit
          ▼
ChatGPT implementer
  ├─ local_full
  └─ github_connector
```

The native Codex thread goal is the only top-level objective authority. This repository manages finite implementation tasks beneath it.

## 1. Native Goal Layer

Codex calls `get_goal` before task discovery.

- Bind an active unfinished goal and preserve its objective.
- Create a goal only when none exists or the previous goal is complete.
- Do not replace paused, blocked, usage-limited, budget-limited, or conflicting goals.
- Audit the full goal after each accepted task.

## 2. macOS Environment Layer

`macos-doctor.py` verifies macOS, Python, Git, Xcode Command Line Tools, Codex CLI, launchd, ChatGPT surface, state storage, and optional GitHub connectivity.

Codex is the verifier and therefore requires:

- a complete local repository checkout;
- local command execution;
- access to the assigned remote branch.

The ChatGPT implementer does not always require a local shell.

## 3. Capability Layer

Before implementation dispatch, ChatGPT returns a machine-readable handshake.

### `local_full`

ChatGPT has local checkout, shell, acceptance commands, commit, and push.

```text
implementation_validation_policy = implementer_required
candidate_commit_without_tests = false
```

### `github_connector`

ChatGPT has repository read/write and branch commit through GitHub connector, but no local checkout or shell.

```text
implementation_validation_policy = deferred_to_codex
candidate_commit_without_tests = true
```

ChatGPT produces a candidate commit and marks unavailable commands `not_run`. Codex runs every required acceptance command locally.

### `read_only` and `none`

No candidate commit can be created. The task enters `BLOCKED_CAPABILITY` before a watcher starts.

The handshake prevents impossible contracts such as requiring local tests from a connector-only executor while also forbidding any remote verification path.

## 4. Control Plane

The control plane opens the approved ChatGPT conversation, verifies Chat mode, sends handshake and task contracts, reads completed responses, and emits terminal transport events.

Required adapter operations:

- `open_conversation(url)`
- `detect_mode()`
- `send_message(dispatch_id, fingerprint, content)`
- `detect_generation_state()`
- `read_last_completed_message()`
- `parse_capability_handshake()`
- `emit_transport_event()`
- `detect_terminal_error()`

A completed UI response is not a code handoff. A remote commit is required.

## 5. Data Plane

GitHub carries:

- assigned branch;
- base SHA;
- candidate SHA;
- changed files;
- implementer test evidence or `not_run` results;
- verification status.

`pending_codex_verification` is expected for `github_connector` handoffs.

## 6. Execution Layer

The implementer lifecycle depends on profile.

### Local full

1. Resolve local checkout.
2. Edit allowed paths.
3. Run implementer-required checks.
4. Commit and push candidate.

### GitHub connector

1. Read assigned branch through connector.
2. Edit allowed paths.
3. Commit candidate through connector.
4. Mark local commands `not_run`.
5. Return `pending_codex_verification`.

Prohibited behavior includes base-branch writes, force-push, secret reads, unrelated paths, and claiming acceptance.

## 7. Low-Token Observation Layer

The launchd watcher checks branch HEAD without invoking an LLM. Polling begins at 60 seconds and backs off to 300 seconds.

Codex then blocks the current turn in local `await`, which reads:

1. Git watcher logs; and
2. ChatGPT transport event JSONL.

This prevents active `/goal` from repeatedly opening continuation turns during an external wait.

## 8. Terminal Transport Event Layer

The adapter writes events under:

```text
~/.codex/collaboration/events/<task-id>.jsonl
```

Terminal events include:

- `implementation_blocked`
- `conversation_completed_no_commit`
- `conversation_failed`
- `transport_unreachable`
- `mode_drifted`

The local await stops the Git watcher and returns immediately when one appears.

This prevents the deadlock:

```text
Implementer cannot create commit
→ verifier waits only for commit
→ no terminal condition is observed
```

## 9. State Machine

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

Repair:

```text
VERIFYING
→ REPAIR_REQUIRED
→ WAITING_REPAIR
→ HANDOFF_CANDIDATE
→ VERIFYING
```

Only `VERIFYING` may transition a finite task to `ACCEPTED`.

## 10. Acceptance Layer

Codex always performs independent acceptance.

For `local_full`, Codex reruns focused and required regression checks.

For `github_connector`, Codex runs all commands because implementer validation was deferred.

Acceptance covers spec alignment, changed scope, tests, typecheck, lint, browser behavior, error paths, and security requirements.

## 11. Recovery

- Resolve the absolute Skill root.
- Run Mac Doctor.
- Read native goal before task state.
- Restore the saved executor handshake.
- Do not reuse a profile disproved by a runtime blocker.
- Read watcher and transport event logs before redispatching.
- Do not start a watcher before capability readiness.
