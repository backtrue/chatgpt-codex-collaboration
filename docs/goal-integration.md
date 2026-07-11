# Native Codex Goal Integration

This skill runs beneath Codex's persisted thread goal. The native goal owns the complete objective; a collaboration task is one finite implementation-and-acceptance cycle.

## Startup Rule

Before planning a task:

1. call `get_goal`;
2. bind to an active unfinished goal;
3. if no goal exists or the previous goal is complete, call `create_goal` using the user's requested end state;
4. verify the resulting goal;
5. refuse dispatch when goal identity is missing, unexpectedly changed, or conflicts with the requested work.

Do not shrink the goal to the first task. Do not set a token budget unless explicitly requested.

## Goal and Task Are Separate State Machines

These are collaboration task states, not native goal statuses:

- `CAPABILITY_CHECK`
- `WAITING_HANDOFF`
- `BLOCKED_CAPABILITY`
- `BLOCKED_TRANSPORT`
- `BLOCKED_OBSERVATION`
- `BLOCKED_SPEC`
- `BLOCKED_USER`
- `REPAIR_REQUIRED`

A task blocker must not call `update_goal(status="blocked")`, clear the goal, replace its objective, or create repeated waiting turns.

A missing ChatGPT local checkout, shell, or test runner is an executor issue. If GitHub connector commits remain available, select `github_connector` and defer validation to Codex.

## Native Status Handling

| Native status | Workflow behavior |
|---|---|
| `active` | Plan, dispatch, verify, or continue goal work |
| `paused` with active wake config | External ChatGPT transport wait; event supervisor owns resume |
| `paused` without wake config | Preserve goal and require explicit recovery |
| `blocked` | Preserve goal; resume only after complete-goal blocker changes |
| `usage_limited` | Preserve goal and wait for usage availability |
| `budget_limited` | Preserve goal and require a budget decision |
| `complete` | A new request may create a new goal |

## Event-Driven Transport Suspension

After a valid task dispatch, Codex no longer has useful model work until Git or transport evidence arrives.

The formal workflow temporarily sets the same goal to `paused` through the local app-server and starts a launchd event supervisor.

This suspension is valid only when:

- the capability handshake selected `local_full` or `github_connector`;
- the remote branch exists at the recorded base SHA;
- the task contract was sent successfully;
- `CODEX_THREAD_ID` is available;
- wake configuration is persisted;
- LaunchAgent bootstrap succeeds.

The current Codex turn then ends. No blocking `await` is used.

When a terminal event arrives, the supervisor:

1. sets the same goal back to `active` through app-server;
2. runs `codex exec resume <CODEX_THREAD_ID> <event prompt>`;
3. continues the same persisted thread and task;
4. preserves goal ID and objective.

If resume fails, the supervisor returns the goal to `paused`, sends a macOS notification, and leaves evidence for retry.

## Native Blocked Rule

Mark the native goal blocked only when every condition holds:

1. the same blocker recurs across at least three consecutive native goal turns;
2. no executor downgrade, transport fallback, repair, local verification path, user action, or external-state change can make progress;
3. the blocker prevents the complete objective rather than only one task;
4. exact evidence is persisted.

Transport suspension turns and failed shell waits are not evidence for this audit.

## Remote Branch Rule

Before ChatGPT implementation begins, the assigned remote branch must exist and its HEAD must equal the recorded base SHA.

Run:

```sh
sh "$SKILL_ROOT/scripts/prepare-handoff-branch.sh" \
  <repo> <remote> <branch> <base-sha>
```

Do not rely on a local branch name or prose claim.

## Strict Receipt Rule

Task completion requires a real remote commit.

For `status=completed`, the receipt must contain:

- a non-null candidate commit SHA;
- changed files;
- no blockers;
- implementer verification or pending Codex verification.

`pending_codex_verification` without a commit is `conversation_completed_no_commit` and must wake Codex for protocol recovery.

## Task Binding

Every task records:

- parent goal ID;
- complete objective;
- task contribution;
- executor profile;
- branch and base SHA;
- accepted commit and evidence;
- remaining goal work.

## Completion Rule

Task acceptance and goal completion are separate claims.

After task acceptance:

1. inspect repository and external state;
2. reread the complete objective and authoritative references;
3. identify evidence for every requirement;
4. record remaining work;
5. call `update_goal(status="complete")` only when no required work remains;
6. otherwise keep the goal active and select the next task.

Do not redefine the goal around completed work.

## Recovery from Legacy Waits

When an older workflow is stuck in blocking await or incorrectly paused/blocked:

1. preserve the same goal ID and objective;
2. stop the stale LaunchAgent;
3. reactivate the same goal once;
4. migrate and load task state;
5. rerun capability handshake;
6. prepare the remote branch at base SHA;
7. reject any prior response that lacks a commit SHA;
8. redispatch with a strict receipt contract;
9. start event-driven suspension.

Do not create a replacement goal and do not restart blocking await.

## Restart Rule

On restart:

1. call `get_goal`;
2. load persisted task and wake state;
3. compare goal IDs;
4. inspect LaunchAgent, resume log, remote branch, and transport events;
5. continue only when goal identity matches;
6. if the user explicitly replaced the goal, rebind only after confirmation.
