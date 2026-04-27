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
        job_id = await _create_stale_running_job(async_session, "novel-route-stale")

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/recovery/cleanup",
                json={"stale_running_minutes": 120},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["cleaned_jobs"][0] == job_id

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
        job_id = await _create_stale_running_job(async_session, "novel-route-dry-run")

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/recovery/cleanup",
                json={"stale_running_minutes": 120, "dry_run": True},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["cleaned_jobs"][0] == job_id

        refreshed = await GenerationJobRepository(async_session).get_by_id(job_id)
        assert refreshed.status == "running"
    finally:
        app.dependency_overrides.clear()
