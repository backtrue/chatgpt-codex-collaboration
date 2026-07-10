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
Mode constraint: use this existing Chat conversation in Chat mode only; do not use Work, Task, Scheduled Task, Project, Canvas, or another mode.
```

Ask ChatGPT to stop rather than guess when it finds a missing spec decision. Do not send credentials, secrets, tokens, private files, or unrelated repository data.

## GitHub Handoff Gate

Treat the handoff as incomplete until ChatGPT provides a pushed branch and commit hash.

Check:

1. The pushed branch is the assigned branch.
2. The commit exists on the remote.
3. The changed-file list stays within the allowed scope.
4. The commit does not include generated archives, secrets, temporary files, or unrelated work.
5. The repository worktree state is understood before pulling or merging.

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

Pull the new commit and repeat acceptance. Keep the original failure evidence in the task record. If the same blocker repeats three times or requires a user decision, stop and report the blocker instead of sending speculative repairs.

## Completion Gate

Report completion only after all of these are true:

- ChatGPT’s implementation commit is present on the remote.
- Codex has independently inspected the diff.
- Every required acceptance command passed.
- Browser checks passed when the task has a frontend surface.
- The authoritative spec and acceptance audit were checked line by line.
- No deterministic fallback or unapproved behavior was introduced.
- The worktree has no unexplained changes.

The final report must include the task id, commit hash, pushed branch, changed files, validation commands and results, spec acceptance summary, and the explicit statement that no next task was started.

## Safe Continuation Rules

- Keep one active implementation task at a time unless the user explicitly authorizes parallel work.
- Reuse the approved Chat conversation; do not create a new ChatGPT task or workspace.
- Do not interpret a ChatGPT “done” message as evidence of completion.
- Do not make model, package, API, or framework decisions from memory when the repository or official documentation can verify them.
- Do not expose raw prompts, model intermediate output, secrets, credentials, or private repository data in the handoff.
