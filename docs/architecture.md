# Collaboration Architecture — macOS First

```text
Native Codex thread goal (/goal)
  │
  │  objective, status, budget, automatic continuation
  ▼
Codex verifier/orchestrator on macOS
  ├─ Goal gate: get_goal / create_goal / update_goal
  ├─ Environment gate: macos-doctor.py
  ├─ Control plane: approved ChatGPT conversation
  ├─ State store: ~/.codex/collaboration/tasks/*.json
  ├─ launchd watcher: ~/Library/LaunchAgents/*.plist
  └─ Data plane: assigned GitHub branch
          ↑
ChatGPT implementer through the configured macOS executor
```

The native Codex thread goal is the only top-level objective authority. This repository manages finite implementation tasks beneath it; it does not create a competing goal planner.

The first supported operating environment is macOS 13 or newer on Apple Silicon or Intel. Linux, Windows, and WSL are intentionally unsupported until a later portability phase.

## 1. Native Goal Layer

Before task discovery, Codex calls `get_goal`.

- Active unfinished goal: bind the collaboration task to its `goal_id` and preserve the full objective.
- No goal or completed goal: create a new active goal from the user's actual requested end state.
- Paused, blocked, usage-limited, or budget-limited goal: do not replace it; resume only through an authorized native goal-control action.
- Conflicting active goal: block rather than silently replace or edit it.

Each task state records the goal ID, objective, status, optional token budget, whether the skill created it, and bind time.

After every accepted finite task, Codex audits the complete goal. If every requirement is proven, it calls `update_goal(status="complete")`. Otherwise it leaves the goal active and returns control to the native continuation runtime.

## 2. macOS Environment Layer

`scripts/macos-doctor.py` verifies the local operating environment before orchestration begins:

- macOS 13+ and supported architecture;
- Python 3.9+ and Git 2.30+;
- Xcode Command Line Tools;
- `launchctl`, `osascript`, and `open`;
- Codex CLI and a ChatGPT browser or app surface;
- writable state storage;
- optional repository and GitHub remote connectivity.

The system shell is not an execution dependency beyond thin `/bin/sh` wrappers. Python owns version comparison, JSON output, branch polling, validation, and state operations. Homebrew Bash and GNU coreutils are not required.

## 3. Transport Layer

The control plane sends goal-bound task and repair contracts and observes ChatGPT mode, generation state, completion, and terminal errors. The data plane carries source code, commits, diffs, and test evidence through GitHub.

Required ChatGPT adapter operations:

- `open_conversation(url)`
- `detect_mode()`
- `send_message(dispatch_id, message_fingerprint, content)`
- `detect_generation_state()`
- `read_last_completed_message()`
- `detect_terminal_error()`

The adapter must refuse non-Chat modes, reject duplicate dispatch IDs, and never send a status prompt while generation is active. UI completion is only a control signal. A remote Git commit is the handoff evidence.

macOS Automation or Accessibility permission may be required by the selected browser adapter. The adapter must request the minimum permission necessary and must not depend on Full Disk Access.

## 4. Execution Layer

The executor provides the local macOS workspace in which ChatGPT edits code and runs commands. Its capabilities and restrictions are declared in `config/executor.example.yaml`.

Lifecycle:

1. Resolve a clean checkout or isolated Git worktree.
2. Fetch the configured remote.
3. Create the assigned branch from the recorded base SHA.
4. Restrict writes to allowed paths.
5. Run task-specific commands.
6. Commit and push only a candidate handoff.
7. Return parent goal ID, commit SHA, changed files, command results, and blockers.

Prohibited behavior includes base-branch writes, force-push, secret reads, unapproved paths, silent package installation, claiming success without a remote commit, and narrowing the native goal to fit the current task.

## 5. launchd Observation Layer

`scripts/macos-watcher.py` creates a per-task LaunchAgent. This separates waiting from Codex reasoning and prevents a watcher from depending on an open terminal or active model turn.

The LaunchAgent:

- runs `wait-for-handoff.py` in the repository working directory;
- preserves the original dispatch epoch;
- writes stdout and stderr under `~/.codex/collaboration/logs`;
- exits when a candidate commit appears, the lease expires, or it is stopped;
- never invokes an LLM.

The completion gate must stop and remove the task LaunchAgent.

## 6. Collaboration Task State Machine

Normal finite-task path:

`DISCOVERING → READY → DISPATCHING → IMPLEMENTING → WAITING_HANDOFF → HANDOFF_CANDIDATE → VERIFYING → ACCEPTED`

Repair path:

`VERIFYING → REPAIR_REQUIRED → WAITING_REPAIR → HANDOFF_CANDIDATE → VERIFYING`

Blocked states:

- `BLOCKED_GOAL`
- `BLOCKED_SPEC`
- `BLOCKED_CAPABILITY`
- `BLOCKED_DEPENDENCY`
- `BLOCKED_TRANSPORT`
- `BLOCKED_OBSERVATION`
- `BLOCKED_USER`

Only `VERIFYING` may transition the finite collaboration task to `ACCEPTED`. Observation lease expiry is not failure. `ACCEPTED` means only that the finite task passed; it does not change the native goal status.

Use `scripts/task-state.sh` to persist and validate transitions outside the worktree.

## 7. Dependency Contract

`dependencies.yaml` declares the macOS platform target, required commands, native goal capabilities, executor capabilities, conditional skills, contracts, and fallbacks.

The automated workflow requires native `get_goal`, `create_goal`, and `update_goal` tools. Missing goal support produces `BLOCKED_GOAL`; the skill must not emulate goal persistence only in conversation text.

Conditional spec skills become mandatory only when repo-local instructions require them:

- `spec-discovery-gate`
- `spec-task-audit-list`
- `spec-acceptance-audit`

## 8. Goal-Bound Contracts

`contracts/collaboration.schema.json` requires:

- parent native goal ID;
- full goal objective;
- the finite task's contribution to the goal;
- goal-bound handoff and acceptance results;
- evidence of which goal requirements advanced;
- remaining goal work.

This allows the native goal continuation to resume from evidence rather than a prose claim that the task is done.

## Recovery

- On restart, call `get_goal` before loading collaboration task state.
- Resume only when the persisted and native goal IDs match.
- Do not redispatch an existing task automatically.
- Inspect the per-task LaunchAgent and restart it with the original dispatch epoch only when necessary.
- If the UI completes without a push, send one focused commit-and-push repair request.
- If branch validation fails, preserve evidence and transition to `REPAIR_REQUIRED`.
- If the native goal is missing, changed, or non-active, transition to `BLOCKED_GOAL`.
- If a dependency is missing, transition to `BLOCKED_DEPENDENCY` rather than weakening acceptance.
