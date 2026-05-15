import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.db.models import NovelState


app = FastAPI()
app.include_router(router)


def genre_payload(title="分类小说", primary="xuanhuan", secondary="zhutian"):
    return {
        "title": title,
        "primary_category_slug": primary,
        "secondary_category_slug": secondary,
    }


@pytest.mark.asyncio
async def test_list_novel_categories(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/novel-categories")
            assert resp.status_code == 200
            data = resp.json()
            xuanhuan = next(item for item in data if item["slug"] == "xuanhuan")
            assert xuanhuan["name"] == "玄幻"
            assert any(child["slug"] == "zhutian" for child in xuanhuan["children"])
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_novel_requires_matching_primary_and_secondary(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            missing = await client.post("/api/novels", json={"title": "缺分类"})
            assert missing.status_code == 422

            mismatch = await client.post("/api/novels", json=genre_payload(primary="xuanhuan", secondary="workplace_business"))
            assert mismatch.status_code == 422

            ok = await client.post("/api/novels", json=genre_payload())
            assert ok.status_code == 201
            data = ok.json()
            assert data["genre"]["primary_slug"] == "xuanhuan"
            assert data["genre"]["secondary_slug"] == "zhutian"
            assert data["checkpoint_data"]["genre"]["primary_name"] == "玄幻"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_state_for_historical_novel_returns_default_genre(async_session):
    async_session.add(NovelState(novel_id="n_legacy_genre", current_phase="brainstorming", checkpoint_data={"novel_title": "旧书"}))
    await async_session.commit()

    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/novels/n_legacy_genre/state")
            assert resp.status_code == 200
            data = resp.json()
            assert data["genre"] == {
                "primary_slug": "general",
                "primary_name": "通用",
                "secondary_slug": "uncategorized",
                "secondary_name": "未分类",
            }
            assert data["checkpoint_data"]["genre"] == data["genre"]
    finally:
        app.dependency_overrides.clear()
