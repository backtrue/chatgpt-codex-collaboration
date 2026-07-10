# Collaboration Architecture

```text
Native Codex thread goal (/goal)
  │
  │  objective, status, budget, automatic continuation
  ▼
Codex verifier/orchestrator
  ├─ Goal gate: get_goal / create_goal / update_goal
  ├─ Control plane: approved ChatGPT conversation
  ├─ State store: ~/.codex/collaboration/tasks/*.json
  ├─ Dependency and capability preflight
  └─ Data plane: assigned GitHub branch
          ↑
ChatGPT implementer through the configured executor
```

The native Codex thread goal is the only top-level objective authority. This repository manages finite implementation tasks beneath it; it does not create a competing goal planner.

## 1. Native Goal Layer

Before task discovery, Codex calls `get_goal`.

- Active unfinished goal: bind the collaboration task to its `goal_id` and preserve the full objective.
- No goal or completed goal: create a new active goal from the user's actual requested end state.
- Paused, blocked, usage-limited, or budget-limited goal: do not replace it; resume only through an authorized native goal-control action.
- Conflicting active goal: block rather than silently replace or edit it.

Each task state records the goal ID, objective, status, optional token budget, whether the skill created it, and bind time.

After every accepted finite task, Codex audits the complete goal. If every requirement is proven, it calls `update_goal(status="complete")`. Otherwise it leaves the goal active and returns control to the native continuation runtime.

## 2. Transport Layer

The control plane sends goal-bound task and repair contracts and observes ChatGPT mode, generation state, completion, and terminal errors. The data plane carries source code, commits, diffs, and test evidence through GitHub.

Required UI adapter operations:

- `open_conversation(url)`
- `detect_mode()`
- `send_message(dispatch_id, message_fingerprint, content)`
- `detect_generation_state()`
- `read_last_completed_message()`
- `detect_terminal_error()`

The adapter must refuse non-Chat modes, reject duplicate dispatch IDs, and never send a status prompt while generation is active. UI completion is only a control signal. A remote Git commit is the handoff evidence.

Use a webhook when available. Otherwise use `scripts/wait-for-handoff.sh`. Polling must not invoke an LLM.

## 3. Execution Layer

The executor provides the workspace in which ChatGPT edits code and runs commands. Its capabilities and restrictions are declared in `config/executor.example.yaml`.

Lifecycle:

1. Resolve a clean checkout or isolated worktree.
2. Fetch the configured remote.
3. Create the assigned branch from the recorded base SHA.
4. Restrict writes to allowed paths.
5. Run task-specific commands.
6. Commit and push only a candidate handoff.
7. Return parent goal ID, commit SHA, changed files, command results, and blockers.

Prohibited behavior includes base-branch writes, force-push, secret reads, unapproved paths, silent package installation, claiming success without a remote commit, and narrowing the native goal to fit the current task.

## 4. Collaboration Task State Machine

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

## 5. Dependency Contract

`dependencies.yaml` declares required commands, native goal capabilities, executor capabilities, conditional skills, contracts, and fallbacks.

The automated workflow requires native `get_goal`, `create_goal`, and `update_goal` tools. Missing goal support produces `BLOCKED_GOAL`; the skill must not emulate goal persistence only in conversation text.

Conditional spec skills become mandatory only when repo-local instructions require them:

- `spec-discovery-gate`
- `spec-task-audit-list`
- `spec-acceptance-audit`

## 6. Goal-Bound Contracts

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
- Restart an interrupted watcher with the original dispatch epoch.
- If the UI completes without a push, send one focused commit-and-push repair request.
- If branch validation fails, preserve evidence and transition to `REPAIR_REQUIRED`.
- If the native goal is missing, changed, or non-active, transition to `BLOCKED_GOAL`.
- If a dependency is missing, transition to `BLOCKED_DEPENDENCY` rather than weakening acceptance.
