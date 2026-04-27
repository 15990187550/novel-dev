import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.api.routes import get_session, router
from novel_dev.services.flow_control_service import clear_cancel_request


app = FastAPI()
app.include_router(router)


@pytest.fixture(autouse=True)
def clear_flow_cancel_registry():
    clear_cancel_request("novel-stop")


@pytest.mark.asyncio
async def test_stop_current_flow_marks_checkpoint(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        director = NovelDirector(session=async_session)
        await director.save_checkpoint(
            "novel-stop",
            phase=Phase.DRAFTING,
            checkpoint_data={"drafting_progress": {"beat_index": 2}},
            volume_id="vol_1",
            chapter_id="ch_1",
        )

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/novels/novel-stop/flow/stop")

        assert response.status_code == 200
        assert response.json()["stop_requested"] is True
        state = await director.resume("novel-stop")
        assert state.checkpoint_data["drafting_progress"] == {"beat_index": 2}
        assert state.checkpoint_data["flow_control"]["cancel_requested"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stop_current_flow_returns_404_for_missing_novel(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/novels/missing/flow/stop")

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
