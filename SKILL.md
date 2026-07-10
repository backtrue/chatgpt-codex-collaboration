---
name: chatgpt-codex-collaboration
description: Coordinate a goal-bound two-agent coding workflow in which ChatGPT performs one scoped implementation task in an existing Chat conversation, pushes the result to GitHub, and Codex verifies it against the authoritative spec before returning control to the native Codex thread goal. Use when implementation and acceptance must be separated, when a user requires ChatGPT to edit code and Codex to validate it, or when a long-running Codex /goal must continue across implementation handoffs.
---

# ChatGPT-Codex Collaboration

Use this skill to keep implementation and acceptance independent while preserving the native Codex thread goal:

- The native Codex `/goal` is the top-level objective and continuation authority.
- ChatGPT is the implementer for one finite, goal-aligned task at a time.
- Codex is the specification owner, verifier, and release gate.
- GitHub is the handoff boundary.
- The user decides unresolved product behavior and explicit goal changes.

Do not let ChatGPT declare acceptance. Do not let Codex silently implement a failed handoff that was assigned to ChatGPT. Do not create a second competing goal system inside this skill.

## Operational Files

Use the bundled files rather than recreating their behavior from memory:

- `dependencies.yaml`: required commands, native goal capabilities, conditional skills, and fallbacks.
- `config/executor.example.yaml`: executor capability and restriction profile.
- `contracts/collaboration.schema.json`: goal-bound task, repair, event, handoff, acceptance, and task-state contracts.
- `scripts/check-dependencies.sh`: command dependency check.
- `scripts/preflight.sh`: repository and execution preflight.
- `scripts/task-state.sh`: persistent state controller and goal binding.
- `scripts/wait-for-handoff.sh`: token-free branch watcher.
- `scripts/validate-handoff.sh`: remote SHA and changed-scope validation.
- `docs/architecture.md`: transport, execution, state, dependency, goal, and recovery architecture.
- `docs/goal-integration.md`: native `/goal` binding and continuation rules.

Persist task state outside the repository worktree, normally under `~/.codex/collaboration/tasks`.

## Native Codex Goal Gate

Run this gate before planning or dispatching any implementation task.

1. Call `get_goal` and inspect the thread goal before reading the task as an isolated request.
2. If an unfinished active goal exists:
   - preserve its `goal_id` and objective exactly;
   - treat that objective as the top-level authority;
   - derive only a finite task that materially advances it.
3. If no goal exists, or the previous goal is `complete`, call `create_goal` before continuing:
   - derive the objective from the user's actual requested end state and referenced specs;
   - preserve the full scope rather than shrinking it to the first implementation task;
   - omit `token_budget` unless the user explicitly requested one;
   - call `get_goal` again and verify the new goal is `active`.
4. This skill's activation policy explicitly requires a native thread goal. Creating one when absent is authorized by the workflow; do not infer or create unrelated goals outside this skill.
5. If the existing goal is `paused`, `blocked`, `usage_limited`, or `budget_limited`, do not replace or clear it:
   - use an explicitly authorized native goal-control action when available;
   - otherwise transition the collaboration task to `BLOCKED_GOAL` and report the exact goal status and required `/goal resume`, usage reset, budget change, or user decision.
6. If the active goal materially conflicts with the current request, preserve the active goal and transition to `BLOCKED_GOAL`. Do not silently edit, clear, complete, or replace it.
7. Record the bound `goal_id`, objective, status, token budget, whether this skill created it, and bind time in task state.
8. Before every new implementation or repair dispatch, call `get_goal` again:
   - the goal must still exist;
   - its ID must match the bound goal;
   - its status must be `active`;
   - the finite task must still advance the current objective.
9. Goal completion and goal blocking remain controlled by native `update_goal` rules. Task acceptance is not goal completion.

## Non-Negotiable Mode Gate

Use only the existing ChatGPT conversation supplied by the user. Before every message sent to ChatGPT:

