# ChatGPT Executor Capability Handshake

The capability handshake runs before implementation dispatch. Its purpose is to prevent impossible task contracts and watcher deadlocks.

## Why it exists

Opening a ChatGPT conversation does not prove that the conversation can:

- access the assigned repository;
- create or update files;
- use a local checkout;
- run shell commands and tests;
- create a commit on the assigned branch.

A task must not enter `WAITING_HANDOFF` until the actual executor profile is known.

## Handshake response

ChatGPT returns one JSON object conforming to `capabilityHandshake` in `contracts/collaboration.schema.json`.

```json
{
  "schema_version": "2.0",
  "status": "ready",
  "executor_profile": "github_connector",
  "repository_read": true,
  "repository_write": true,
  "local_checkout": false,
  "shell": false,
  "git_commit": true,
  "git_push": true,
  "external_network": false,
  "can_run_acceptance": false,
  "blocker_code": null,
  "blocker_detail": null,
  "observed_at": "2026-07-11T00:00:00Z"
}
```

## Profiles

### `local_full`

ChatGPT has a local checkout and can run commands.

Requirements:

- repository read and write;
- local checkout;
- shell;
- commit and push;
- focused acceptance commands.

Task policy:

```text
implementation_validation_policy = implementer_required
candidate_commit_without_tests = false
```

Codex still reruns acceptance independently.

### `github_connector`

ChatGPT can modify and commit the assigned branch through a GitHub connector, but cannot run local commands.

Task policy:

```text
implementation_validation_policy = deferred_to_codex
candidate_commit_without_tests = true
```

ChatGPT must:

- make the implementation changes;
- create a candidate commit;
- mark unavailable command results as `not_run`;
- return `verification_status = pending_codex_verification`.

Codex must fetch the candidate and run all required acceptance locally.

Missing shell access is not a blocker under this profile.

### `read_only`

ChatGPT can inspect the repository but cannot create a candidate commit. Transition to `BLOCKED_CAPABILITY` before starting a watcher.

### `none`

No usable repository access exists. Transition to `BLOCKED_CAPABILITY` before starting a watcher.

## Runtime capability drift

A handshake can become stale or be inaccurate. For example, ChatGPT may initially report `local_full` and later fail to clone because network access is unavailable.

When this occurs:

1. emit `implementation_blocked` through `transport-event.sh`;
2. stop the Git watcher;
3. return the task to `CAPABILITY_CHECK`;
4. run the handshake again;
5. downgrade to `github_connector` when branch commit capability remains available;
6. otherwise enter `BLOCKED_CAPABILITY`.

Do not continue waiting for a commit after the implementer has declared that no legal commit path exists.

## Terminal transport events

The ChatGPT transport adapter writes local JSONL events under:

```text
~/.codex/collaboration/events/<task-id>.jsonl
```

Example:

```sh
sh "$SKILL_ROOT/scripts/transport-event.sh" emit \
  TASK-001 implementation_blocked \
  --source chatgpt-ui \
  --code NO_LOCAL_EXECUTOR \
  --reason "No local checkout or shell is available"
```

The blocking await monitors this file together with the Git watcher log. Terminal transport events wake Codex immediately and stop the Git watcher.
