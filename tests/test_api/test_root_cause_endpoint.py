import pytest


@pytest.mark.asyncio
async def test_get_root_cause_for_chapter(async_session):
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    from novel_dev.api.routes import router, get_session
    from novel_dev.repositories.root_cause_repo import RootCauseRepository

    repo = RootCauseRepository(async_session)
    await repo.persist(
        chapter_id="ch_1", analyzer_version="v1.0",
        summary="test summary",
        suggested_actions=[{"action": "x", "target": "y", "severity": "high"}],
        confidence=0.8, input_snapshot={},
    )

    app = FastAPI()
    app.include_router(router)

    def override():
        return async_session
    app.dependency_overrides[get_session] = override

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/chapters/ch_1/root-cause")
            assert resp.status_code == 200
            data = resp.json()
            assert data["summary"] == "test summary"
            assert data["confidence"] == 0.8
            assert len(data["suggested_actions"]) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_root_cause_empty_404(async_session):
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    from novel_dev.api.routes import router, get_session

    app = FastAPI()
    app.include_router(router)

    def override():
        return async_session
    app.dependency_overrides[get_session] = override

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/chapters/nonexistent/root-cause")
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
