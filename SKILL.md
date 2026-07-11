---
name: chatgpt-codex-collaboration
description: Coordinate a macOS-first two-agent coding workflow in which ChatGPT performs most implementation work through either a local executor or GitHub connector, while Codex defines the task, independently verifies the candidate, and continues the same native /goal. Use when Codex token use should be minimized, external ChatGPT work may take a long time, or GitHub handoffs must avoid blocking-await loops, missing branches, false completion receipts, and native-goal deadlocks.
---

# ChatGPT-Codex Collaboration

Use this skill to separate implementation from acceptance:

- Native Codex `/goal` owns the complete objective.
- ChatGPT implements one finite, goal-aligned task at a time.
- Codex owns task definition, authoritative specification, acceptance, and repair decisions.
- A remote Git branch and commit SHA are the code handoff boundary.
- The user resolves undefined product behavior and explicit goal changes.

ChatGPT must not accept its own work. Codex must not silently implement a repair assigned to ChatGPT. A response without a remote commit is not a completed handoff.

This version supports macOS 13 or newer only.

## Resolve Bundled Resources

Resolve `SKILL_ROOT` to the absolute directory containing this `SKILL.md`.

Run bundled scripts through absolute paths:

```sh
sh "$SKILL_ROOT/scripts/<script>.sh" ...
```

Important resources:

- `contracts/collaboration.schema.json`
- `contracts/handoff-receipt.schema.json`
- `dependencies.yaml`
- `config/executor.example.yaml`
- `scripts/macos-doctor.sh`
- `scripts/preflight.sh`
- `scripts/prepare-handoff-branch.sh`
- `scripts/task-state.sh`
- `scripts/transport-event.sh`
- `scripts/macos-watcher.sh`
- `scripts/validate-handoff-receipt.sh`
- `scripts/validate-handoff.sh`
- `docs/native-goal-safety.md`
- `docs/capability-handshake.md`
- `docs/architecture.md`
- `docs/macos.md`

Persist task state under `~/.codex/collaboration/tasks`.

## 1. Native Goal Safety and Transport Suspension

The native goal and collaboration task are separate state machines.

A task-level blocker does not authorize:

- `update_goal(status="blocked")`;
- clearing or replacing the native goal;
- permanently pausing the goal;
- repeated “still blocked” continuation turns.

The native goal may be marked blocked only when the same complete-goal blocker persists across at least three consecutive native goal turns and no executor fallback, transport fallback, repair, local verification path, user action, or external-state change can make progress.

### Authorized temporary suspension

External ChatGPT implementation is a transport wait, not model work. To prevent active `/goal` continuation turns during that wait, this skill is authorized to temporarily set the same goal to `paused` through the local Codex app-server.

This temporary pause:

- preserves the same goal ID and objective;
- is not evidence of failure;
- must occur only after a valid implementation dispatch;
- must be paired with event-driven resume of the same `CODEX_THREAD_ID`;
- must not be used to hide a task blocker.

The event supervisor launches `codex exec resume` while the goal is still paused. The wake controller waits for the explicit resumed `turn.started` event, then reactivates the same goal. This prevents an idle continuation from racing ahead of the event prompt.

## 2. macOS Environment Gate

Before goal or task work:

1. Confirm macOS 13+ on `arm64` or `x86_64`.
2. Run:

   ```sh
   sh "$SKILL_ROOT/scripts/macos-doctor.sh" \
     --repo <absolute-repo-path> --remote <remote>
   ```

3. Treat doctor failures as hard environment blocks.
4. Require a complete local repository checkout and command execution for Codex acceptance.
5. Require `CODEX_THREAD_ID`, `codex app-server`, and `codex exec resume` for automatic event-driven recovery.
6. Do not automatically install packages, widen permissions, or request Full Disk Access.

## 3. Native Goal Gate

1. Call `get_goal`.
2. Preserve an active goal's `goal_id` and complete objective.
3. If no goal exists or the previous goal is complete, call `create_goal` using the user's requested end state and authoritative specifications. Do not shrink the goal to the first task.
4. If an older workflow incorrectly left the goal blocked or paused:
   - preserve the same goal ID and objective;
   - do not create a replacement goal;
   - resume that same goal once;
   - recover the existing task and continue.
