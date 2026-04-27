from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.repositories.generation_job_repo import GenerationJobRepository


app = FastAPI()
app.include_router(router)


async def _create_stale_running_job(async_session, novel_id: str):
    repo = GenerationJobRepository(async_session)
    job = await repo.create(novel_id, "chapter_auto_run", {})
    await repo.mark_running(job.id)
    old = datetime.utcnow() - timedelta(hours=3)
    job.heartbeat_at = old
    job.updated_at = old
    job_id = job.id
    await async_session.commit()
    return job_id


@pytest.mark.asyncio
async def test_recovery_cleanup_route_marks_stale_job(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        novel_id = "novel-route-stale"
        job_id = await _create_stale_running_job(async_session, novel_id)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/recovery/cleanup",
                json={"stale_running_minutes": 120},
            )

        assert response.status_code == 200
        data = response.json()
        cleaned_job = data["cleaned_jobs"][0]
        assert cleaned_job["job_id"] == job_id
        assert cleaned_job["novel_id"] == novel_id
        assert cleaned_job["job_type"] == "chapter_auto_run"
        assert cleaned_job["previous_status"] == "running"
        assert cleaned_job["reason"] == "Recovered stale running job after process interruption"

        refreshed = await GenerationJobRepository(async_session).get_by_id(job_id)
        assert refreshed.status == "failed"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_recovery_cleanup_route_supports_dry_run(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        novel_id = "novel-route-dry-run"
        job_id = await _create_stale_running_job(async_session, novel_id)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/recovery/cleanup",
                json={"stale_running_minutes": 120, "dry_run": True},
            )

        assert response.status_code == 200
        data = response.json()
        cleaned_job = data["cleaned_jobs"][0]
        assert cleaned_job["job_id"] == job_id
        assert cleaned_job["novel_id"] == novel_id
        assert cleaned_job["job_type"] == "chapter_auto_run"
        assert cleaned_job["previous_status"] == "running"
        assert cleaned_job["reason"] == "Recovered stale running job after process interruption"

        refreshed = await GenerationJobRepository(async_session).get_by_id(job_id)
        assert refreshed.status == "running"
    finally:
        app.dependency_overrides.clear()
