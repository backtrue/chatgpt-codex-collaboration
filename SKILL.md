---
name: chatgpt-codex-collaboration
description: Coordinate a macOS-first, goal-bound two-agent coding workflow in which ChatGPT implements one scoped task through either a full local executor or a GitHub connector, while Codex independently verifies the candidate against authoritative specifications. Use when ChatGPT should perform most implementation work, Codex should minimize token use and focus on planning and acceptance, or a long-running Codex /goal must survive external ChatGPT handoffs without deadlocks, false blockers, or polling loops.
---

# ChatGPT-Codex Collaboration

Use this skill to separate implementation from acceptance:

- Native Codex `/goal` owns the complete objective.
- ChatGPT implements one finite, goal-aligned task at a time.
- Codex owns task definition, authoritative specification, acceptance, and repair decisions.
- GitHub branch and commit SHA are the code handoff boundary.
- The user resolves undefined product behavior and explicit goal changes.

ChatGPT must not accept its own work. Codex must not silently implement a repair assigned to ChatGPT. A ChatGPT completion message without a remote commit is not a handoff.

This version supports macOS 13 or newer only.

## Resolve Bundled Resources

Resolve `SKILL_ROOT` to the absolute directory containing this `SKILL.md`. Run scripts with absolute paths:

```sh
sh "$SKILL_ROOT/scripts/<script>.sh" ...
```

Important resources:

- `contracts/collaboration.schema.json`
- `dependencies.yaml`
- `config/executor.example.yaml`
- `scripts/macos-doctor.sh`
- `scripts/preflight.sh`
- `scripts/task-state.sh`
- `scripts/transport-event.sh`
- `scripts/macos-watcher.sh`
- `scripts/recover-capability.sh`
- `scripts/validate-handoff.sh`
- `docs/native-goal-safety.md`
- `docs/capability-handshake.md`
- `docs/architecture.md`
- `docs/macos.md`

Persist task state under `~/.codex/collaboration/tasks`.

## 1. Native Goal Safety Invariant

The native goal and the collaboration task are separate state machines.

A task entering any of these states does **not** authorize changing native goal status:

- `CAPABILITY_CHECK`
- `WAITING_HANDOFF`
- `BLOCKED_CAPABILITY`
- `BLOCKED_TRANSPORT`
- `BLOCKED_OBSERVATION`
- `BLOCKED_SPEC`
- `BLOCKED_USER`
- `REPAIR_REQUIRED`

Therefore:

- Never call `update_goal(status="blocked")` merely because the current collaboration task is blocked.
- Never issue `/goal pause` automatically.
- Never clear or replace the goal to escape a task-level blocker.
- Never repeat “goal remains blocked” status turns after a recoverable executor or transport issue.

The native goal may be marked blocked only when all are true:

1. the same blocker persists across at least three consecutive native goal turns;
2. no executor downgrade, transport fallback, repair, or local verification path exists;
3. no meaningful progress is possible without user input or external-state change;
4. the blocker applies to the complete goal, not only the current task;
5. exact evidence is preserved.

Missing ChatGPT local checkout or shell does not satisfy this rule when GitHub connector commits remain available.

Read `docs/native-goal-safety.md` before mutating native goal status.

## 2. macOS Environment Gate

Before goal or task work:

1. Confirm macOS 13+ on `arm64` or `x86_64`.
2. Run:

   ```sh
   sh "$SKILL_ROOT/scripts/macos-doctor.sh" \
     --repo <absolute-repo-path> --remote <remote>
   ```

3. Treat doctor failures as hard environment blocks.
4. Require Codex to have a complete local repository checkout and command execution for final acceptance.
5. Do not automatically install packages, widen permissions, or request Full Disk Access.

## 3. Native Goal Gate

1. Call `get_goal`.
2. Preserve an active goal's `goal_id` and full objective.
3. If no goal exists or the previous goal is complete, call `create_goal` using the user's requested end state and authoritative specifications. Do not shrink the goal to the first task.
4. If the goal is paused or blocked because an older version of this skill incorrectly changed it:
   - preserve the same goal ID and objective;
   - do not create a replacement goal;
   - request one native `/goal resume` action;
   - after resume, recover the task with `recover-capability.sh` and rerun the handshake.
