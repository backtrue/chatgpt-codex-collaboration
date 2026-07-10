---
name: chatgpt-codex-collaboration
description: Coordinate a macOS-first, goal-bound two-agent coding workflow in which ChatGPT performs one scoped implementation task in an existing Chat conversation, pushes the result to GitHub, and Codex independently verifies it before returning control to the native Codex thread goal. Use on macOS when implementation and acceptance must be separated, when ChatGPT should implement while Codex validates, or when a long-running Codex /goal must continue across GitHub handoffs without token-heavy polling.
---

# ChatGPT-Codex Collaboration

Use this skill to keep implementation and acceptance independent:

- Native Codex `/goal` owns the complete objective and cross-turn continuation.
- ChatGPT implements one finite, goal-aligned task at a time.
- Codex owns the specification, acceptance, repair decision, and release gate.
- GitHub is the auditable code handoff boundary.
- The user resolves undefined product behavior and explicit goal changes.

ChatGPT must not accept its own work. Codex must not silently implement a repair assigned to ChatGPT. A ChatGPT completion message is not a handoff without a remote commit.

This version supports macOS 13 or newer only.

## Resolve Bundled Resources

Before running a bundled script, resolve `SKILL_ROOT` to the absolute directory containing this `SKILL.md`. Run scripts with absolute paths:

```sh
sh "$SKILL_ROOT/scripts/<script>.sh" ...
```

Do not assume the current working directory is the skill directory. Repository paths passed to scripts must also be absolute.

Key resources:

- `dependencies.yaml`
- `config/executor.example.yaml`
- `contracts/collaboration.schema.json`
- `scripts/macos-doctor.sh`
- `scripts/preflight.sh`
- `scripts/task-state.sh`
- `scripts/macos-watcher.sh`
- `scripts/validate-handoff.sh`
- `docs/architecture.md`
- `docs/goal-integration.md`
- `docs/macos.md`

Persist collaboration state outside the project worktree under `~/.codex/collaboration/tasks` unless explicitly configured otherwise.

## 1. macOS Environment Gate

Before any goal or task work:

1. Confirm macOS 13+ on `arm64` or `x86_64`.
2. Run:

   ```sh
   sh "$SKILL_ROOT/scripts/macos-doctor.sh" --repo <absolute-repo-path> --remote <remote>
   ```

3. Treat doctor failures as hard blocks. Do not install packages, grant permissions, or widen filesystem access automatically.
4. Require Python 3.9+, Git 2.30+, Xcode Command Line Tools, `launchctl`, `osascript`, `open`, Codex CLI, writable state storage, and a usable ChatGPT surface.
5. Use the bundled `/bin/sh` wrappers and Python scripts. Do not require Bash 4 or GNU coreutils.
6. Request only the minimum macOS Automation or Accessibility permission needed by the selected adapter. Do not request Full Disk Access merely to bypass a gate.

## 2. Native Codex Goal Gate

Before planning or dispatching:

1. Call `get_goal`.
2. When an unfinished active goal exists, preserve its `goal_id` and full objective exactly.
3. When no goal exists, or the previous goal is complete, call `create_goal` using the user's requested end state and authoritative specifications. Do not shrink the goal to the first implementation task. Omit token budget unless explicitly requested.
4. Call `get_goal` again and verify the goal is active.
5. Do not replace a paused, blocked, usage-limited, or budget-limited goal. Use an authorized native goal-control action or enter `BLOCKED_GOAL` and report the exact required action.
6. If the current request conflicts with an active goal, preserve the goal and enter `BLOCKED_GOAL`.
7. Record goal ID, objective, status, optional token budget, creation source, and bind time in task state.
8. Before every implementation or repair dispatch, call `get_goal` again and confirm the same active goal still governs the work.

Task acceptance is not goal completion. Only the native goal audit may mark the goal complete or genuinely blocked.

## 3. ChatGPT Mode Gate

Use only the approved existing ChatGPT conversation.

Before every message sent to ChatGPT:

