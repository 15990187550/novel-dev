import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.agents.director import NovelDirector, Phase

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
async def test_brainstorm_start_success(async_session, test_client):
    await DocumentRepository(async_session).create(
        "d1", "n_brain", "worldview", "WV", "天玄大陆"
    )
    await async_session.commit()

    async with test_client as client:
        resp = await client.post("/api/novels/n_brain/brainstorm/start")
        assert resp.status_code == 200
        data = resp.json()
        assert "prompt" in data
        assert "n_brain" in data["prompt"]

        state = await NovelDirector(session=async_session).resume("n_brain")
        assert state.current_phase == Phase.BRAINSTORMING.value


@pytest.mark.asyncio
async def test_brainstorm_start_no_documents(async_session, test_client):
    async with test_client as client:
        resp = await client.post("/api/novels/n_empty/brainstorm/start")
        assert resp.status_code == 400
        assert "文档" in resp.json()["detail"] or "document" in resp.json()["detail"].lower()