1. Navigate to the approved conversation URL.
2. Inspect the visible page state or DOM and confirm the active mode is `Chat`.
3. If the active mode is `Work`, `Task`, `Scheduled Task`, `Project`, `Canvas`, or any other mode that is not plain `Chat`, stop before sending the prompt.
4. Do not click a mode switch, create a task, create a project, schedule work, open Work mode, or use a mode-changing shortcut to continue.
5. Report the exact visible mode and wait for the user to restore `Chat` mode.

A prompt cannot override the UI mode. Text saying “stay in Chat mode” is an additional guard, not proof that the active mode is Chat.

## Start Gate

After the Native Codex Goal Gate passes:

1. Inspect `~/.codex/agents/*.toml`, repo-local agent instructions, and the authoritative spec files.
2. Run `bash scripts/check-dependencies.sh`. Missing required commands or a repo-required conditional skill transitions the task to `BLOCKED_DEPENDENCY`; missing native goal tools is handled by the Goal Gate as `BLOCKED_GOAL`.
3. Identify the exact spec lines, allowed files, forbidden changes, acceptance commands, and required output fields.
4. Run `spec-discovery-gate` and `spec-task-audit-list` only when repo-local instructions require them. Do not silently approximate a missing required audit.
5. Split the next work into one finite implementation task and state how it advances the bound goal. One ChatGPT prompt must map to one task and one acceptance bundle.
6. Do not send a task when required behavior is not explicit in the spec. Transition to `BLOCKED_SPEC` and ask the user for the missing product decision.
7. Run `bash scripts/preflight.sh <repo-path> <remote> <branch> [required-command ...]`. Missing execution capability transitions the task to `BLOCKED_CAPABILITY`.
8. Create the assigned remote branch before dispatch and record its current remote HEAD as the handoff base SHA.
9. Create persistent state with `bash scripts/task-state.sh create ... --goal-id ... --goal-objective ...`, then transition `DISCOVERING → READY → DISPATCHING` as each gate passes.
10. Persist the task ID, goal binding, conversation URL, repository, branch, base SHA, dispatch ID, message fingerprint, dispatch time, and observation settings outside the worktree.

## Implementation Handoff

Build the dispatch from the `taskContract` definition in `contracts/collaboration.schema.json`. Send ChatGPT a compact task contract containing:

```text
Parent goal ID: <native Codex goal id>
Goal objective: <full native Codex goal objective>
Goal contribution: <how this finite task advances the goal>
Task: <single finite task id and objective>
Dispatch ID: <stable idempotency key>
Repository: <repository URL>
Branch: <implementation branch>
Base SHA: <recorded remote head>
Authoritative spec: <file and line references>
Allowed files: <exact files or directories>
Forbidden: <behavior and files that must not change>
Acceptance: <commands and observable outcomes>
Required handoff: edit the files, run the acceptance commands, commit, push the branch, and return commit hash, changed files, tests, and blockers.
Push discipline: do not push partial progress to the assigned branch. Push only a candidate handoff after the required checks have run.
Mode constraint: use this existing Chat conversation in Chat mode only; do not use Work, Task, Scheduled Task, Project, Canvas, or another mode.
```

Generate and persist a message fingerprint before sending. Do not send the same `dispatch_id` and fingerprint twice after a restart. After successful dispatch, transition `DISPATCHING → IMPLEMENTING → WAITING_HANDOFF` and start the watcher.

Ask ChatGPT to stop rather than guess when it finds a missing spec decision. Do not send credentials, secrets, tokens, private files, or unrelated repository data.

## Long-Running Implementer Wait

A slow implementer is not a failed implementer. Separate waiting from reasoning after the implementation prompt is sent.

