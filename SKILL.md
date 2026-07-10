---
name: chatgpt-codex-collaboration
description: Coordinate a two-agent coding workflow in which ChatGPT performs one scoped implementation task in an existing Chat conversation, pushes the result to GitHub, and Codex pulls, verifies against the authoritative spec, rejects or returns corrections, and closes the task only after acceptance. Use when implementation and acceptance must be separated, when a user requires ChatGPT to edit code and Codex to validate it, or when the workflow must avoid ChatGPT Work, Task, Scheduled Task, Project, Canvas, or other alternate execution modes.
---

# ChatGPT-Codex Collaboration

Use this skill to keep implementation and acceptance independent:

- ChatGPT is the implementer.
- Codex is the specification owner, verifier, and release gate.
- GitHub is the handoff boundary.
- The user decides unresolved product behavior and whether the workflow may continue after a blocked handoff.

Do not let ChatGPT declare acceptance. Do not let Codex silently implement a failed handoff that was assigned to ChatGPT.

## Operational Files

Use the bundled files rather than recreating their behavior from memory:

- `dependencies.yaml`: required commands, capabilities, conditional skills, and fallbacks.
- `config/executor.example.yaml`: executor capability and restriction profile.
- `contracts/collaboration.schema.json`: task, repair, event, handoff, acceptance, and task-state contracts.
- `scripts/check-dependencies.sh`: command dependency check.
- `scripts/preflight.sh`: repository and execution preflight.
- `scripts/task-state.sh`: persistent state controller.
- `scripts/wait-for-handoff.sh`: token-free branch watcher.
- `scripts/validate-handoff.sh`: remote SHA and changed-scope validation.
- `docs/architecture.md`: transport, execution, state, dependency, and recovery architecture.

Persist task state outside the repository worktree, normally under `~/.codex/collaboration/tasks`.

## Non-Negotiable Mode Gate

Use only the existing ChatGPT conversation supplied by the user. Before every message sent to ChatGPT:

1. Navigate to the approved conversation URL.
2. Inspect the visible page state or DOM and confirm the active mode is `Chat`.
3. If the active mode is `Work`, `Task`, `Scheduled Task`, `Project`, `Canvas`, or any other mode that is not plain `Chat`, stop before sending the prompt.
4. Do not click a mode switch, create a task, create a project, schedule work, open Work mode, or use a mode-changing shortcut to continue.
5. Report the exact visible mode and wait for the user to restore `Chat` mode.

A prompt cannot override the UI mode. Text saying “stay in Chat mode” is an additional guard, not proof that the active mode is Chat.

## Start Gate

Before assigning implementation work:

1. Inspect `~/.codex/agents/*.toml`, repo-local agent instructions, and the authoritative spec files.
2. Run `bash scripts/check-dependencies.sh`. Missing required commands or a repo-required conditional skill transitions the task to `BLOCKED_DEPENDENCY`.
3. Identify the exact spec lines, allowed files, forbidden changes, acceptance commands, and required output fields.
4. Run `spec-discovery-gate` and `spec-task-audit-list` only when repo-local instructions require them. Do not silently approximate a missing required audit.
5. Split the work into one finite implementation task. One ChatGPT prompt must map to one task and one acceptance bundle.
6. Do not send a task when required behavior is not explicit in the spec. Transition to `BLOCKED_SPEC` and ask the user for the missing decision.
7. Run `bash scripts/preflight.sh <repo-path> <remote> <branch> [required-command ...]`. Missing execution capability transitions the task to `BLOCKED_CAPABILITY`.
8. Create the assigned remote branch before dispatch and record its current remote HEAD as the handoff base SHA.
9. Create persistent state with `bash scripts/task-state.sh create ...`, then transition `DISCOVERING → READY → DISPATCHING` as each gate passes.
10. Persist the task ID, conversation URL, repository, branch, base SHA, dispatch ID, message fingerprint, dispatch time, and observation settings outside the worktree.

## Implementation Handoff

Build the dispatch from the `taskContract` definition in `contracts/collaboration.schema.json`. Send ChatGPT a compact task contract containing:

