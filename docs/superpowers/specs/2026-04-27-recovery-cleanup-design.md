# Recovery Cleanup Design

## Purpose

Long-running flows can leave control-state residue when the API process exits unexpectedly, the host is killed, or an in-process background task is cancelled without reaching its normal `finally` path. The immediate symptom is a stale generation lock or active job that blocks the next run even though no worker is alive.

This design adds a safe recovery cleanup mechanism. The first release targets residue that can be identified without guessing about business data:

- stale `generation_jobs` rows in `queued` or `running`
- stale `auto_run_lock` entries in `novel_state.checkpoint_data`
- expired `flow_control.cancel_requested` markers

The cleanup service does not repair or rewrite generated chapter text, extracted entities, documents, embeddings, or other content records.

## Goals

- Release stale locks after abnormal process exit or system kill.
- Mark stale background jobs terminal so new work can start.
- Keep cleanup decisions auditable through persistent logs.
- Avoid interrupting legitimately running flows.
- Provide both startup cleanup and a manual cleanup endpoint.
- Establish a common recovery pattern that later flows can adopt.

## Non-Goals

- No full queue system replacement in this step.
- No automatic business-data rollback.
- No automatic retry of failed generation or extraction work.
- No migration of every existing long flow to the job model in this step.

## Current Context

`chapter_auto_run` uses `generation_jobs` as a persisted task table and stores a runtime lock in `novel_state.checkpoint_data.auto_run_lock`. `schedule_generation_job()` starts the worker with `asyncio.create_task()`, so the worker is tied to the API process lifetime. If that process exits before the task finishes, the database may still show a `running` job and the checkpoint may still contain an active lock.

`FlowControlService` stores stop requests in both memory and `checkpoint_data.flow_control`. After restart, the memory set is empty but the persisted stop marker remains. That is useful for honoring recent stop requests, but old markers should not indefinitely affect future operations.

## Architecture

Add `RecoveryCleanupService` under `src/novel_dev/services/`.

The service exposes one main method:

```python
async def run_cleanup(options: RecoveryCleanupOptions | None = None) -> RecoveryCleanupResult
```

`RecoveryCleanupOptions` contains conservative defaults:

- `stale_queued_minutes`: 30
- `stale_running_minutes`: 120
- `stale_flow_stop_hours`: 24
- `dry_run`: false

`RecoveryCleanupResult` contains structured counts and details:

- `cleaned_jobs`
- `released_locks`
- `cleared_flow_stops`
- `skipped`

Each detail includes `novel_id`, relevant IDs, and a reason string.

## Startup Cleanup

Add a FastAPI startup or lifespan hook in `src/novel_dev/api/__init__.py`.

Startup cleanup runs once after the app starts. It should:

- open its own DB session
- call `RecoveryCleanupService.run_cleanup()`
- catch and log cleanup errors
- never prevent the API from starting

The startup path uses default thresholds and normal cleanup mode. It does not run in a loop.

## Manual Cleanup Endpoint

Add:

```http
POST /api/recovery/cleanup
```

Request body:

```json
{
  "stale_running_minutes": 120,
  "stale_queued_minutes": 30,
  "stale_flow_stop_hours": 24,
  "dry_run": false
}
```

The endpoint returns the `RecoveryCleanupResult`. `dry_run` computes the same actions but does not mutate rows. This is useful before widening cleanup rules later.

## Generation Job Recovery

Add `heartbeat_at TIMESTAMP NULL` to `generation_jobs`.

The repository gains methods to:

- update heartbeat for a job
- list stale active jobs by threshold
- mark a stale job as recovered failure

`run_generation_job()` updates `heartbeat_at`:

- after marking the job `running`
- before entering chapter generation
- after chapter generation returns or raises

The first release may still use `updated_at` or `started_at` as a fallback when `heartbeat_at` is null. Staleness is evaluated as:

- `queued`: `updated_at` or `created_at` older than `stale_queued_minutes`
- `running`: `heartbeat_at`, `updated_at`, or `started_at` older than `stale_running_minutes`

Stale active jobs are marked:

- `status = "failed"`
- `finished_at = now`
- `updated_at = now`
- `error_message = "Recovered stale <status> job after process interruption"`
- `result_payload` merged or set with `{"stopped_reason": "failed", "recovered": true}`

Optional columns `recovered_at` and `recovery_reason` can be added later if recovery reporting needs first-class fields. For the first release, `error_message` and `result_payload` are enough.

## Auto-Run Lock Recovery

For each `novel_state` containing `checkpoint_data.auto_run_lock`:

1. Find active `chapter_auto_run` jobs for the same novel.
2. If no active job exists, remove `auto_run_lock`.
3. If active jobs existed but were marked terminal by this cleanup pass, remove `auto_run_lock`.
4. If a non-stale active job remains, keep the lock and add a `skipped` entry.

When a lock is released, preserve the rest of `checkpoint_data`. If an `auto_run_last_result` is absent, write a compact recovery result:

```json
{
  "stopped_reason": "failed",
  "recovered": true,
  "error": "Recovered stale auto_run_lock after process interruption"
}
```

## Flow Stop Cleanup

For each `novel_state.checkpoint_data.flow_control` with `cancel_requested = true`:

- parse `requested_at`
- if it is older than `stale_flow_stop_hours`, remove `flow_control`
- if it is missing or invalid, treat it as stale only when the novel has no active generation job
- if it is recent, keep it

This avoids erasing a user stop request shortly after they clicked stop.

## Logging

Every mutation writes a persistent log through `log_service.add_log()` with:

- `agent = "RecoveryCleanup"`
- `event = "recovery.cleanup"`
- `status` matching the action, such as `job_failed`, `lock_released`, or `flow_stop_cleared`
- `node = "recovery"`
- `task = "cleanup"`
- metadata containing job IDs, thresholds, and reasons

Startup-level exceptions are logged with `level = "error"` and do not abort app startup.

## Safety Rules

- Cleanup only mutates control state: job status, checkpoint locks, and old stop markers.
- It never edits generated content or extraction output.
- It does not clean a job if its latest heartbeat is within the running threshold.
- It does not release an `auto_run_lock` when a fresh active job exists for the same novel.
- It continues after per-novel cleanup errors and records skipped items.
- It is idempotent: running cleanup twice should not produce additional mutations after the first pass.

## Testing

Backend tests should cover:

- stale `running` job is marked failed and no longer active
- stale `queued` job is marked failed and no longer active
- fresh active job is not cleaned
- stale `auto_run_lock` is released when no active job exists
- lock remains when a fresh active job exists
- lock is released when its active job is recovered in the same cleanup pass
- expired `flow_control.cancel_requested` is cleared
- recent stop marker is preserved
- `dry_run` returns planned actions without mutating rows
- startup hook invokes cleanup and swallows cleanup exceptions

Existing auto-run tests should continue to pass.

## Rollout

1. Add migration and model/repository support for `heartbeat_at`.
2. Add `RecoveryCleanupService` and focused unit tests.
3. Add manual cleanup API tests.
4. Add startup cleanup hook test.
5. Update `run_generation_job()` to heartbeat active jobs.
6. Run backend route/repository/service tests.

Later releases can migrate setting extraction, document merging, outline planning, and backfill jobs to the same job and heartbeat pattern.
