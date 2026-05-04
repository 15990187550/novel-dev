import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router


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
async def test_create_setting_generation_session_returns_session_and_initial_message(test_client):
    async with test_client as client:
        response = await client.post(
            "/api/novels/novel-api/settings/sessions",
            json={
                "title": "修炼体系补全",
                "initial_idea": "主角从废脉开始修炼",
                "target_categories": ["功法", "体系设定"],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["title"] == "修炼体系补全"
        assert payload["status"] == "clarifying"
        assert payload["target_categories"] == ["功法", "体系设定"]

        detail = await client.get(f"/api/novels/novel-api/settings/sessions/{payload['id']}")
        assert detail.status_code == 200
        detail_payload = detail.json()
        assert detail_payload["session"]["id"] == payload["id"]
        assert detail_payload["messages"][0]["role"] == "user"
        assert detail_payload["messages"][0]["content"] == "主角从废脉开始修炼"


@pytest.mark.asyncio
async def test_list_setting_generation_sessions(test_client):
    async with test_client as client:
        created = await client.post(
            "/api/novels/novel-api/settings/sessions",
            json={
                "title": "主角阵营设定",
                "initial_idea": "",
                "target_categories": ["人物"],
            },
        )
        assert created.status_code == 200

        response = await client.get("/api/novels/novel-api/settings/sessions")
        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["title"] == "主角阵营设定"