1. Open the approved conversation URL.
2. Inspect visible UI or DOM state and confirm plain `Chat` mode.
3. If the mode is Work, Task, Scheduled Task, Project, Canvas, or anything other than Chat, stop before sending.
4. Do not switch modes automatically.
5. Report the exact visible mode and wait for the user to restore Chat mode.

Prompt text saying “use Chat mode” is not proof of the active UI mode.

## 4. Start Gate

After the environment and goal gates pass:

1. Inspect `~/.codex/agents/*.toml`, repository instructions, PRD, SDD, specs, issues, and plans.
2. Identify exact authoritative references, allowed paths, forbidden changes, acceptance commands, and required handoff fields.
3. Run repository-required discovery and audit skills. Never silently approximate a missing required audit.
4. Choose one finite task and state how it materially advances the bound goal.
5. If required behavior is undefined, enter `BLOCKED_SPEC` instead of guessing.
6. Run:

   ```sh
   sh "$SKILL_ROOT/scripts/preflight.sh" <repo-path> <remote> <branch> [required-command ...]
   ```

7. Create the assigned remote branch and record its remote HEAD as `base_sha`.
8. Create persistent task state with the bound goal and transition through `DISCOVERING → READY → DISPATCHING`.
9. Persist task ID, goal binding, conversation URL, repository, branch, base SHA, dispatch ID, message fingerprint, dispatch time, and observation settings.

## 5. Implementation Handoff

Send one compact task contract:

```text
Parent goal ID: <native goal id>
Goal objective: <full native goal objective>
Goal contribution: <how this task advances the goal>
Task: <finite task id and objective>
Dispatch ID: <stable idempotency key>
Repository: <repository URL>
Branch: <assigned implementation branch>
Base SHA: <recorded remote head>
Authoritative spec: <file and line references>
Allowed files: <exact files or directories>
Forbidden: <behavior and files that must not change>
Acceptance: <commands and observable outcomes>
Required handoff: edit, test, commit, push, then return commit hash, changed files, test results, and blockers.
Push discipline: do not push partial progress; push only a candidate handoff.
Mode constraint: use this existing conversation in plain Chat mode only.
```

Persist the dispatch ID and message fingerprint before sending. Never send the same dispatch twice after restart.

After successful dispatch, transition `DISPATCHING → IMPLEMENTING → WAITING_HANDOFF`.

## 6. Low-Token Wait Protocol

A slow implementer is not a failed implementer. Waiting must not create repeated Codex goal turns.

### Background transport watcher

Start one per-task LaunchAgent:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" start \
  <task-id> <branch> <base-sha> \
  --repo <absolute-repo-path> \
  --remote <remote> \
  --dispatch-epoch <epoch>
```

The Git watcher:

- invokes no LLM;
- emits only state changes and terminal events;
- starts at a 60-second Git polling interval;
- progressively backs off after unchanged polls;
- caps polling at 300 seconds;
- preserves the original dispatch epoch.

### Keep the current Codex turn active

Immediately after starting the LaunchAgent, synchronously run:

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" await \
  <task-id> --timeout-seconds <lease-plus-grace>
```

This `await` process reads only the local watcher log. It does not query GitHub and does not invoke an LLM.

While `await` is running:

- do not end the Codex turn;
- do not produce status summaries;
- do not call `get_goal` repeatedly;
- do not inspect the same ChatGPT UI repeatedly;
- do not ask ChatGPT for progress;
- do not start another task.

Keeping the tool call active prevents the thread from becoming idle and prevents the active `/goal` runtime from spawning repeated continuation turns merely to discover that the handoff is still pending.

Resume reasoning only after `await` returns a terminal event:

- `handoff_candidate`;
- `lease_expired`;
- `interrupted`;
- watcher failure.

If a local tool timeout returns while the LaunchAgent remains healthy, invoke `await` again in the same Codex turn without summarizing or ending the turn. Do not interpret an await timeout as implementation failure.

If the execution environment repeatedly forces very short blocking-command timeouts, do not allow an active-goal continuation loop. Enter `BLOCKED_OBSERVATION`, leave the LaunchAgent running, and require an authorized `/goal pause` until a handoff event can resume the workflow.

## 7. Token and Context Budget

Waiting should consume approximately zero model tokens after the blocking await begins.

