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
2. Identify the exact spec lines, allowed files, forbidden changes, acceptance commands, and required output fields.
3. Run `spec-discovery-gate` and `spec-task-audit-list` when the repository workflow requires them.
4. Split the work into one finite implementation task. One ChatGPT prompt must map to one task and one acceptance bundle.
5. Do not send a task when the required behavior is not explicit in the spec. Ask the user for the missing decision instead.
6. Create the assigned remote branch before dispatch and record its current remote HEAD as the handoff base SHA.
7. Persist the task ID, conversation URL, repository, branch, base SHA, dispatch time, and observation-lease settings outside the repository worktree.

## Implementation Handoff

Send ChatGPT a compact task contract containing:

```text
Task: <single finite task id and objective>
Repository: <repository URL>
Branch: <implementation branch>
Authoritative spec: <file and line references>
Allowed files: <exact files or directories>
Forbidden: <behavior and files that must not change>
Acceptance: <commands and observable outcomes>
Required handoff: edit the files, run the acceptance commands, commit, push the branch, and return commit hash, changed files, tests, and blockers.
Push discipline: do not push partial progress to the assigned branch. Push only a candidate handoff after the required checks have run.
Mode constraint: use this existing Chat conversation in Chat mode only; do not use Work, Task, Scheduled Task, Project, Canvas, or another mode.
```

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
- If the UI shows an explicit failure, disconnected session, authentication problem, or mode drift, report the exact blocker.
- If the state cannot be determined, mark the task `blocked-observation`; do not label the implementation failed.

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

Check:

1. The pushed branch is the assigned branch.
2. The commit exists on the remote and differs from the recorded base SHA.
3. The changed-file list stays within the allowed scope.
4. The commit does not include generated archives, secrets, temporary files, or unrelated work.
5. The repository worktree state is understood before pulling or merging.
6. The candidate commit was not accepted solely because the watcher observed a branch change.

If ChatGPT says it changed files but did not push, do not copy the files into the working tree by default. Send one repair request asking it to commit and push. Accept an attached patch or archive only when the user explicitly authorizes that fallback for the current task; inspect it as untrusted input and still require a local commit before acceptance.

Never force-push, reset the user’s worktree, or discard unrelated changes.

## Codex Acceptance

After the remote handoff:

1. Fetch the assigned branch and inspect the commit diff.
2. Re-read the authoritative spec around every changed behavior.
3. Run the task-specific acceptance commands before broader regression commands.
4. Inspect error paths, boundary cases, logging, security fields, and forbidden fallback behavior.
5. For frontend work, verify the actual local page with the browser at required desktop and mobile sizes.
6. Run `spec-acceptance-audit` before reporting completion.
7. Check the audit list. No requested row may remain unchecked or be silently moved out of scope.

Accept only when the implementation, tests, observable behavior, and changed-file scope all match the spec. A passing test suite does not override a spec mismatch.

## Failed Acceptance Loop

When acceptance fails, do not patch the failed implementation locally. Create a repair handoff in the same approved Chat conversation:

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

Record the current repair-branch HEAD as the next base SHA, start a new deterministic watcher, pull the new candidate commit, and repeat acceptance. Keep the original failure evidence in the task record. If the same blocker repeats three times or requires a user decision, stop and report the blocker instead of sending speculative repairs.

## Completion Gate

Report completion only after all of these are true:

- ChatGPT’s implementation commit is present on the remote.
- Codex has independently inspected the diff.
- Every required acceptance command passed.
- Browser checks passed when the task has a frontend surface.
- The authoritative spec and acceptance audit were checked line by line.
- No deterministic fallback or unapproved behavior was introduced.
- The worktree has no unexplained changes.
- Every watcher or background observation process for the task has been stopped.

The final report must include the task ID, commit hash, pushed branch, changed files, validation commands and results, spec acceptance summary, and the explicit statement that no next task was started.

## Safe Continuation Rules

- Keep one active implementation task at a time unless the user explicitly authorizes parallel work.
- Reuse the approved Chat conversation; do not create a new ChatGPT task or workspace.
- Do not interpret a ChatGPT “done” message as evidence of completion.
- Do not interpret an observation timeout as evidence of implementation failure.
- Do not make model, package, API, or framework decisions from memory when the repository or official documentation can verify them.
- Do not expose raw prompts, model intermediate output, secrets, credentials, or private repository data in the handoff.
