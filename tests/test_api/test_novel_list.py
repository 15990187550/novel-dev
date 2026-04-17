import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_list_novels(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    from novel_dev.repositories.novel_state_repo import NovelStateRepository
    repo = NovelStateRepository(async_session)
    await repo.save_checkpoint("n1", current_phase="volume_planning", checkpoint_data={})
    await repo.save_checkpoint("n2", current_phase="drafting", checkpoint_data={})
    await async_session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 2
            ids = {i["novel_id"] for i in data["items"]}
            assert ids == {"n1", "n2"}
    finally:
        app.dependency_overrides.clear()