- Keep goal, spec, task contract, and acceptance bundle on disk.
- Rehydrate context only after a terminal watcher event.
- Fetch the candidate commit only after branch HEAD changes.
- Do not generate recurring “still waiting” turns or prose.
- Do not confuse watcher process activity with model activity.
- Prefer an event-driven webhook when available; otherwise use the adaptive LaunchAgent watcher.

## 8. GitHub Handoff Gate

After `handoff_candidate`:

1. Call `get_goal` once and confirm the bound goal still exists, matches the recorded goal ID, and remains active.
2. Record candidate SHA and transition to `HANDOFF_CANDIDATE`.
3. Run:

   ```sh
   sh "$SKILL_ROOT/scripts/validate-handoff.sh" \
     <repo-path> <remote> <branch> <base-sha> <candidate-sha> <allowed-path>...
   ```

4. Confirm candidate SHA is the current remote branch HEAD and differs from base SHA.
5. Confirm changed files remain in scope and contain no secrets, archives, temporary files, or unrelated work.
6. Do not accept merely because branch HEAD changed.

If ChatGPT completed without pushing, send one focused commit-and-push repair request. Do not copy chat output into the worktree by default.

Never force-push, reset the user's worktree, or discard unrelated changes.

## 9. Codex Acceptance

After the handoff gate passes, transition `HANDOFF_CANDIDATE → VERIFYING`:

1. Fetch and inspect the candidate diff.
2. Re-read every relevant authoritative requirement.
3. Verify the implementation advances the bound goal, not merely a narrow local test.
4. Run focused acceptance commands before broad regression commands.
5. Inspect boundary cases, error paths, logging, security fields, and forbidden fallback behavior.
6. Perform required browser checks on actual local surfaces.
7. Run repository-required acceptance audits.
8. Produce a schema-conforming acceptance result including goal evidence and remaining goal work.

Accept only when implementation, tests, observable behavior, changed-file scope, specification, and goal alignment all match. Only `VERIFYING` may transition a task to `ACCEPTED`.

## 10. Failed Acceptance Loop

When acceptance fails:

1. Transition `VERIFYING → REPAIR_REQUIRED`.
2. Do not patch the failed implementation locally.
3. Confirm the same active goal still governs the task.
4. Send one focused repair contract with exact failure evidence, spec requirement, expected correction, scope, forbidden changes, acceptance command, and commit/push requirement.
5. Record the candidate as the next base SHA, increment repair count, transition to `WAITING_REPAIR`, recreate the LaunchAgent, and run blocking `await` again.

Three repair attempts are not automatically three native goal turns. Mark the native goal blocked only when its own strict repeated-blocker audit is satisfied.

## 11. Task Completion and Return to Goal

`ACCEPTED` closes only the finite collaboration task.

After acceptance:

1. Stop and remove the LaunchAgent:

   ```sh
   sh "$SKILL_ROOT/scripts/macos-watcher.sh" stop <task-id>
   ```

2. Persist accepted SHA.
3. Call `get_goal` once and reassess the complete objective against current repository, runtime, tests, CI, browser checks, artifacts, and external state.
4. Record proven goal requirements and remaining work.
5. If every requirement is proven and no required work remains, call `update_goal(status="complete")`.
6. Otherwise keep the goal active and choose the next finite task or return control to native goal continuation.

Do not redefine the goal around completed work. Do not mark it complete because a task, test suite, context window, or budget cycle ended.

## 12. Recovery

On restart:

1. Resolve `SKILL_ROOT` and rerun Mac Doctor.
2. Call `get_goal` before reading task state.
3. Resume only when persisted and native goal IDs match.
4. Inspect LaunchAgent status and logs before redispatching.
5. If the watcher is active, run blocking `await`; do not create a new polling turn.
6. If the user explicitly replaced the goal, rebind only after confirming the new objective.
7. Enter `BLOCKED_GOAL` when the native goal is missing, unexpectedly terminal, non-active, or mismatched.

Keep one active implementation task unless parallel work is explicitly authorized. Reuse the approved ChatGPT conversation. Never treat a ChatGPT “done” message or observation timeout as completion evidence.
