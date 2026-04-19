import re
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_create_novel(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels", json={"title": "测试小说"})
            assert resp.status_code == 201
            data = resp.json()
            assert data["novel_id"].startswith("novel-")
            assert data["current_phase"] == "brainstorming"
            assert data["checkpoint_data"]["synopsis_data"]["title"] == "测试小说"
            assert data["checkpoint_data"]["synopsis_data"]["estimated_volumes"] == 1
            assert data["current_volume_id"] is None
            assert data["current_chapter_id"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_novel_empty_title(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels", json={"title": "  "})
            assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()
