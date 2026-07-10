# Collaboration Architecture

```text
Codex verifier/orchestrator
  ├─ Control plane: approved ChatGPT conversation
  ├─ State store: ~/.codex/collaboration/tasks/*.json
  ├─ Dependency and capability preflight
  └─ Data plane: assigned GitHub branch
          ↑
ChatGPT implementer through the configured executor
```

## 1. Transport Layer

The control plane sends task and repair contracts and observes ChatGPT mode, generation state, completion, and terminal errors. The data plane carries source code, commits, diffs, and test evidence through GitHub.

Required UI adapter operations:

- `open_conversation(url)`
- `detect_mode()`
- `send_message(dispatch_id, message_fingerprint, content)`
- `detect_generation_state()`
- `read_last_completed_message()`
- `detect_terminal_error()`

The adapter must refuse non-Chat modes, reject duplicate dispatch IDs, and never send a status prompt while generation is active. UI completion is only a control signal. A remote Git commit is the handoff evidence.

Use a webhook when available. Otherwise use `scripts/wait-for-handoff.sh`. Polling must not invoke an LLM.

## 2. Execution Layer

The executor provides the workspace in which ChatGPT edits code and runs commands. Its capabilities and restrictions are declared in `config/executor.example.yaml`.

Lifecycle:

1. Resolve a clean checkout or isolated worktree.
2. Fetch the configured remote.
3. Create the assigned branch from the recorded base SHA.
4. Restrict writes to allowed paths.
5. Run task-specific commands.
6. Commit and push only a candidate handoff.
7. Return commit SHA, changed files, command results, and blockers.

Prohibited behavior includes base-branch writes, force-push, secret reads, unapproved paths, silent package installation, and claiming success without a remote commit.

## 3. State Machine

Normal path:

`DISCOVERING → READY → DISPATCHING → IMPLEMENTING → WAITING_HANDOFF → HANDOFF_CANDIDATE → VERIFYING → ACCEPTED`

Repair path:

`VERIFYING → REPAIR_REQUIRED → WAITING_REPAIR → HANDOFF_CANDIDATE → VERIFYING`

Blocked states:

- `BLOCKED_SPEC`
- `BLOCKED_CAPABILITY`
- `BLOCKED_DEPENDENCY`
- `BLOCKED_TRANSPORT`
- `BLOCKED_OBSERVATION`
- `BLOCKED_USER`

Only `VERIFYING` may transition to `ACCEPTED`. Observation lease expiry is not failure. Use `scripts/task-state.sh` to persist and validate transitions outside the worktree.

## 4. Dependency Contract

`dependencies.yaml` declares required commands, capabilities, conditional skills, contracts, and fallbacks. Missing required dependencies produce `BLOCKED_DEPENDENCY`; they must not be replaced by improvised checks.

Conditional spec skills become mandatory only when repo-local instructions require them:

- `spec-discovery-gate`
- `spec-task-audit-list`
- `spec-acceptance-audit`

## Recovery

- On restart, read persisted state and do not redispatch automatically.
- Restart an interrupted watcher with the original dispatch epoch.
- If the UI completes without a push, send one focused commit-and-push repair request.
- If branch validation fails, preserve evidence and transition to `REPAIR_REQUIRED`.
- If a dependency is missing, transition to `BLOCKED_DEPENDENCY` rather than weakening acceptance.
