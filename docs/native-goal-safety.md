# Native Goal Safety

The native Codex thread goal and the collaboration task are separate state machines.

## Core Invariant

A collaboration task blocker must not be promoted into a native goal blocker.

These states are task-local:

- `CAPABILITY_CHECK`
- `WAITING_HANDOFF`
- `BLOCKED_CAPABILITY`
- `BLOCKED_TRANSPORT`
- `BLOCKED_OBSERVATION`
- `BLOCKED_SPEC`
- `BLOCKED_USER`
- `REPAIR_REQUIRED`

Entering any of them does not authorize:

- `update_goal(status="blocked")`;
- clearing the goal;
- replacing the goal objective;
- permanently pausing the goal;
- creating repeated “still blocked” turns.

## Native Goal Blocking Rule

The native goal may be marked `blocked` only when all are true:

1. the same blocker persists across at least three consecutive native goal turns;
2. no executor downgrade, transport fallback, repair contract, local verification path, user action, or external-state change can make progress;
3. the blocker prevents the complete objective, not only the current task;
4. exact evidence is preserved.

A missing ChatGPT local checkout or shell does not satisfy this rule while `github_connector` can still create a candidate commit.

## Authorized Transport Suspension

A temporary `paused` status is allowed only as a transport suspension after a valid implementation dispatch.

The suspension must satisfy every condition:

1. the task is already in `WAITING_HANDOFF` or `WAITING_REPAIR`;
2. capability handshake selected an accepted executor profile;
3. the assigned remote branch exists and its HEAD equals the recorded base SHA;
4. the implementation contract was successfully sent;
5. `CODEX_THREAD_ID` is known;
6. a launchd event supervisor is successfully installed;
7. the supervisor is configured to reactivate the same goal and run `codex exec resume` on a terminal event;
8. the same goal ID and objective are preserved.

This pause means only:

```text
external implementer is working
→ no Codex model turn is required
→ native continuation is suspended until transport evidence arrives
```

It must not be described as blocked, failed, abandoned, or waiting for user intervention.

If LaunchAgent creation fails, restore the goal to `active` before returning an error.

If automatic Codex resume fails, return the same goal to `paused`, emit a macOS notification, and preserve the wake event so the user can retry. Do not mark the goal blocked.

The resume controller must create an in-flight marker before starting `codex exec resume`.
While that marker is active, duplicate events for the same task must not start another
resume. The resumed turn must not inspect or control the ChatGPT UI. If the resume
exceeds the bounded 300-second window, terminate it, leave the same goal paused, and
preserve the original event for recovery after new evidence.

## Blocking Await Is Not a Safety Mechanism

The formal workflow must not rely on a long-running shell command to keep a Codex turn active.

The execution platform may force command termination after several minutes. Repeated `await` calls can create:

```text
command timeout
→ active goal continuation
→ another waiting turn
→ token and capacity consumption
```

Therefore `macos-watcher.sh await` is disabled in the formal workflow. Event-driven suspend and resume is required.

## Capability Fallback

When implementation reports `NO_LOCAL_EXECUTOR`, `NO_SHELL`, or `NO_LOCAL_CHECKOUT`:

1. stop any stale supervisor;
2. reactivate the same goal if it is temporarily paused;
3. transition the task to `CAPABILITY_CHECK`;
4. rerun the handshake;
5. choose `github_connector` when remote branch read/write/commit/push remains available;
6. prepare the remote branch at the exact base SHA;
7. redispatch a `deferred_to_codex` contract;
8. begin a new event-driven suspension.

Only enter `BLOCKED_CAPABILITY` when no accepted profile can create a candidate commit.

## Invalid Completion Receipt

A response with all tests `not_run` and `verification_status=pending_codex_verification` is valid only when it also contains a real remote candidate commit SHA.

Without a commit SHA, the response is `conversation_completed_no_commit`, not a handoff and not a reason to keep waiting indefinitely.

## Recovery from Older Incorrect State

When an older workflow left the same native goal blocked or paused:

1. preserve the goal ID and objective;
2. stop stale blocking-await LaunchAgents;
3. reactivate the same goal once;
4. load and migrate the existing task state;
5. rerun capability handshake;
6. verify or create the remote handoff branch at base SHA;
7. redispatch the profile-aware contract;
8. use event-driven suspension.

Do not create a replacement goal.
