import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from datetime import datetime, timedelta

from novel_dev.api.routes import router, get_session
from novel_dev.db.models import ABDecision


app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session

    return override


@pytest.mark.asyncio
async def test_list_recent_decisions(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        for i in range(3):
            async_session.add(ABDecision(
                experiment_id="exp_1",
                action="evaluate",
                decision_at=datetime.utcnow() - timedelta(minutes=i),
                scores={"v1": 75.0 + i},
                meta={"i": i},
            ))
        await async_session.flush()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/ab-decisions/recent?window_minutes=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["decisions"]) == 3
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_decisions_by_experiment(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        for exp in ["exp_a", "exp_b"]:
            async_session.add(ABDecision(
                experiment_id=exp,
                action="accept",
                decision_at=datetime.utcnow(),
                scores={"v1": 75.0},
                meta={},
            ))
        await async_session.flush()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/ab-decisions/by-experiment/exp_a")
        assert resp.status_code == 200
        assert resp.json()["experiment_id"] == "exp_a"
        assert len(resp.json()["decisions"]) == 1
    finally:
        app.dependency_overrides.clear()
