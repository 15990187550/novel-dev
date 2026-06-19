import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.db.models import PromptVersion


app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session

    return override


@pytest.mark.asyncio
async def test_create_and_list_ab_experiment(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True)
        pv2 = PromptVersion(agent_name="writer", version="v2", content="b")
        async_session.add_all([pv1, pv2])
        await async_session.flush()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/ab-tests",
                json={"agent_name": "writer", "baseline_version": "v1", "challenger_version": "v2"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["agent_name"] == "writer"
        assert "id" in data
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stop_ab_experiment(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        from novel_dev.services.ab_test_runner import ABTestRunner

        pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True)
        pv2 = PromptVersion(agent_name="writer", version="v2", content="b")
        async_session.add_all([pv1, pv2])
        await async_session.flush()

        runner = ABTestRunner(async_session)
        ab = await runner.start(agent_name="writer", baseline_version="v1", challenger_version="v2")

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/ab-tests/{ab.id}/stop")
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()