5. If the goal is paused, blocked, usage-limited, or budget-limited for an unrelated reason, do not override it.
6. Before every implementation or repair dispatch, confirm the same active goal governs the task.

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
3. Determine the repository, remote, assigned branch, and base SHA.
4. Create persistent task state with executor `none / UNASSESSED`.
5. Transition:

   ```text
   DISCOVERING → CAPABILITY_CHECK
   ```

Do not dispatch implementation or start the event supervisor before the capability handshake passes.

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

Profiles:

- `local_full`: local checkout, shell, focused checks, commit, and push are available.
- `github_connector`: GitHub connector can read, edit, commit, and push; local shell and tests are unavailable.
- `read_only`: repository can be read but no candidate commit can be created.
- `none`: no usable repository executor exists.

Validate and save the response:

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

Capability is based on actual tools, not confidence or prompt text.

## 7. Prepare the Remote Handoff Branch

The assigned branch must exist on the remote before ChatGPT receives the implementation task, especially for `github_connector`.

Run:

```sh
sh "$SKILL_ROOT/scripts/prepare-handoff-branch.sh" \
  <repo-path> <remote> <branch> <base-sha>
```

This command must prove:

- the remote is reachable;
- the branch exists remotely;
- the branch HEAD equals the recorded base SHA;
- a missing branch was successfully created with an exact non-force push.

Do not dispatch when the remote branch is missing, inaccessible, or points at an unexpected commit.

A local branch name or claimed branch HEAD is not sufficient evidence.

## 8. Profile-Aware Task Contract

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
Remote branch is already created and writable.
```

Explicitly tell ChatGPT:

```text
You do not need a local checkout or shell for this task.
Use the GitHub connector to read and edit the assigned existing remote branch.
Create and push a candidate commit on that exact branch before responding.
For commands you cannot run, return status=not_run and verification_status=pending_codex_verification.
Do not treat missing local tests as a blocker; Codex will run all acceptance locally.
```

Never combine `github_connector` with a requirement that ChatGPT pass local tests before commit.

Every task contract includes:

- parent goal ID and complete objective;
- goal contribution;
- task ID and objective;
- executor profile and validation policy;
- repository, remote branch, and base SHA;
- authoritative references;
- allowed and forbidden paths;
- Codex acceptance commands;
- the strict handoff receipt format.

Persist dispatch ID and message fingerprint. Transition:

```text
READY → DISPATCHING → IMPLEMENTING → WAITING_HANDOFF
```

## 9. Strict Handoff Receipt

ChatGPT's final response must be exactly one receipt conforming to `contracts/handoff-receipt.schema.json`.

A completed receipt requires:

- `status: completed`;
- a non-null 40-character `commit_sha`;
- at least one changed file;
- no blockers;
- `verification_status: implementer_verified` or `pending_codex_verification`.

A blocked receipt requires:

- `status: blocked`;
- `commit_sha: null`;
- at least one explicit blocker;
- `verification_status: blocked`.

`pending_codex_verification`, `not_run`, or `Blockers: 無` without a commit SHA is not completion. It is an invalid receipt and must produce `conversation_completed_no_commit`.

Validate an extracted receipt with:

```sh
sh "$SKILL_ROOT/scripts/validate-handoff-receipt.sh" \
  <receipt-json-file>
```

Do not start or continue waiting based solely on prose claims.

## 10. Event-Driven External Wait

After a valid dispatch, start the event supervisor:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" start \
  <task-id> <branch> <base-sha> \
  --repo <absolute-repo-path> \
  --remote <remote> \
  --dispatch-epoch <epoch>
```

`start` performs these actions atomically:

1. verifies or creates the remote branch at the exact base SHA;
2. reads the saved executor profile;
3. reads `CODEX_THREAD_ID`;
4. temporarily pauses the same native goal through `codex app-server`;
5. starts a per-task launchd event supervisor with a unique generation ID;
6. records the wake configuration;
7. returns immediately so the current turn can end.

Do not run blocking `await`. The command is intentionally disabled because the execution platform may force a 300-second timeout and create continuation loops.

During the external wait:

- native goal status is temporarily paused;
- no Codex model turn remains active;
- Git polling starts at 60 seconds and backs off to 300 seconds;
- local ChatGPT transport events are monitored;
- no LLM is invoked;
- default fallback wake is 30 minutes for `github_connector` and 2 hours for `local_full`.

Terminal events:

