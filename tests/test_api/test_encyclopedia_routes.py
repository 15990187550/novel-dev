import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_list_entities(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = EntityRepository(async_session)
    await repo.create("e1", "character", "Lin Feng", novel_id="n1")
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/entities")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 1
            assert data["items"][0]["name"] == "Lin Feng"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_timelines(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = TimelineRepository(async_session)
    await repo.create(tick=1, narrative="Start", novel_id="n1")
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/timelines")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_spacelines(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = SpacelineRepository(async_session)
    await repo.create("loc_1", "Qingyun", novel_id="n1")
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/spacelines")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_foreshadowings(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    repo = ForeshadowingRepository(async_session)
    await repo.create(fs_id="fs_1", content="Hint", novel_id="n1")
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/foreshadowings")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 1
    finally:
        app.dependency_overrides.clear()
