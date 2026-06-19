import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from unittest.mock import AsyncMock, patch

from novel_dev.api.routes import router, get_session


app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session

    return override


@pytest.mark.asyncio
async def test_trigger_sweep_returns_decisions(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("novel_dev.services.ab_acceptance_sweeper.ABAcceptanceSweeper") as MockSweeper:
                mock = AsyncMock()
                mock.tick = AsyncMock(return_value=[{"action": "timeout", "experiment_id": "ab_1"}])
                MockSweeper.return_value = mock
                resp = await client.post("/api/ab-sweeper/tick")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["decisions"]) == 1
        assert data["decisions"][0]["action"] == "timeout"
    finally:
        app.dependency_overrides.clear()
