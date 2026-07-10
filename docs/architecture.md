# Collaboration Architecture — macOS First

```text
Native Codex thread goal (/goal)
  │
  │ objective / status / budget / continuation
  ▼
Codex verifier/orchestrator on macOS
  ├─ Goal gate: get_goal / create_goal / update_goal
  ├─ Environment gate: macos-doctor.py
  ├─ Control plane: approved ChatGPT conversation
  ├─ State store: ~/.codex/collaboration/tasks/*.json
  ├─ launchd Git watcher
  ├─ local blocking await
  └─ Data plane: assigned GitHub branch
          ↑
ChatGPT implementer through the configured macOS executor
```

The native Codex thread goal is the only top-level objective authority. This repository manages finite implementation tasks beneath it; it does not create a competing goal planner.

The first supported environment is macOS 13 or newer on Apple Silicon or Intel.

## 1. Native Goal Layer

Before task discovery, Codex calls `get_goal`.

- Active unfinished goal: bind to its `goal_id` and preserve the full objective.
- No goal or completed goal: create a new active goal from the user's requested end state.
- Paused, blocked, usage-limited, or budget-limited goal: do not replace it.
- Conflicting active goal: block rather than silently replace or edit it.

Task state records the goal ID, objective, status, token budget, creation source, and bind time.

After every accepted finite task, Codex audits the complete goal. It calls `update_goal(status="complete")` only when every requirement is proven.

## 2. macOS Environment Layer

`macos-doctor.py` verifies:

- macOS 13+ and supported architecture;
- Python 3.9+ and Git 2.30+;
- Xcode Command Line Tools;
- `launchctl`, `osascript`, and `open`;
- Codex CLI and a ChatGPT surface;
- writable collaboration state;
- repository and GitHub connectivity when provided.

Python owns version comparison, JSON output, state, branch polling, and validation. `/bin/sh` is only a thin wrapper. Homebrew Bash and GNU coreutils are not required.

## 3. Transport Layer

The control plane sends goal-bound task and repair contracts and observes ChatGPT mode, generation state, completion, and terminal errors.

The data plane carries source code, commits, diffs, and test evidence through GitHub.

Required ChatGPT adapter operations:

- `open_conversation(url)`
- `detect_mode()`
- `send_message(dispatch_id, message_fingerprint, content)`
- `detect_generation_state()`
- `read_last_completed_message()`
- `detect_terminal_error()`

The adapter must reject non-Chat modes and duplicate dispatch IDs. UI completion is only a control signal; a remote Git commit is the handoff evidence.

## 4. Execution Layer

The executor provides the local macOS worktree where ChatGPT edits code and runs commands.

Lifecycle:

1. Resolve a clean checkout or isolated worktree.
2. Fetch the configured remote.
3. Create the assigned branch from base SHA.
4. Restrict writes to allowed paths.
5. Run task-specific commands.
6. Commit and push only a candidate handoff.
7. Return goal ID, commit SHA, changed files, command results, and blockers.

Prohibited behavior includes base-branch writes, force-push, secret reads, unapproved paths, silent package installation, and narrowing the native goal to fit the current task.

## 5. Low-Token Observation Layer

### The problem

A Git watcher that runs `git ls-remote` does not itself consume model tokens. The larger risk is native `/goal` continuation.

When the goal is active and the Codex thread becomes idle, the goal runtime may start another turn. If the workflow ends each turn with “still waiting,” it can create a repeated model loop.

### Two-layer wait

The workflow therefore uses two distinct processes:

```text
launchd watcher
  └─ checks the assigned Git branch

current Codex turn
  └─ blocks in local await and reads only watcher logs
```

The LaunchAgent:

- runs `wait-for-handoff.py` in the repository working directory;
- preserves dispatch epoch;
- writes logs under `~/.codex/collaboration/logs`;
- starts at 60-second Git polling;
- progressively backs off after unchanged polls;
- caps polling at 300 seconds;
- exits on candidate commit, lease expiry, or interrupt;
- never invokes an LLM.

After starting it, Codex synchronously runs:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" await <task-id>
```

The await process:

- reads only local logs;
- performs no GitHub requests;
- invokes no LLM;
- keeps the current Codex turn active;
- returns only on a terminal watcher event.

This prevents the thread from becoming idle merely because the external ChatGPT implementation is still running.

If the command runner forces a timeout but the LaunchAgent remains healthy, Codex re-enters await in the same turn. Repeated short command timeouts must not be converted into repeated goal continuation turns.

## 6. Collaboration Task State Machine

Normal task:

`DISCOVERING → READY → DISPATCHING → IMPLEMENTING → WAITING_HANDOFF → HANDOFF_CANDIDATE → VERIFYING → ACCEPTED`

Repair:

`VERIFYING → REPAIR_REQUIRED → WAITING_REPAIR → HANDOFF_CANDIDATE → VERIFYING`

Blocked states:

- `BLOCKED_GOAL`
- `BLOCKED_SPEC`
- `BLOCKED_CAPABILITY`
- `BLOCKED_DEPENDENCY`
- `BLOCKED_TRANSPORT`
- `BLOCKED_OBSERVATION`
- `BLOCKED_USER`

Only `VERIFYING` may transition a finite task to `ACCEPTED`. `ACCEPTED` does not change native goal status.

## 7. Dependency Contract

`dependencies.yaml` declares the macOS target, required commands, native goal capabilities, executor capabilities, conditional skills, contracts, and fallbacks.

The workflow requires native `get_goal`, `create_goal`, and `update_goal` tools. Missing goal support produces `BLOCKED_GOAL`.

Repository-required discovery and acceptance skills must not be silently approximated.

## 8. Goal-Bound Contracts

The collaboration schema requires:

- parent native goal ID;
- full goal objective;
- finite task contribution;
- goal-bound handoff and acceptance results;
- evidence of advanced requirements;
- remaining goal work.

This lets native goal continuation resume from evidence instead of a prose claim.

## Recovery

- Resolve the absolute Skill root before running bundled scripts.
- Call `get_goal` before loading task state.
- Resume only when persisted and native goal IDs match.
- Do not redispatch automatically.
- Inspect the LaunchAgent and log before creating a new watcher.
- If a watcher is active, block in local await rather than ending the turn.
- Preserve original dispatch epoch when recreating a watcher.
- Enter `BLOCKED_OBSERVATION` when the environment cannot provide a stable low-token wait.