1. Start a deterministic handoff watcher for the assigned remote branch. Prefer `bash scripts/wait-for-handoff.sh <task-id> <branch> <base-sha>` or an equivalent transport-level process.
2. Treat the first remote branch HEAD that differs from the recorded base SHA as a candidate handoff signal. It is not acceptance.
3. While the watcher is active, Codex must not repeatedly reread the spec, inspect the same page, ask ChatGPT for status, or spend model turns polling.
4. The watcher may poll GitHub or the transport layer, but it must not call an LLM. It should emit only state changes and terminal events rather than logging every poll.
5. Use a renewable observation lease instead of a short task timeout. The bundled watcher defaults to a two-hour lease and a 30-second transport poll; repositories may override both values.
6. Preserve the original dispatch timestamp when restarting a watcher. A shell timeout, browser timeout, lost terminal connection, or watcher restart is not evidence that ChatGPT failed.
7. Do not send a status prompt while the ChatGPT response is visibly generating. A status prompt can interrupt or alter the active implementation turn.
8. Resume Codex reasoning only when one of these events occurs:
   - a candidate handoff commit appears;
   - the ChatGPT UI shows a terminal error or completed response without a push;
   - the approved conversation changes mode or becomes inaccessible;
   - an observation lease expires.

When an observation lease expires without a candidate commit, inspect the approved conversation once:

- If generation is visibly active, record the observation and renew the lease without sending a message.
- If the response is complete but no remote commit exists, send one focused repair request requiring commit and push.
- If the UI shows an explicit failure, disconnected session, authentication problem, or mode drift, transition to `BLOCKED_TRANSPORT` and report the exact blocker.
- If the state cannot be determined, transition to `BLOCKED_OBSERVATION`; do not label the implementation failed.

A task may renew its observation lease while visible generation activity continues. Stop only at an explicit user-configured absolute deadline, an explicit terminal failure, or repeated unchanged observations that indicate a stalled interface. Keep stalled-state evidence and ask the user before abandoning the handoff.

## Token and Context Budget

Waiting must be nearly token-free:

- Keep the goal objective, authoritative spec, and acceptance bundle on disk; do not replay them during each observation.
- Persist a compact task-state record outside the worktree and rehydrate only after a terminal watcher event.
- Use `git ls-remote` or an equivalent small transport query while waiting; fetch the candidate commit only once it appears.
- Do not request periodic prose status updates from ChatGPT.
- Do not produce recurring summaries of unchanged state.
- After a candidate commit appears, load only the bound goal, task contract, changed diff, relevant spec sections, and acceptance results into the active verification context.

If the environment supports an event-driven push webhook or notification hook, prefer that over polling. The event handler should wake the verifier only after the assigned branch changes.

## GitHub Handoff Gate

Treat the handoff as incomplete until ChatGPT provides a pushed branch and commit hash.

1. Call `get_goal` and confirm the bound goal still exists, has the same ID, and remains `active`.
2. Record the candidate SHA and transition `WAITING_HANDOFF` or `WAITING_REPAIR → HANDOFF_CANDIDATE`.
3. Run `bash scripts/validate-handoff.sh <repo-path> <remote> <branch> <base-sha> <candidate-sha> <allowed-path>...`.
4. Confirm the pushed branch is the assigned branch.
5. Confirm the candidate is the current remote HEAD and differs from the recorded base SHA.
6. Confirm changed files stay within the allowed scope.
7. Confirm the commit does not include generated archives, secrets, temporary files, or unrelated work.
8. Confirm the repository worktree state is understood before pulling or merging.
9. Do not accept a candidate solely because the watcher observed a branch change.

If ChatGPT says it changed files but did not push, do not copy the files into the working tree by default. Send one repair request asking it to commit and push. Accept an attached patch or archive only when the user explicitly authorizes that fallback for the current task; inspect it as untrusted input and still require a local commit before acceptance.

Never force-push, reset the user’s worktree, or discard unrelated changes.

## Codex Acceptance

After the handoff gate passes, transition `HANDOFF_CANDIDATE → VERIFYING`:

1. Fetch the assigned branch and inspect the commit diff.
2. Re-read the authoritative spec around every changed behavior.
3. Verify the implementation still advances the bound goal rather than only satisfying a narrow local test.
4. Run the task-specific acceptance commands before broader regression commands.
5. Inspect error paths, boundary cases, logging, security fields, and forbidden fallback behavior.
6. For frontend work, verify the actual local page with the browser at required desktop and mobile sizes.
7. Run `spec-acceptance-audit` when repo-local instructions require it.
8. Check the audit list. No requested row may remain unchecked or be silently moved out of scope.
9. Produce an `acceptanceResult` conforming to `contracts/collaboration.schema.json`, including goal evidence and remaining goal work.