```text
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

- Keep the authoritative spec and acceptance bundle on disk; do not replay them during each observation.
- Persist a compact task-state record outside the worktree and rehydrate only after a terminal watcher event.
- Use `git ls-remote` or an equivalent small transport query while waiting; fetch the candidate commit only once it appears.
- Do not request periodic prose status updates from ChatGPT.
- Do not produce recurring summaries of unchanged state.
- After a candidate commit appears, load only the task contract, changed diff, relevant spec sections, and acceptance results into the active verification context.

If the environment supports an event-driven push webhook or notification hook, prefer that over polling. The event handler should wake the verifier only after the assigned branch changes.

## GitHub Handoff Gate

Treat the handoff as incomplete until ChatGPT provides a pushed branch and commit hash.

1. Record the candidate SHA and transition `WAITING_HANDOFF` or `WAITING_REPAIR → HANDOFF_CANDIDATE`.
2. Run `bash scripts/validate-handoff.sh <repo-path> <remote> <branch> <base-sha> <candidate-sha> <allowed-path>...`.
3. Confirm the pushed branch is the assigned branch.
4. Confirm the candidate is the current remote HEAD and differs from the recorded base SHA.
5. Confirm changed files stay within the allowed scope.
6. Confirm the commit does not include generated archives, secrets, temporary files, or unrelated work.
7. Confirm the repository worktree state is understood before pulling or merging.
8. Do not accept a candidate solely because the watcher observed a branch change.

If ChatGPT says it changed files but did not push, do not copy the files into the working tree by default. Send one repair request asking it to commit and push. Accept an attached patch or archive only when the user explicitly authorizes that fallback for the current task; inspect it as untrusted input and still require a local commit before acceptance.

Never force-push, reset the user’s worktree, or discard unrelated changes.

## Codex Acceptance

After the handoff gate passes, transition `HANDOFF_CANDIDATE → VERIFYING`:

1. Fetch the assigned branch and inspect the commit diff.
2. Re-read the authoritative spec around every changed behavior.
3. Run the task-specific acceptance commands before broader regression commands.
4. Inspect error paths, boundary cases, logging, security fields, and forbidden fallback behavior.
5. For frontend work, verify the actual local page with the browser at required desktop and mobile sizes.
6. Run `spec-acceptance-audit` when repo-local instructions require it.
7. Check the audit list. No requested row may remain unchecked or be silently moved out of scope.
8. Produce an `acceptanceResult` conforming to `contracts/collaboration.schema.json`.

Accept only when the implementation, tests, observable behavior, and changed-file scope all match the spec. A passing test suite does not override a spec mismatch. Only `VERIFYING` may transition to `ACCEPTED`.

## Failed Acceptance Loop

When acceptance fails, transition `VERIFYING → REPAIR_REQUIRED`. Do not patch the failed implementation locally. Create a repair contract conforming to `repairContract` in the schema:

```text
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

Record the current candidate SHA as the next base SHA, increment repair count with `bash scripts/task-state.sh repair ...`, transition to `WAITING_REPAIR`, start a new watcher, pull the next candidate, and repeat acceptance. Keep the original failure evidence in the task record. If the same blocker repeats three times or requires a user decision, transition to `BLOCKED_USER` instead of sending speculative repairs.

## Completion Gate

Report completion only after all of these are true:

- ChatGPT’s implementation commit is present on the remote.
- Codex has independently inspected the diff.
- Every required acceptance command passed.
- Browser checks passed when the task has a frontend surface.
- The authoritative spec and required acceptance audit were checked line by line.
- No deterministic fallback or unapproved behavior was introduced.
- The worktree has no unexplained changes.
- Every watcher or background observation process for the task has been stopped.
- Task state contains the accepted SHA and is `ACCEPTED`.

The final report must include the task ID, commit hash, pushed branch, changed files, validation commands and results, spec acceptance summary, and the explicit statement that no next task was started.

## Recovery and Safe Continuation

- On restart, read persisted task state before taking any action. Do not redispatch automatically.
- Keep one active implementation task at a time unless the user explicitly authorizes parallel work.
- Reuse the approved Chat conversation; do not create a new ChatGPT task or workspace.
- Do not interpret a ChatGPT “done” message as evidence of completion.
- Do not interpret an observation timeout as evidence of implementation failure.
- Do not make model, package, API, or framework decisions from memory when the repository or official documentation can verify them.
- Do not expose raw prompts, model intermediate output, secrets, credentials, or private repository data in the handoff.