5. If a paused, blocked, usage-limited, or budget-limited goal is unrelated to this workflow, do not override it.
6. Record goal binding in task state.
7. Before each implementation or repair dispatch, confirm the same active goal still governs the work.

Task acceptance is not goal completion.

## 4. ChatGPT Mode Gate

Use only the approved existing ChatGPT conversation.

Before every message:

1. Open the approved conversation URL.
2. Confirm visible plain `Chat` mode.
3. Stop if the mode is Work, Task, Scheduled Task, Project, Canvas, or another mode.
4. Do not switch modes automatically.

## 5. Create Task State

After reading repository instructions and authoritative specifications:

1. Choose one finite task that materially advances the goal.
2. Identify allowed paths, forbidden changes, and Codex acceptance commands.
3. Create the assigned branch and record its remote HEAD as `base_sha`.
4. Create task state; initial executor is `none / UNASSESSED`.
5. Transition:

   ```text
   DISCOVERING → CAPABILITY_CHECK
   ```

Do not dispatch implementation or start a watcher before the handshake passes.

## 6. ChatGPT Capability Handshake

Send this before the implementation contract:

```text
CAPABILITY_HANDSHAKE

Do not implement the task yet. Inspect only the tools and repository access currently available in this Chat conversation.

Return exactly one JSON object:
{
  "schema_version": "2.0",
  "status": "ready | blocked",
  "executor_profile": "local_full | github_connector | read_only | none",
  "repository_read": true,
  "repository_write": true,
  "local_checkout": false,
  "shell": false,
  "git_commit": true,
  "git_push": true,
  "external_network": false,
  "can_run_acceptance": false,
  "blocker_code": null,
  "blocker_detail": null,
  "observed_at": "ISO-8601 timestamp"
}
```

Profile rules:

- `local_full`: local checkout, shell, checks, commit, and push are available.
- `github_connector`: repository read/write and branch commits are available through GitHub connector; local shell and tests are unavailable.
- `read_only`: repository can be read but no candidate commit can be created.
- `none`: no usable repository executor exists.

Validate and save:

```sh
sh "$SKILL_ROOT/scripts/task-state.sh" set-executor \
  <task-id> --file <handshake-json-file>
```

Decision:

| Profile | Result |
|---|---|
| `local_full` | Continue; ChatGPT runs focused implementer checks before commit. |
| `github_connector` | Continue; ChatGPT may commit an untested candidate; Codex runs all acceptance locally. |
| `read_only` | Task enters `BLOCKED_CAPABILITY`; native goal remains unchanged. |
| `none` | Task enters `BLOCKED_CAPABILITY`; native goal remains unchanged. |

After a ready profile:

```text
CAPABILITY_CHECK → READY
```

Capability is based on actual tools, not model confidence or prompt text.

## 7. Profile-Aware Task Contract

### `local_full`

```text
Executor profile: local_full
Implementation validation policy: implementer_required
Candidate commit without tests: false
```

ChatGPT edits, runs focused checks, commits, pushes, and returns evidence.

### `github_connector`

```text
Executor profile: github_connector
Implementation validation policy: deferred_to_codex
Candidate commit without tests: true
```

Explicitly tell ChatGPT:

```text
You do not need a local checkout or shell for this task.
Use the GitHub connector to read and edit the assigned branch.
Create a candidate commit on that branch.
For commands you cannot run, return status=not_run and verification_status=pending_codex_verification.
Do not treat missing local tests as a blocker; Codex will fetch the candidate and run all acceptance locally.
```

Never combine `github_connector` with a requirement that ChatGPT must pass local tests before commit.

Every task contract includes:

- parent goal ID and full objective;
- goal contribution;
- task ID and objective;
- executor profile and validation policy;
- repository, branch, and base SHA;
- authoritative references;
- allowed and forbidden paths;
- Codex acceptance commands;
- required commit, changed files, test results, blockers, and verification status.

Persist dispatch ID and message fingerprint. Transition:

```text
READY → DISPATCHING → IMPLEMENTING → WAITING_HANDOFF
```

## 8. Low-Token, Blocker-Aware Wait

Start watcher only after dispatch:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" start \
  <task-id> <branch> <base-sha> \
  --repo <absolute-repo-path> \
  --remote <remote> \
  --dispatch-epoch <epoch>
```

Then block the current Codex turn:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" await \
  <task-id> --timeout-seconds <lease-plus-grace>
```