- remote branch HEAD differs from base SHA;
- `implementation_blocked`;
- `capability_rejected`;
- `conversation_completed_no_commit`;
- `conversation_failed`;
- `transport_unreachable`;
- `mode_drifted`;
- observation lease expiry.

On a terminal event, the supervisor:

1. launches `codex exec --json resume <CODEX_THREAD_ID> <event prompt>` while the goal remains paused;
2. waits for the explicit `turn.started` event;
3. reactivates the same native goal;
4. resumes the same persisted session and task;
5. logs the resumed run;
6. cleans only the matching supervisor generation;
7. leaves the goal paused and sends a macOS notification if automatic resume fails.

## 11. Transport Adapter Responsibilities

When the ChatGPT response reaches a terminal condition, the transport adapter must emit a local event.

Example:

```sh
sh "$SKILL_ROOT/scripts/transport-event.sh" emit \
  <task-id> conversation_completed_no_commit \
  --source chatgpt-ui \
  --reason "ChatGPT completed without a valid commit receipt"
```

For a valid commit, the Git branch change is sufficient to trigger resume; a separate UI event is optional.

For an invalid or blocked response, the adapter must not leave the supervisor waiting for a commit that cannot appear.

## 12. Terminal Event Handling

### `handoff_candidate`

Proceed to GitHub handoff validation.

### `implementation_blocked` or `capability_rejected`

1. Keep the same native goal.
2. Recover the task to capability checking.
3. Rerun the handshake.
4. Downgrade from `local_full` to `github_connector` when connector commit capability remains available.
5. Enter `BLOCKED_CAPABILITY` only when no accepted profile can create a candidate commit.

### `conversation_completed_no_commit`

Treat it as protocol failure, not an active wait.

1. Verify that the remote branch did not advance.
2. Send one focused request requiring a commit and strict receipt.
3. If commit remains impossible, recover capability and rerun the handshake.
4. Never accept `pending_codex_verification` without a commit SHA.

### `conversation_failed`, `transport_unreachable`, or `mode_drifted`

Transition the collaboration task to `BLOCKED_TRANSPORT`, preserve evidence, and keep the same native goal identity.

### `observation_lease_expired`

Inspect the approved ChatGPT conversation once:

- if generation is still active, start a new event-driven suspension without status prose;
- if the response completed without a valid commit, emit protocol failure and require a commit;
- if the UI is inaccessible, enter `BLOCKED_TRANSPORT`.

## 13. GitHub Handoff Gate

After a candidate appears:

1. Confirm the same native goal identity.
2. Validate:

   ```sh
   sh "$SKILL_ROOT/scripts/validate-handoff.sh" \
     <repo-path> <remote> <branch> <base-sha> <candidate-sha> <allowed-path>...
   ```

3. Confirm the candidate is the current remote branch HEAD.
4. Confirm candidate differs from base SHA.
5. Confirm changed files are in scope and contain no forbidden artifacts.
6. Record executor profile and verification status.

A branch change is a candidate, not acceptance.

## 14. Codex Acceptance

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

## 15. Repair Loop

When acceptance fails:

1. Transition `VERIFYING → REPAIR_REQUIRED`.
2. Do not patch ChatGPT's implementation locally.
3. Send exact failure evidence and one concrete expected correction.
4. Preserve executor profile and validation policy.
5. Record the candidate as the next base SHA.
6. Ensure the remote branch still exists at that base SHA.
7. Dispatch the repair and start a new event-driven wait.

Task repair failure does not authorize native goal blocking.

## 16. Task Completion and Goal Continuation

After task acceptance:

1. Stop and remove any remaining LaunchAgent.
2. Persist accepted SHA and acceptance evidence.
3. Reassess the complete native goal.
4. Call `update_goal(status="complete")` only when every requirement is proven and no required work remains.
5. Otherwise keep the goal active and select the next finite task.

## 17. Recovery

On restart:

1. Resolve `SKILL_ROOT` and rerun Mac Doctor.
2. Call `get_goal` before reading task state.
3. Preserve the same goal ID and objective.
4. Inspect task state, wake configuration, supervisor status, logs, remote branch, and transport events.
5. If a previous blocking-await workflow is still running, stop it and restart with event-driven `macos-watcher.sh start`.
6. If the remote handoff branch is absent, create it at base SHA before redispatching.
7. Do not reuse a stale executor profile after a capability blocker.
8. Do not create repeated “still waiting” or “still blocked” turns.

The formal wait path is always suspend-and-resume, never blocking await.
