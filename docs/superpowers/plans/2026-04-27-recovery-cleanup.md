# Recovery Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe recovery cleanup mechanism that releases stale generation jobs, stale chapter auto-run locks, and expired flow stop markers after abnormal process exits.

**Architecture:** Introduce a focused `RecoveryCleanupService` that mutates only control state and reports every action. Add `heartbeat_at` to `generation_jobs`, update the background job runner to heartbeat, expose a manual cleanup endpoint, and run cleanup once on API startup without blocking app availability.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic, PostgreSQL JSON/JSONB-compatible checkpoint data, pytest/pytest-asyncio, httpx ASGI tests.

---

## File Structure

- Create `migrations/versions/20260427_add_generation_job_heartbeat.py`: Alembic migration for `generation_jobs.heartbeat_at`.
- Modify `src/novel_dev/db/models.py`: add `GenerationJob.heartbeat_at`.
- Modify `src/novel_dev/repositories/generation_job_repo.py`: heartbeat and stale-job helpers.
- Create `src/novel_dev/services/recovery_cleanup_service.py`: cleanup options/result models and cleanup logic.
- Modify `src/novel_dev/services/generation_job_service.py`: update heartbeat around background job execution.
- Modify `src/novel_dev/api/routes.py`: add request/response route for manual cleanup.
- Modify `src/novel_dev/api/__init__.py`: add startup cleanup hook.
- Create `tests/test_services/test_recovery_cleanup_service.py`: service behavior tests.
- Modify `tests/test_repositories/test_generation_job_repo.py`: repository heartbeat/stale helpers tests.
- Modify `tests/test_api/test_auto_chapter_generation_routes.py`: route/startup-facing API tests, or create `tests/test_api/test_recovery_cleanup_routes.py` if the file becomes noisy.

## Task 1: Add Job Heartbeat Persistence

**Files:**
- Create: `migrations/versions/20260427_add_generation_job_heartbeat.py`
- Modify: `src/novel_dev/db/models.py`
- Modify: `src/novel_dev/repositories/generation_job_repo.py`
- Test: `tests/test_repositories/test_generation_job_repo.py`

- [ ] **Step 1: Write repository heartbeat tests**

Add these tests to `tests/test_repositories/test_generation_job_repo.py`:

```python
from datetime import datetime, timedelta

import pytest

from novel_dev.repositories.generation_job_repo import GenerationJobRepository


@pytest.mark.asyncio
async def test_generation_job_heartbeat_updates_timestamp(async_session):
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-heartbeat", "chapter_auto_run", {})
    await async_session.commit()

    before = datetime.utcnow()
    await repo.touch_heartbeat(job.id)
    await async_session.commit()

    refreshed = await repo.get_by_id(job.id)
    assert refreshed.heartbeat_at is not None
    assert refreshed.heartbeat_at >= before
    assert refreshed.updated_at >= before


@pytest.mark.asyncio
async def test_generation_job_lists_stale_active_jobs(async_session):
    repo = GenerationJobRepository(async_session)
    stale = await repo.create("novel-stale-job", "chapter_auto_run", {})
    fresh = await repo.create("novel-fresh-job", "chapter_auto_run", {})
    await repo.mark_running(stale.id)
    await repo.mark_running(fresh.id)

    old = datetime.utcnow() - timedelta(hours=3)
    recent = datetime.utcnow()
    stale.heartbeat_at = old
    stale.updated_at = old
    fresh.heartbeat_at = recent
    fresh.updated_at = recent
    await async_session.commit()

    jobs = await repo.list_stale_active(
        stale_queued_before=datetime.utcnow() - timedelta(minutes=30),
        stale_running_before=datetime.utcnow() - timedelta(hours=2),
    )

    assert [job.id for job in jobs] == [stale.id]
```

