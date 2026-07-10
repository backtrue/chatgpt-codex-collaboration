---
name: chatgpt-codex-collaboration
description: Coordinate a macOS-first, goal-bound two-agent coding workflow in which ChatGPT implements one scoped task through either a full local executor or a GitHub connector, while Codex independently verifies the candidate against authoritative specifications. Use when ChatGPT should perform most implementation work, Codex should minimize token use and focus on planning and acceptance, or a long-running Codex /goal must survive external ChatGPT handoffs without deadlocks or polling loops.
---

# ChatGPT-Codex Collaboration

Use this skill to separate implementation from acceptance:

- Native Codex `/goal` owns the complete objective.
- ChatGPT implements one finite, goal-aligned task at a time.
- Codex owns task definition, authoritative spec, acceptance, and repair decisions.
- GitHub branch and commit SHA are the code handoff boundary.
- The user resolves undefined product behavior and explicit goal changes.

ChatGPT must not accept its own work. Codex must not silently implement a repair assigned to ChatGPT. A ChatGPT completion message without a remote commit is not a handoff.

This version supports macOS 13 or newer only.

## Resolve Bundled Resources

Resolve `SKILL_ROOT` to the absolute directory containing this `SKILL.md`. Run bundled scripts through absolute paths:

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
- `scripts/validate-handoff.sh`
- `docs/architecture.md`
- `docs/macos.md`

Persist task state outside the project worktree under `~/.codex/collaboration/tasks`.

## 1. macOS Environment Gate

Before goal or task work:

1. Confirm macOS 13+ on `arm64` or `x86_64`.
2. Run:

   ```sh
   sh "$SKILL_ROOT/scripts/macos-doctor.sh" \
     --repo <absolute-repo-path> --remote <remote>
   ```

3. Treat doctor failures as hard blocks.
4. Require Codex to have a complete local repository checkout and command execution for acceptance.
5. Do not automatically install packages, widen permissions, or request Full Disk Access.

## 2. Native Goal Gate

1. Call `get_goal`.
2. Preserve an active goal's `goal_id` and full objective.
3. If no goal exists, or the previous goal is complete, call `create_goal` using the user's requested end state and authoritative specs. Do not shrink the goal to the first task.
4. Do not replace a paused, blocked, usage-limited, budget-limited, or conflicting goal.
5. Record the goal binding in persistent task state.
6. Before every implementation or repair dispatch, verify the same active goal still governs the work.

Task acceptance is not goal completion.

## 3. ChatGPT Mode Gate

Use only the approved existing ChatGPT conversation.

Before every message:

1. Open the approved conversation URL.
2. Confirm visible plain `Chat` mode.
3. Stop if the mode is Work, Task, Scheduled Task, Project, Canvas, or another mode.
4. Do not switch modes automatically.

## 4. Create Task State

After reading repository instructions and authoritative specs:

1. Choose one finite task that materially advances the goal.
2. Identify allowed paths, forbidden changes, and Codex acceptance commands.
3. Create the assigned branch and record its remote HEAD as `base_sha`.
4. Create task state. The initial executor profile is `none / UNASSESSED`.
5. Transition:

   ```text
   DISCOVERING → CAPABILITY_CHECK
   ```

Do not dispatch implementation or start a watcher before the capability handshake passes.

## 5. ChatGPT Capability Handshake

Send a handshake message before the implementation contract:

```text
CAPABILITY_HANDSHAKE

Do not implement the task yet. Inspect only the tools and repository access currently available in this Chat conversation.

Return exactly one JSON object with:
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

Profile rules:
- local_full: local checkout, shell, tests, commit, and push are available.
- github_connector: repository read/write and branch commits are available through GitHub connector, but local shell/tests are unavailable.
- read_only: repository can be read but no candidate commit can be created.
- none: no usable repository executor exists.
```

Validate the response against `capabilityHandshake` in the collaboration schema. Save it with:

```sh
sh "$SKILL_ROOT/scripts/task-state.sh" set-executor \
  <task-id> --file <handshake-json-file>
```

### Profile decision

| Profile | Result |
|---|---|
| `local_full` | Continue; ChatGPT must run required implementer checks before committing. |
| `github_connector` | Continue; ChatGPT may commit an untested candidate and mark tests `not_run`; Codex must run all acceptance locally. |
| `read_only` | `BLOCKED_CAPABILITY`; do not start watcher. |
| `none` | `BLOCKED_CAPABILITY`; do not start watcher. |

After an accepted ready profile, transition:

```text
CAPABILITY_CHECK → READY
```

A profile is based on real available tools, not on model confidence or prompt instructions.

## 6. Build the Profile-Aware Task Contract

### `local_full`

Use:

```text
Executor profile: local_full
Implementation validation policy: implementer_required
Candidate commit without tests: false
```

ChatGPT must edit, run required focused checks, commit, push, and return test evidence.

### `github_connector`

Use:

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

Never send a contract that simultaneously requires local tests, forbids remote validation, and assigns a `github_connector` executor.

Every task contract must include:

- parent goal ID and full objective;
- goal contribution;
- task ID and objective;
- executor profile and validation policy;
- repository, branch, and base SHA;
- authoritative references;
- allowed and forbidden paths;
- Codex acceptance commands;
- required commit, changed files, test results, blockers, and verification status.

