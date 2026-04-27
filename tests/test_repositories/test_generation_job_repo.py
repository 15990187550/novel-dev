from datetime import datetime, timedelta

import pytest

from novel_dev.repositories.generation_job_repo import GenerationJobRepository


@pytest.mark.asyncio
async def test_generation_job_lifecycle(async_session):
    repo = GenerationJobRepository(async_session)

    job = await repo.create(
        novel_id="novel-job",
        job_type="chapter_auto_run",
        request_payload={"max_chapters": 1},
    )
    assert job.status == "queued"

    active = await repo.get_active("novel-job", "chapter_auto_run")
    assert active.id == job.id

    await repo.mark_running(job.id)
    running = await repo.get_by_id(job.id)
    assert running.status == "running"
    assert running.started_at is not None

    await repo.mark_succeeded(job.id, {"stopped_reason": "max_chapters_reached"})
    done = await repo.get_by_id(job.id)
    assert done.status == "succeeded"
    assert done.result_payload["stopped_reason"] == "max_chapters_reached"
    assert done.finished_at is not None
    assert await repo.get_active("novel-job", "chapter_auto_run") is None


@pytest.mark.asyncio
async def test_generation_job_active_scope_is_per_novel(async_session):
    repo = GenerationJobRepository(async_session)
    first = await repo.create("novel-a", "chapter_auto_run", {})
    second = await repo.create("novel-b", "chapter_auto_run", {})

    assert (await repo.get_active("novel-a", "chapter_auto_run")).id == first.id
    assert (await repo.get_active("novel-b", "chapter_auto_run")).id == second.id


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