- [ ] **Step 2: Run repository tests and verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_generation_job_repo.py -q
```

Expected: failure because `heartbeat_at`, `touch_heartbeat`, or `list_stale_active` does not exist.

- [ ] **Step 3: Add migration**

Create `migrations/versions/20260427_add_generation_job_heartbeat.py`:

```python
"""add generation job heartbeat

Revision ID: 20260427_job_heartbeat
Revises: 20260427_document_embedding_dims
Create Date: 2026-04-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260427_job_heartbeat"
down_revision: Union[str, Sequence[str], None] = "20260427_document_embedding_dims"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("generation_jobs", sa.Column("heartbeat_at", sa.TIMESTAMP(), nullable=True))


def downgrade() -> None:
    op.drop_column("generation_jobs", "heartbeat_at")
```

This plan was written against `alembic heads` output `20260427_document_embedding_dims (head)`.

- [ ] **Step 4: Add model field**

In `src/novel_dev/db/models.py`, update `GenerationJob`:

```python
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
```

Place it after `started_at` so lifecycle timestamps stay grouped.

- [ ] **Step 5: Add repository helpers**

In `src/novel_dev/repositories/generation_job_repo.py`, update imports:

```python
from datetime import datetime

from sqlalchemy import or_, select
```

Add methods:

```python
    async def touch_heartbeat(self, job_id: str) -> None:
        job = await self.get_by_id(job_id)
        if not job:
            return
        now = datetime.utcnow()
        job.heartbeat_at = now
        job.updated_at = now
        await self.session.flush()

    async def list_stale_active(
        self,
        *,
        stale_queued_before: datetime,
        stale_running_before: datetime,
    ) -> list[GenerationJob]:
        result = await self.session.execute(
            select(GenerationJob)
            .where(
                GenerationJob.status.in_(ACTIVE_STATUSES),
                or_(
                    (
                        (GenerationJob.status == "queued")
                        & (GenerationJob.updated_at < stale_queued_before)
                    ),
                    (
                        (GenerationJob.status == "running")
                        & (
                            or_(
                                GenerationJob.heartbeat_at < stale_running_before,
                                (
                                    (GenerationJob.heartbeat_at.is_(None))
                                    & (GenerationJob.updated_at < stale_running_before)
                                ),
                                (
                                    (GenerationJob.heartbeat_at.is_(None))
                                    & (GenerationJob.updated_at.is_(None))
                                    & (GenerationJob.started_at < stale_running_before)
                                ),
                            )
                        )
                    ),
                ),
            )
            .order_by(GenerationJob.updated_at.asc(), GenerationJob.created_at.asc())
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def mark_recovered_failed(self, job_id: str, reason: str) -> None:
        job = await self.get_by_id(job_id)
        if not job:
            return
        payload = dict(job.result_payload or {})
        payload.update({"stopped_reason": "failed", "recovered": True})
        await self._mark_terminal(
            job_id,
            "failed",
            result_payload=payload,
            error_message=reason,
        )
```

- [ ] **Step 6: Run repository tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_generation_job_repo.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add migrations/versions/20260427_add_generation_job_heartbeat.py src/novel_dev/db/models.py src/novel_dev/repositories/generation_job_repo.py tests/test_repositories/test_generation_job_repo.py
git commit -m "feat: add generation job heartbeat"
```

## Task 2: Implement Recovery Cleanup Service

**Files:**
- Create: `src/novel_dev/services/recovery_cleanup_service.py`
- Test: `tests/test_services/test_recovery_cleanup_service.py`

- [ ] **Step 1: Write service tests**

Create `tests/test_services/test_recovery_cleanup_service.py`:

```python
from datetime import datetime, timedelta

import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.services.recovery_cleanup_service import (
    RecoveryCleanupOptions,
    RecoveryCleanupService,
)


@pytest.mark.asyncio
async def test_cleanup_marks_stale_running_job_failed(async_session):
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-clean-running", "chapter_auto_run", {})
    await repo.mark_running(job.id)
    old = datetime.utcnow() - timedelta(hours=3)
    job.heartbeat_at = old
    job.updated_at = old
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup(
        RecoveryCleanupOptions(stale_running_minutes=120)
    )

    refreshed = await repo.get_by_id(job.id)
    assert refreshed.status == "failed"
    assert refreshed.result_payload["recovered"] is True
    assert result.cleaned_jobs[0]["job_id"] == job.id


@pytest.mark.asyncio
async def test_cleanup_does_not_mark_fresh_running_job(async_session):
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-fresh-running", "chapter_auto_run", {})
    await repo.mark_running(job.id)
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup(
        RecoveryCleanupOptions(stale_running_minutes=120)
    )

    refreshed = await repo.get_by_id(job.id)
    assert refreshed.status == "running"
    assert result.cleaned_jobs == []


@pytest.mark.asyncio
async def test_cleanup_releases_lock_without_active_job(async_session):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel-lock-only",
        phase=Phase.DRAFTING,
        checkpoint_data={"auto_run_lock": {"active": True, "token": "stale-token"}},
        chapter_id="ch_1",
        volume_id="vol_1",
    )
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup()

    state = await director.resume("novel-lock-only")
    assert "auto_run_lock" not in state.checkpoint_data
    assert state.checkpoint_data["auto_run_last_result"]["recovered"] is True
    assert result.released_locks[0]["novel_id"] == "novel-lock-only"


@pytest.mark.asyncio
async def test_cleanup_keeps_lock_with_fresh_active_job(async_session):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel-fresh-lock",
        phase=Phase.DRAFTING,
        checkpoint_data={"auto_run_lock": {"active": True, "token": "fresh-token"}},
        chapter_id="ch_1",
        volume_id="vol_1",
    )
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-fresh-lock", "chapter_auto_run", {})
    await repo.mark_running(job.id)
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup()

    state = await director.resume("novel-fresh-lock")
    assert "auto_run_lock" in state.checkpoint_data
    assert result.released_locks == []
    assert result.skipped[0]["novel_id"] == "novel-fresh-lock"


@pytest.mark.asyncio
async def test_cleanup_clears_expired_flow_stop(async_session):
    director = NovelDirector(async_session)
    requested_at = (datetime.utcnow() - timedelta(hours=25)).isoformat() + "Z"
    await director.save_checkpoint(
        "novel-old-stop",
        phase=Phase.DRAFTING,
        checkpoint_data={
            "flow_control": {
                "cancel_requested": True,
                "requested_at": requested_at,
                "reason": "user_requested",
            }
        },
        chapter_id="ch_1",
        volume_id="vol_1",
    )
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup(
        RecoveryCleanupOptions(stale_flow_stop_hours=24)
    )

    state = await director.resume("novel-old-stop")
    assert "flow_control" not in state.checkpoint_data
    assert result.cleared_flow_stops[0]["novel_id"] == "novel-old-stop"


@pytest.mark.asyncio
async def test_cleanup_dry_run_does_not_mutate(async_session):
    repo = GenerationJobRepository(async_session)
    job = await repo.create("novel-dry-run", "chapter_auto_run", {})
    await repo.mark_running(job.id)
    old = datetime.utcnow() - timedelta(hours=3)
    job.heartbeat_at = old
    job.updated_at = old
    await async_session.commit()

    result = await RecoveryCleanupService(async_session).run_cleanup(
        RecoveryCleanupOptions(stale_running_minutes=120, dry_run=True)
    )

    refreshed = await repo.get_by_id(job.id)
    assert refreshed.status == "running"
    assert result.cleaned_jobs[0]["job_id"] == job.id
```

- [ ] **Step 2: Run service tests and verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_recovery_cleanup_service.py -q
```

Expected: import failure because `recovery_cleanup_service.py` does not exist.

- [ ] **Step 3: Implement service models and helpers**

Create `src/novel_dev/services/recovery_cleanup_service.py` with:

```python
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import NovelState
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.services.generation_job_service import CHAPTER_AUTO_RUN_JOB
from novel_dev.services.log_service import log_service


class RecoveryCleanupOptions(BaseModel):
    stale_running_minutes: int = Field(default=120, ge=1)
    stale_queued_minutes: int = Field(default=30, ge=1)
    stale_flow_stop_hours: int = Field(default=24, ge=1)
    dry_run: bool = False


class RecoveryCleanupResult(BaseModel):
    cleaned_jobs: list[dict[str, Any]] = Field(default_factory=list)
    released_locks: list[dict[str, Any]] = Field(default_factory=list)
    cleared_flow_stops: list[dict[str, Any]] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)


class RecoveryCleanupService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.job_repo = GenerationJobRepository(session)
        self.state_repo = NovelStateRepository(session)

    async def run_cleanup(
        self,
        options: RecoveryCleanupOptions | None = None,
    ) -> RecoveryCleanupResult:
        opts = options or RecoveryCleanupOptions()
        result = RecoveryCleanupResult()
        recovered_job_ids = await self._cleanup_jobs(opts, result)
        await self._cleanup_auto_run_locks(opts, result, recovered_job_ids)
        await self._cleanup_flow_stops(opts, result)
        if not opts.dry_run:
            await self.session.commit()
        else:
            await self.session.rollback()
        return result
```

- [ ] **Step 4: Implement stale job cleanup**

Add to `RecoveryCleanupService`:

```python
    async def _cleanup_jobs(
        self,
        opts: RecoveryCleanupOptions,
        result: RecoveryCleanupResult,
    ) -> set[str]:
        now = datetime.utcnow()
        jobs = await self.job_repo.list_stale_active(
            stale_queued_before=now - timedelta(minutes=opts.stale_queued_minutes),
            stale_running_before=now - timedelta(minutes=opts.stale_running_minutes),
        )
        recovered: set[str] = set()
        for job in jobs:
            reason = f"Recovered stale {job.status} job after process interruption"
            detail = {
                "job_id": job.id,
                "novel_id": job.novel_id,
                "job_type": job.job_type,
                "previous_status": job.status,
                "reason": reason,
            }
            result.cleaned_jobs.append(detail)
            recovered.add(job.id)
            if opts.dry_run:
                continue
            await self.job_repo.mark_recovered_failed(job.id, reason)
            self._log(job.novel_id, "job_failed", reason, detail)
        return recovered
```

- [ ] **Step 5: Implement lock and flow cleanup**

Add to `RecoveryCleanupService`:

```python
    async def _cleanup_auto_run_locks(
        self,
        opts: RecoveryCleanupOptions,
        result: RecoveryCleanupResult,
        recovered_job_ids: set[str],
    ) -> None:
        states = await self._states_with_checkpoint_key("auto_run_lock")
        for state in states:
            active = await self.job_repo.get_active(state.novel_id, CHAPTER_AUTO_RUN_JOB)
            if active and active.id not in recovered_job_ids:
                result.skipped.append(
                    {
                        "novel_id": state.novel_id,
                        "reason": "fresh active chapter_auto_run job exists",
                        "job_id": active.id,
                    }
                )
                continue

            checkpoint = dict(state.checkpoint_data or {})
            if "auto_run_lock" not in checkpoint:
                continue

            detail = {
                "novel_id": state.novel_id,
                "chapter_id": state.current_chapter_id,
                "volume_id": state.current_volume_id,
                "reason": "Recovered stale auto_run_lock after process interruption",
            }
            result.released_locks.append(detail)
            if opts.dry_run:
                continue

            checkpoint.pop("auto_run_lock", None)
            checkpoint.setdefault(
                "auto_run_last_result",
                {
                    "stopped_reason": "failed",
                    "recovered": True,
                    "error": detail["reason"],
                },
            )
            await self.state_repo.save_checkpoint(
                state.novel_id,
                current_phase=state.current_phase,
                checkpoint_data=checkpoint,
                current_volume_id=state.current_volume_id,
                current_chapter_id=state.current_chapter_id,
            )
            self._log(state.novel_id, "lock_released", detail["reason"], detail)

    async def _cleanup_flow_stops(
        self,
        opts: RecoveryCleanupOptions,
        result: RecoveryCleanupResult,
    ) -> None:
        states = await self._states_with_checkpoint_key("flow_control")
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=opts.stale_flow_stop_hours)
        for state in states:
            checkpoint = dict(state.checkpoint_data or {})
            flow_control = checkpoint.get("flow_control") or {}
            if not flow_control.get("cancel_requested"):
                continue
            requested_at = self._parse_timestamp(flow_control.get("requested_at"))
            active = await self.job_repo.get_active(state.novel_id, CHAPTER_AUTO_RUN_JOB)
            if requested_at and requested_at >= cutoff:
                continue
            if requested_at is None and active:
                result.skipped.append(
                    {
                        "novel_id": state.novel_id,
                        "reason": "invalid flow_control timestamp but active job exists",
                        "job_id": active.id,
                    }
                )
                continue

            detail = {
                "novel_id": state.novel_id,
                "reason": "Cleared expired flow stop marker",
            }
            result.cleared_flow_stops.append(detail)
            if opts.dry_run:
                continue
            checkpoint.pop("flow_control", None)
            await self.state_repo.save_checkpoint(
                state.novel_id,
                current_phase=state.current_phase,
                checkpoint_data=checkpoint,
                current_volume_id=state.current_volume_id,
                current_chapter_id=state.current_chapter_id,
            )
            self._log(state.novel_id, "flow_stop_cleared", detail["reason"], detail)
```

- [ ] **Step 6: Implement shared utilities**

Add to `RecoveryCleanupService`:

```python
    async def _states_with_checkpoint_key(self, key: str) -> list[NovelState]:
        result = await self.session.execute(
            select(NovelState)
            .where(NovelState.checkpoint_data.is_not(None))
            .execution_options(populate_existing=True)
        )
        states = []
        for state in result.scalars().all():
            checkpoint = state.checkpoint_data if isinstance(state.checkpoint_data, dict) else {}
            if key in checkpoint:
                states.append(state)
        return states

    def _parse_timestamp(self, value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.removesuffix("Z"))
        except ValueError:
            return None

    def _log(self, novel_id: str, status: str, message: str, meta: dict[str, Any]) -> None:
        log_service.add_log(
            novel_id,
            "RecoveryCleanup",
            message,
            level="warning",
            event="recovery.cleanup",
            status=status,
            node="recovery",
            task="cleanup",
            meta=meta,
        )
```

- [ ] **Step 7: Run service tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_recovery_cleanup_service.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/novel_dev/services/recovery_cleanup_service.py tests/test_services/test_recovery_cleanup_service.py
git commit -m "feat: add recovery cleanup service"
```

## Task 3: Add Manual Recovery Cleanup API

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Test: `tests/test_api/test_recovery_cleanup_routes.py`

- [ ] **Step 1: Write route tests**

Create `tests/test_api/test_recovery_cleanup_routes.py`:

```python
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.repositories.generation_job_repo import GenerationJobRepository


app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_recovery_cleanup_route_marks_stale_job(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    try:
        repo = GenerationJobRepository(async_session)
        job = await repo.create("novel-route-cleanup", "chapter_auto_run", {})
        await repo.mark_running(job.id)
        old = datetime.utcnow() - timedelta(hours=3)
        job.heartbeat_at = old
        job.updated_at = old
        await async_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/recovery/cleanup",
                json={"stale_running_minutes": 120},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["cleaned_jobs"][0]["job_id"] == job.id
        refreshed = await repo.get_by_id(job.id)
        assert refreshed.status == "failed"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_recovery_cleanup_route_supports_dry_run(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    try:
        repo = GenerationJobRepository(async_session)
        job = await repo.create("novel-route-dry-run", "chapter_auto_run", {})
        await repo.mark_running(job.id)
        old = datetime.utcnow() - timedelta(hours=3)
        job.heartbeat_at = old
        job.updated_at = old
        await async_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/recovery/cleanup",
                json={"stale_running_minutes": 120, "dry_run": True},
            )

        assert response.status_code == 200
        assert response.json()["cleaned_jobs"][0]["job_id"] == job.id
        refreshed = await repo.get_by_id(job.id)
        assert refreshed.status == "running"
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run route tests and verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_recovery_cleanup_routes.py -q
```

Expected: 404 for `/api/recovery/cleanup`.

- [ ] **Step 3: Add imports and route**

In `src/novel_dev/api/routes.py`, add imports:

```python
from novel_dev.services.recovery_cleanup_service import (
    RecoveryCleanupOptions,
    RecoveryCleanupService,
)
```

Add route near generation job routes:

```python
@router.post("/api/recovery/cleanup")
async def run_recovery_cleanup(
    req: RecoveryCleanupOptions = RecoveryCleanupOptions(),
    session: AsyncSession = Depends(get_session),
):
    result = await RecoveryCleanupService(session).run_cleanup(req)
    return result.model_dump()
```

- [ ] **Step 4: Run route tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_recovery_cleanup_routes.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_recovery_cleanup_routes.py
git commit -m "feat: expose recovery cleanup endpoint"
```

## Task 4: Add Startup Cleanup Hook

**Files:**
- Modify: `src/novel_dev/api/__init__.py`
- Test: `tests/test_api/test_recovery_cleanup_startup.py`

- [ ] **Step 1: Write startup helper tests**

Create `tests/test_api/test_recovery_cleanup_startup.py`:

```python
import pytest

from novel_dev.api import run_startup_recovery_cleanup


@pytest.mark.asyncio
async def test_startup_recovery_cleanup_swallows_errors(monkeypatch):
    class FailingService:
        def __init__(self, session):
            self.session = session

        async def run_cleanup(self):
            raise RuntimeError("cleanup exploded")

    class DummySession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr("novel_dev.api.async_session_maker", lambda: DummySession())
    monkeypatch.setattr("novel_dev.api.RecoveryCleanupService", FailingService)

    await run_startup_recovery_cleanup()
```

- [ ] **Step 2: Run startup test and verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_recovery_cleanup_startup.py -q
```

Expected: import failure because `run_startup_recovery_cleanup` does not exist.

- [ ] **Step 3: Add startup hook**

In `src/novel_dev/api/__init__.py`, update imports:

```python
from contextlib import asynccontextmanager

from novel_dev.db.engine import async_session_maker
from novel_dev.services.log_service import log_service
from novel_dev.services.recovery_cleanup_service import RecoveryCleanupService
```

Add helper and lifespan before creating `app`:

```python
async def run_startup_recovery_cleanup() -> None:
    try:
        async with async_session_maker() as session:
            await RecoveryCleanupService(session).run_cleanup()
    except Exception as exc:
        log_service.add_log(
            "system",
            "RecoveryCleanup",
            f"启动恢复清理失败: {exc}",
            level="error",
            event="recovery.cleanup",
            status="startup_failed",
            node="recovery",
            task="startup_cleanup",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_startup_recovery_cleanup()
    yield
```

Then change app creation:

```python
app = FastAPI(lifespan=lifespan)
```

- [ ] **Step 4: Run startup test**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_recovery_cleanup_startup.py -q
```

Expected: test passes.

- [ ] **Step 5: Run API route smoke tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_recovery_cleanup_routes.py tests/test_api/test_auto_chapter_generation_routes.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/api/__init__.py tests/test_api/test_recovery_cleanup_startup.py
git commit -m "feat: run recovery cleanup on startup"
```

## Task 5: Heartbeat Background Generation Jobs

**Files:**
- Modify: `src/novel_dev/services/generation_job_service.py`
- Test: `tests/test_api/test_auto_chapter_generation_routes.py`

- [ ] **Step 1: Write heartbeat test**

Add to `tests/test_api/test_auto_chapter_generation_routes.py`:

```python
@pytest.mark.asyncio
async def test_auto_run_background_job_updates_heartbeat(async_session):
    plan = build_test_volume("vol_heartbeat_bg", "ch_heartbeat_bg")
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_auto_heartbeat_bg",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "current_volume_plan": plan.model_dump(),
            "current_chapter_plan": plan.chapters[0].model_dump(),
        },
        volume_id="vol_heartbeat_bg",
        chapter_id="ch_heartbeat_bg_1",
    )
    repo = GenerationJobRepository(async_session)
    job = await repo.create(
        "n_auto_heartbeat_bg",
        "chapter_auto_run",
        {"max_chapters": 1, "stop_at_volume_end": True},
    )
    await async_session.commit()

    from novel_dev.services.generation_job_service import run_generation_job

    await run_generation_job(job.id)

    refreshed = await repo.get_by_id(job.id)
    assert refreshed.heartbeat_at is not None
    assert refreshed.finished_at is not None
    assert refreshed.heartbeat_at <= refreshed.finished_at
```

- [ ] **Step 2: Run heartbeat test and verify failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_auto_chapter_generation_routes.py::test_auto_run_background_job_updates_heartbeat -q
```

Expected: failure because `run_generation_job()` does not touch heartbeat yet.

- [ ] **Step 3: Update job runner heartbeat**

In `src/novel_dev/services/generation_job_service.py`, update `run_generation_job()`:

```python
        await repo.mark_running(job_id)
        await repo.touch_heartbeat(job_id)
        await session.commit()
```

Before calling `service.auto_run()`:

```python
            await repo.touch_heartbeat(job_id)
            await session.commit()
            result = await service.auto_run(
                job.novel_id,
                max_chapters=request.get("max_chapters", 1),
                stop_at_volume_end=request.get("stop_at_volume_end", True),
            )
            await repo.touch_heartbeat(job_id)
```

In both exception branches, call heartbeat before terminal marking:

```python
        except AutoRunFailedError as exc:
            await repo.touch_heartbeat(job_id)
            await repo.mark_failed(job_id, exc.result.model_dump(), exc.result.error or str(exc))
            await session.commit()
            return
        except Exception as exc:
            log_service.add_log(job.novel_id, "GenerationJobService", f"后台生成任务失败: {exc}", level="error")
            await repo.touch_heartbeat(job_id)
            await repo.mark_failed(job_id, {}, str(exc))
            await session.commit()
            return
```

Keep the existing terminal status semantics unchanged.

- [ ] **Step 4: Run auto generation tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_auto_chapter_generation_routes.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/generation_job_service.py tests/test_api/test_auto_chapter_generation_routes.py
git commit -m "feat: heartbeat background generation jobs"
```

## Task 6: Full Verification and Migration Check

**Files:**
- No new files unless fixes are needed.

- [ ] **Step 1: Check Alembic heads**

Run:

```bash
alembic heads
```

Expected: one current head, including `20260427_job_heartbeat`.

- [ ] **Step 2: Run focused backend tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_generation_job_repo.py tests/test_services/test_recovery_cleanup_service.py tests/test_api/test_recovery_cleanup_routes.py tests/test_api/test_recovery_cleanup_startup.py tests/test_api/test_auto_chapter_generation_routes.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run syntax check**

Run:

```bash
python3.11 -m py_compile src/novel_dev/services/recovery_cleanup_service.py src/novel_dev/services/generation_job_service.py src/novel_dev/repositories/generation_job_repo.py src/novel_dev/api/routes.py src/novel_dev/api/__init__.py
```

Expected: no output and exit code 0.

- [ ] **Step 4: Run diff whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 5: Apply migration locally**

Run:

```bash
alembic upgrade head
```

Expected: migration applies successfully.

- [ ] **Step 6: Restart local service**

Run:

```bash
./scripts/run_local.sh
```

Expected: API and embedding service start successfully.

- [ ] **Step 7: Smoke test health and manual cleanup**

Run:

```bash
curl -sf http://127.0.0.1:8000/healthz
curl -sS -X POST http://127.0.0.1:8000/api/recovery/cleanup -H 'Content-Type: application/json' -d '{"dry_run": true}'
```

Expected:

```json
{"ok":true}
```

The cleanup response should include keys `cleaned_jobs`, `released_locks`, `cleared_flow_stops`, and `skipped`.

- [ ] **Step 8: Final commit if verification required fixes**

If Step 6 exposed fixes, commit them:

```bash
git add <changed-files>
git commit -m "fix: stabilize recovery cleanup"
```

## Self-Review

- Spec coverage: The plan covers heartbeat persistence, stale job recovery, lock cleanup, flow stop cleanup, persistent logging, startup cleanup, manual API, dry-run behavior, and focused tests.
- Scope check: The plan keeps first release limited to control-state residue and does not migrate unrelated long flows.
- Type consistency: The plan consistently uses `RecoveryCleanupOptions`, `RecoveryCleanupResult`, `RecoveryCleanupService.run_cleanup()`, `GenerationJobRepository.touch_heartbeat()`, `GenerationJobRepository.list_stale_active()`, and `GenerationJobRepository.mark_recovered_failed()`.
- Placeholder scan: No task uses placeholder implementation text; each code-changing step includes exact files and concrete snippets.