Accept only when the implementation, tests, observable behavior, changed-file scope, and goal alignment all match the spec. A passing test suite does not override a spec or goal mismatch. Only `VERIFYING` may transition the collaboration task to `ACCEPTED`.

## Failed Acceptance Loop

When acceptance fails, transition `VERIFYING → REPAIR_REQUIRED`. Do not patch the failed implementation locally. Call `get_goal` again and create a repair contract conforming to `repairContract` in the schema:

```text
Parent goal ID: <bound native Codex goal id>
Repair Task: <same task id with repair suffix>
Observed failure: <exact command output, response, or UI state>
Spec requirement: <exact file and line>
Expected behavior: <one concrete correction>
Scope: <allowed files>
Forbidden: <what must remain unchanged>
Acceptance: <focused command or observable check>
Handoff: commit and push the repair branch, then return the commit hash and changed files.
Mode constraint: confirm visible Chat mode before working; do not use Work, Task, Scheduled Task, Project, Canvas, or another mode.
```

Record the current candidate SHA as the next base SHA, increment repair count with `bash scripts/task-state.sh repair ...`, transition to `WAITING_REPAIR`, start a new watcher, pull the next candidate, and repeat acceptance. Keep the original failure evidence in the task record.

Three failed repair attempts are not automatically three native goal turns. Do not call `update_goal(status="blocked")` unless the native goal blocked audit is satisfied: the same blocker must recur across at least three consecutive goal turns and meaningful progress must be impossible without user input or external change.

## Task Completion and Return to Goal

`ACCEPTED` closes only the finite collaboration task. It does not complete the native Codex goal.

After a task reaches `ACCEPTED`:

1. Stop its watcher and persist the accepted SHA.
2. Call `get_goal` and confirm the same bound goal still exists.
3. Reassess the full goal against current authoritative evidence:
   - original objective;
   - referenced PRD, SDD, specs, issues, and plans;
   - repository and runtime state;
   - tests, browser checks, CI, artifacts, and external state.
4. Record which goal requirements this task proved, which remain incomplete, and whether new required work was discovered.
5. If every goal requirement is proven complete and no required work remains, call `update_goal(status="complete")`.
6. If any required work remains:
   - do not call `update_goal`;
   - leave the native goal `active`;
   - choose the next highest-value finite task if the current turn can continue safely, or return control to the native goal runtime so idle continuation starts the next goal turn.
7. Never redefine the goal around the work already completed. Never mark it complete merely because one task, branch, test suite, or budget cycle ended.

The task report must include task ID, commit hash, branch, changed files, validation results, goal evidence, remaining goal work, and one of:

- `Native goal completed and update_goal succeeded.`
- `Native goal remains active; control returned to the Codex goal runtime.`

Do not state that no next task was started when an active native goal still has remaining work.

## Recovery and Safe Continuation

- On restart, call `get_goal` before reading persisted task state.
- If persisted `goal_id` matches the native goal, resume the recorded collaboration state without redispatching.
- If the user explicitly replaced the goal, rebind only after confirming the new objective and recording the change with `task-state.sh set-goal --allow-rebind`.
- If the native goal is missing, unexpectedly complete, non-active, or has a different ID, transition to `BLOCKED_GOAL`; do not guess which objective governs the work.
- Keep one active implementation task at a time unless the user explicitly authorizes parallel work.
- Reuse the approved Chat conversation; do not create a new ChatGPT task or workspace.
- Do not interpret a ChatGPT “done” message as evidence of task or goal completion.
- Do not interpret an observation timeout as evidence of implementation failure.
- Do not make model, package, API, or framework decisions from memory when the repository or official documentation can verify them.
- Do not expose raw prompts, model intermediate output, secrets, credentials, or private repository data in the handoff.
