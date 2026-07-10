# Native Codex Goal Integration

This skill runs beneath Codex's native persisted thread goal. The native goal is the continuation mechanism for the complete objective; the collaboration task is only one finite implementation-and-acceptance cycle.

## Startup Rule

Before planning a task:

1. Call `get_goal`.
2. Bind to an active unfinished goal.
3. If no goal exists or the previous goal is complete, call `create_goal` using the user's requested end state.
4. Verify the resulting goal with `get_goal`.
5. Refuse dispatch when goal identity is missing, changed unexpectedly, or conflicts with the requested work.

Do not shrink the goal to the first implementation task. Do not set a token budget unless explicitly requested.

## Goal and Task Are Separate State Machines

The following are collaboration task states, not native goal statuses:

- `CAPABILITY_CHECK`
- `WAITING_HANDOFF`
- `BLOCKED_CAPABILITY`
- `BLOCKED_TRANSPORT`
- `BLOCKED_OBSERVATION`
- `BLOCKED_SPEC`
- `BLOCKED_USER`
- `REPAIR_REQUIRED`

Entering one of these states must not call `update_goal(status="blocked")`, must not pause the goal, and must not replace the objective.

A missing ChatGPT local checkout, shell, or test runner is a task executor issue. When GitHub connector commits are available, the workflow must downgrade to `github_connector` and defer validation to Codex.

## Goal Status Handling

| Native status | Workflow behavior |
|---|---|
| `active` | Bind and continue |
| `paused` | Preserve the same goal; require one authorized `/goal resume` |
| `blocked` | Preserve the same goal; resume only after the complete-goal blocker changes |
| `usage_limited` | Preserve the goal and wait for usage availability |
| `budget_limited` | Preserve the goal and require a budget decision |
| `complete` | A new request may create a new goal |

Pause, resume, edit, and clear are user/system-controlled operations. This skill must not pause automatically.

## Native Blocked Rule

Mark the native goal blocked only when every condition holds:

1. the same blocker recurs across at least three consecutive native goal turns;
2. no executor downgrade, transport fallback, repair contract, or local verification path exists;
3. no meaningful progress is possible without user input or external-state change;
4. the blocker prevents the complete objective, not only the current task;
5. exact evidence is persisted.

Repair attempts and await cycles are not native goal turns.

## Capability Recovery

When an implementation reports `NO_LOCAL_EXECUTOR`, `NO_SHELL`, or `NO_LOCAL_CHECKOUT`:

1. leave the native goal active;
2. stop the stale watcher;
3. transition the task to `CAPABILITY_CHECK`;
4. rerun the handshake;
5. choose `github_connector` when branch read/write/commit/push remains available;
6. redispatch a `deferred_to_codex` contract;
7. let Codex run all acceptance locally.

Do not mark the native goal blocked for this condition.

## Task Binding

Every task records:

- parent goal ID;
- complete objective;
- task contribution;
- executor profile;
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
6. otherwise keep the goal active.

Do not redefine the goal around completed work.

## Recovery from Older Incorrect Goal State

If an older skill version incorrectly changed the native goal to `blocked` or `paused`:

1. preserve the same goal ID and objective;
2. do not create a replacement goal;
3. use one authorized `/goal resume` action;
4. run `scripts/recover-capability.sh <task-id>`;
5. rerun the capability handshake;
6. continue with a profile-aware contract.

Do not repeatedly emit “goal remains blocked” turns.

## Restart Rule

On restart:

1. call `get_goal`;
2. load persisted task state;
3. compare goal IDs;
4. resume only when they match;
5. if the user explicitly replaced the goal, rebind only after confirmation;
6. otherwise enter the task-local `BLOCKED_GOAL` state without mutating native goal status.
