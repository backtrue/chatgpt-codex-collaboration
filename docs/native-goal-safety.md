# Native Goal Safety

The native Codex thread goal and the collaboration task state are separate state machines.

## Core Invariant

A collaboration task state must not directly mutate the native goal status.

The following collaboration states are task-local only:

- `CAPABILITY_CHECK`
- `WAITING_HANDOFF`
- `BLOCKED_CAPABILITY`
- `BLOCKED_TRANSPORT`
- `BLOCKED_OBSERVATION`
- `BLOCKED_SPEC`
- `BLOCKED_USER`
- `REPAIR_REQUIRED`

Entering any of these states does **not** authorize:

- `update_goal(status="blocked")`;
- `/goal pause`;
- `/goal clear`;
- replacing the goal objective.

## Native Goal Blocking Rule

The native goal may be marked `blocked` only when all of the following are true:

1. the same blocker has persisted across at least three consecutive native goal turns;
2. no executor-profile downgrade, transport fallback, repair contract, or local verification path exists;
3. no meaningful progress is possible without user input or an external-state change;
4. the blocker applies to the complete goal rather than only to the current collaboration task;
5. exact blocker evidence is preserved.

A missing ChatGPT local checkout or shell does not satisfy this rule when `github_connector` can still create a candidate commit.

## Native Goal Pause Rule

This skill must never pause the native goal automatically.

Pause is allowed only when:

- the user explicitly requests it; or
- the environment presents an authorized user/system goal-control action and the user has explicitly approved temporary pause for the current blocker.

If a stable blocking await exists, keep the goal active and keep the current Codex turn active instead of pausing.

## Capability Fallback

When implementation reports `NO_LOCAL_EXECUTOR`, `NO_SHELL`, or `NO_LOCAL_CHECKOUT`:

1. stop the current Git watcher;
2. keep the native goal active;
3. transition the collaboration task to `CAPABILITY_CHECK`;
4. rerun the handshake;
5. when GitHub read/write/commit/push is available, choose `github_connector`;
6. redispatch a profile-aware contract with `deferred_to_codex` validation;
7. start a new watcher and blocking await.

Only enter `BLOCKED_CAPABILITY` when no profile can create a candidate commit.

## Recovery from an Incorrect Terminal Goal

If an older workflow incorrectly changed the native goal to `blocked` or `paused`:

1. preserve the current goal ID and objective;
2. use the native goal UI/control to resume the same goal;
3. do not create a replacement goal;
4. stop any stale watcher;
5. migrate and load the existing collaboration task state;
6. transition the task to `CAPABILITY_CHECK`;
7. run a new capability handshake;
8. continue with the selected profile.

If the goal objective was also changed, require the user to confirm the authoritative objective before resuming.
