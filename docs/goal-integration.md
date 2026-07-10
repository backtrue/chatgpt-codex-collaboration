# Native Codex Goal Integration

This skill runs beneath Codex's native persisted thread goal. The native goal is not a label copied into prompts; it is the continuation mechanism that keeps Codex working across turns.

## Startup Rule

Before planning a collaboration task:

1. Call `get_goal`.
2. Bind to an active unfinished goal.
3. If no goal exists, or the previous goal is complete, call `create_goal`.
4. Verify the resulting goal with `get_goal`.
5. Refuse dispatch when the goal is missing, non-active, changed unexpectedly, or conflicts with the requested work.

The workflow is explicitly authorized to create a native goal when this skill is activated and no unfinished goal exists. The objective must represent the user's requested end state, not merely the first finite implementation task. Do not set a token budget unless the user explicitly requested one.

## Goal Status Handling

| Status | Workflow behavior |
|---|---|
| `active` | Bind and continue |
| `paused` | Do not replace; require an authorized `/goal resume` |
| `blocked` | Do not replace; require an authorized `/goal resume` after the blocker changes |
| `usage_limited` | Preserve the goal and wait for usage availability or an authorized resume |
| `budget_limited` | Preserve the goal; require a user budget decision |
| `complete` | A new current request may create a new goal |

The model-facing `update_goal` tool is only for `complete` or genuinely `blocked`. Pause, resume, edit, and clear are user/system-controlled goal operations.

## Task Binding

Every finite collaboration task records:

- parent `goal_id`;
- full native goal objective;
- how the finite task advances the goal;
- accepted commit and evidence;
- remaining goal work.

A task must not be dispatched merely because it is easy to implement. Codex must show that it advances the full objective.

## Completion Rule

Task acceptance and goal completion are separate claims.

After task acceptance:

1. Inspect the current repository and external state.
2. Re-read the full goal objective and authoritative references.
3. Identify evidence for every explicit requirement.
4. Record remaining required work.
5. Call `update_goal(status="complete")` only when no required work remains.
6. Otherwise leave the goal active and return control to the native continuation runtime.

Do not narrow the goal to match completed work. Do not complete the goal because a task, test suite, turn, context window, or token cycle ended.

## Blocked Rule

Repair attempts are not goal turns. Mark the native goal blocked only when the same blocking condition recurs for at least three consecutive native goal turns and no meaningful progress is possible without user input or an external-state change.

## Restart Rule

On restart:

1. Call `get_goal`.
2. Load persisted collaboration state.
3. Compare goal IDs.
4. Resume only when they match.
5. If the user explicitly replaced the goal, rebind with `task-state.sh set-goal --allow-rebind`.
6. Otherwise transition to `BLOCKED_GOAL` rather than guessing.