The Git watcher invokes no LLM, starts at 60-second polling, backs off to 300 seconds, and emits only state changes.

The local await monitors:

1. Git watcher events; and
2. ChatGPT transport events under `~/.codex/collaboration/events`.

When ChatGPT reaches a terminal condition, the transport adapter emits an event, for example:

```sh
sh "$SKILL_ROOT/scripts/transport-event.sh" emit \
  <task-id> implementation_blocked \
  --source chatgpt-ui \
  --code NO_LOCAL_EXECUTOR \
  --reason "ChatGPT has no local checkout or shell"
```

Terminal transport events stop the watcher and return immediately:

- `implementation_blocked`
- `conversation_completed_no_commit`
- `conversation_failed`
- `transport_unreachable`
- `mode_drifted`

While await runs, do not end the Codex turn, produce status prose, repeatedly call `get_goal`, or ask ChatGPT for progress.

## 9. Terminal Event Handling

### `handoff_candidate`

Proceed to handoff validation.

### `implementation_blocked`

1. Stop watcher.
2. Keep native goal active and unchanged.
3. Inspect blocker against saved handshake.
4. Run:

   ```sh
   sh "$SKILL_ROOT/scripts/recover-capability.sh" <task-id>
   ```

5. Rerun handshake.
6. If GitHub connector read/write/commit/push remains available, select `github_connector` and redispatch a profile-aware contract.
7. Enter `BLOCKED_CAPABILITY` only when no profile can create a candidate commit.

Do not call `update_goal(blocked)` and do not pause the goal during this recovery.

### `conversation_completed_no_commit`

Send one focused commit-and-push request using the saved profile. If commit is impossible, recover capability and re-handshake.

### `conversation_failed`, `transport_unreachable`, `mode_drifted`

Transition the task to `BLOCKED_TRANSPORT`, preserve evidence, and leave native goal unchanged. Use a stable await or authorized user action rather than repeatedly generating goal turns.

## 10. GitHub Handoff Gate

After a candidate appears:

1. Confirm the same active native goal.
2. Validate:

   ```sh
   sh "$SKILL_ROOT/scripts/validate-handoff.sh" \
     <repo-path> <remote> <branch> <base-sha> <candidate-sha> <allowed-path>...
   ```

3. Record executor profile and verification status.
4. A branch change is a candidate, not acceptance.

## 11. Codex Acceptance

Codex always performs independent acceptance.

### `local_full`

Re-run focused acceptance and required regression checks. Do not trust implementer evidence alone.

### `github_connector`

Run every required command locally. ChatGPT `not_run` results are expected and are not a rejection.

Inspect:

- specification alignment;
- changed-file scope;
- focused tests;
- typecheck, lint, and required regression suite;
- boundary and error paths;
- browser checks when required;
- security and forbidden fallback behavior.

Only `VERIFYING` may transition the task to `ACCEPTED`.

## 12. Repair Loop

When acceptance fails:

1. Transition `VERIFYING → REPAIR_REQUIRED`.
2. Do not patch ChatGPT's implementation locally.
3. Send exact failure evidence and one expected correction.
4. Preserve executor profile and validation policy.
5. Record candidate as next base SHA, increment repair count, transition to `WAITING_REPAIR`, and repeat watcher plus blocker-aware await.

Task repair failure does not authorize native goal blocking.

## 13. Task Completion and Goal Continuation

After task acceptance:

1. Stop LaunchAgent.
2. Persist accepted SHA and evidence.
3. Reassess the complete native goal.
4. Call `update_goal(status="complete")` only when every requirement is proven and no required work remains.
5. Otherwise keep the goal active and select the next finite task.

## 14. Recovery

On restart:

1. Resolve `SKILL_ROOT` and rerun Mac Doctor.
2. Call `get_goal` before reading task state.
3. If the native goal was incorrectly blocked or paused by an older workflow:
   - preserve the same goal ID and objective;
   - request one `/goal resume` action;
   - do not create a replacement goal;
   - after resume run `recover-capability.sh`;
   - rerun handshake and continue.
4. Resume normally only when goal IDs match.
5. Read saved executor handshake before redispatching.
6. Do not reuse a stale executor profile after a capability blocker.
7. Inspect watcher and transport event logs before starting a new watcher.
8. Never redispatch blindly or create repeated “still blocked” turns.