Persist dispatch ID and message fingerprint before sending. Transition:

```text
READY → DISPATCHING → IMPLEMENTING → WAITING_HANDOFF
```

## 7. Low-Token, Blocker-Aware Wait

Start the Git watcher only after successful dispatch:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" start \
  <task-id> <branch> <base-sha> \
  --repo <absolute-repo-path> \
  --remote <remote> \
  --dispatch-epoch <epoch>
```

Then synchronously block the current Codex turn:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" await \
  <task-id> --timeout-seconds <lease-plus-grace>
```

The Git watcher invokes no LLM, starts at 60-second polling, backs off to 300 seconds, and emits only state changes.

The local `await` monitors both:

1. watcher log events; and
2. local ChatGPT transport events under `~/.codex/collaboration/events`.

### Transport adapter responsibility

When the ChatGPT response reaches a terminal condition, the transport adapter must immediately write a local event. Examples:

```sh
sh "$SKILL_ROOT/scripts/transport-event.sh" emit \
  <task-id> implementation_blocked \
  --source chatgpt-ui \
  --code NO_LOCAL_EXECUTOR \
  --reason "ChatGPT has no local checkout or shell"
```

```sh
sh "$SKILL_ROOT/scripts/transport-event.sh" emit \
  <task-id> conversation_completed_no_commit \
  --source chatgpt-ui \
  --reason "Response completed without a candidate commit"
```

Supported terminal events:

- `implementation_blocked`;
- `conversation_completed_no_commit`;
- `conversation_failed`;
- `transport_unreachable`;
- `mode_drifted`.

A terminal transport event stops the Git watcher and returns control immediately. Do not wait for the Git lease to expire.

While `await` runs, do not end the Codex turn, generate status prose, repeatedly call `get_goal`, or ask ChatGPT for progress.

## 8. Terminal Event Handling

### `handoff_candidate`

Proceed to the GitHub handoff gate.

### `implementation_blocked`

1. Stop the watcher.
2. Inspect the blocker against the saved handshake.
3. If the saved profile was `local_full` but the failure proves no local checkout or shell exists, the handshake is stale or false.
4. Return to `CAPABILITY_CHECK` and run a new handshake.
5. If GitHub connector read/write/commit remains available, downgrade to `github_connector` and redispatch a profile-aware contract.
6. Otherwise transition to `BLOCKED_CAPABILITY`.

Do not continue waiting for a commit that the implementer has stated it cannot create.

### `conversation_completed_no_commit`

Send one focused request to create and push the candidate using the capabilities declared in the handshake. If it still cannot commit, re-run the capability handshake and block or downgrade accordingly.

### `conversation_failed`, `transport_unreachable`, `mode_drifted`

Transition to `BLOCKED_TRANSPORT` and preserve exact evidence.

## 9. GitHub Handoff Gate

After a candidate appears:

1. Confirm the same active goal.
2. Validate branch, current remote HEAD, base SHA difference, allowed paths, and forbidden artifacts:

   ```sh
   sh "$SKILL_ROOT/scripts/validate-handoff.sh" \
     <repo-path> <remote> <branch> <base-sha> <candidate-sha> <allowed-path>...
   ```

3. Record executor profile and verification status from the handoff.
4. A branch change is a candidate, not acceptance.

## 10. Codex Acceptance

Codex always performs independent acceptance.

### For `local_full`

Re-run focused acceptance and required regression checks. Do not trust implementer test output alone.

### For `github_connector`

Codex must run every required command locally because implementer tests are deferred. `not_run` from ChatGPT is expected and is not itself a rejection.

Inspect:

- authoritative spec alignment;
- changed-file scope;
- focused tests;
- typecheck, lint, and required regression suite;
- boundary and error paths;
- browser checks when required;
- security and forbidden fallback behavior.

Only `VERIFYING` may transition the task to `ACCEPTED`.

## 11. Repair Loop

When acceptance fails:

1. Transition `VERIFYING → REPAIR_REQUIRED`.
2. Do not patch ChatGPT's implementation locally.
3. Send exact failure evidence and one concrete expected correction.
4. Preserve the executor profile and validation policy.
5. Record the candidate as the next base SHA, increment repair count, transition to `WAITING_REPAIR`, and repeat watcher plus blocker-aware await.

## 12. Task Completion and Goal Continuation

After task acceptance:

1. Stop and remove the LaunchAgent.
2. Persist accepted SHA and acceptance evidence.
3. Reassess the full native goal.
4. Call `update_goal(status="complete")` only when every requirement is proven and no required work remains.
5. Otherwise keep the goal active and select the next finite task.

## 13. Recovery

On restart:

1. Resolve `SKILL_ROOT` and rerun Mac Doctor.
2. Call `get_goal` before reading task state.
3. Resume only when goal IDs match.
4. Read the saved executor handshake before redispatching.
5. If the previous implementation reported a capability blocker, do not reuse the stale profile.
6. Inspect watcher and transport event logs before starting a new watcher.
7. Never redispatch blindly or create a repeated waiting turn.
