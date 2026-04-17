import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.document_repo import DocumentRepository

app = FastAPI()
app.include_router(router)


@pytest.fixture
def test_client(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_brainstorm_and_volume_plan_flow(async_session, test_client, mock_llm_factory):
    await DocumentRepository(async_session).create(
        "d1", "n_outline", "worldview", "WV", "天玄大陆"
    )

    async with test_client as client:
        resp = await client.post("/api/novels/n_outline/brainstorm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "天玄纪元"

        state = await NovelDirector(session=async_session).resume("n_outline")
        assert state.current_phase == Phase.VOLUME_PLANNING.value

        resp2 = await client.post("/api/novels/n_outline/volume_plan", json={})
        assert resp2.status_code == 200
        plan = resp2.json()
        assert plan["volume_id"] == "vol_1"
        assert len(plan["chapters"]) > 0

        state2 = await NovelDirector(session=async_session).resume("n_outline")
        assert state2.current_phase == Phase.CONTEXT_PREPARATION.value


@pytest.mark.asyncio
async def test_get_synopsis(async_session, test_client, mock_llm_factory):
    await DocumentRepository(async_session).create(
        "d1", "n_syn", "worldview", "WV", "大陆"
    )
    async with test_client as client:
        await client.post("/api/novels/n_syn/brainstorm")
        resp = await client.get("/api/novels/n_syn/synopsis")
        assert resp.status_code == 200
        assert "content" in resp.json()


@pytest.mark.asyncio
async def test_get_volume_plan(async_session, test_client, mock_llm_factory):
    await DocumentRepository(async_session).create(
        "d1", "n_vp", "worldview", "WV", "大陆"
    )
    async with test_client as client:
        await client.post("/api/novels/n_vp/brainstorm")
        await client.post("/api/novels/n_vp/volume_plan", json={})
        resp = await client.get("/api/novels/n_vp/volume_plan")
        assert resp.status_code == 200
        assert resp.json()["volume_id"] == "vol_1"


@pytest.mark.asyncio
async def test_volume_plan_wrong_phase(async_session, test_client):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_wrong", phase=Phase.DRAFTING, checkpoint_data={}, volume_id="v1", chapter_id="c1"
    )
    async with test_client as client:
        resp = await client.post("/api/novels/n_wrong/volume_plan", json={})
        assert resp.status_code == 400
