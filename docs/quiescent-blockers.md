# Stable Blocker Quiescence

A collaboration task may enter a stable task-local blocker such as `BLOCKED_TRANSPORT` without the complete native goal being blocked.

If the native goal remains active after the resumed Codex turn completes, the native goal runtime can immediately create another continuation turn. Without a state change, this produces repeated messages such as:

```text
Task 050 status unchanged: BLOCKED_TRANSPORT
```

This is a control-plane loop, not useful progress.

## Required Behavior

The wake controller enforces quiescence at the `turn.completed` event.

1. Read the persisted collaboration task state.
2. Check whether a successor supervisor generation was created during the resumed turn.
3. If no successor exists and the task remains in a stable blocked state, set the same native goal to `paused` immediately.
4. Preserve the goal ID and objective.
5. Do not set the native goal to `blocked`.
6. Do not create another user-visible status message for the same condition fingerprint.
7. Record a quiescence marker under `~/.codex/collaboration/wakes`.

Stable blocker states:

- `BLOCKED_GOAL`
- `BLOCKED_SPEC`
- `BLOCKED_CAPABILITY`
- `BLOCKED_DEPENDENCY`
- `BLOCKED_TRANSPORT`
- `BLOCKED_OBSERVATION`
- `BLOCKED_USER`
- `FAILED`
- `CANCELLED`

Orphaned asynchronous states without a successor supervisor are also quiesced:

- `DISPATCHING`
- `IMPLEMENTING`
- `WAITING_HANDOFF`
- `WAITING_REPAIR`

## Wake Deduplication

Wake conditions are deduplicated by a stable SHA-256 fingerprint over:

- task ID;
- dispatch ID;
- event type;
- candidate SHA;
- normalized event payload.

The random transport `event_id` is deliberately excluded. Re-emitting the same blocker with a new UUID must not start another Codex turn.

Only one wake process may hold the per-task wake lock at a time.

## Immediate Stop Command

For a task already producing repeated continuation turns:

```sh
SKILL_ROOT="$HOME/.agents/skills/chatgpt-codex-collaboration"

sh "$SKILL_ROOT/scripts/quiesce-task.sh" <task-id>
```

The command:

- verifies that the task is blocked or orphaned;
- stops the current LaunchAgent supervisor;
- pauses the same native goal through Codex app-server;
- preserves the goal ID, objective, branch, task state, and evidence;
- writes `~/.codex/collaboration/wakes/<task-id>.quiescent.json`.

When running outside the originating Codex shell and no wake configuration is available, provide the thread explicitly:

```sh
sh "$SKILL_ROOT/scripts/quiesce-task.sh" <task-id> \
  --thread-id <CODEX_THREAD_ID> \
  --repo /absolute/path/to/repository
```

## Resume Rule

Resume only after new evidence or an actionable recovery path exists.

Examples:

- GitHub/network access is restored;
- a valid candidate commit appears;
- the ChatGPT transport adapter is repaired;
- the user supplies a missing product decision;
- capability recovery selects a usable executor profile.

Resume the same native goal and the same persisted task. Do not create a replacement goal merely to escape quiescence.
