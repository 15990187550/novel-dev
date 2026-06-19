import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.db.models import JudgePromptVersion

app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session

    return override


@pytest.mark.asyncio
async def test_list_judge_prompt_versions(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    async_session.add(pv)
    await async_session.flush()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/judge-prompt-versions")
        assert resp.status_code == 200
        data = resp.json()
        assert any(d["version"] == "v1" for d in data)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_judge_prompt_version(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/judge-prompt-versions", json={
                "version": "judge-v1",
                "agent_name": "judge_agent",
                "prompt_text": "你是一位...",
            })
        assert resp.status_code == 201
        data = resp.json()
        assert data["version"] == "judge-v1"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_activate_judge_prompt_version(async_session):
    pv = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="a", is_active=False)
    async_session.add(pv)
    await async_session.flush()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/judge-prompt-versions/{pv.id}/activate")
        assert resp.status_code == 200
        await async_session.refresh(pv)
        assert pv.is_active is True
    finally:
        app.dependency_overrides.clear()
