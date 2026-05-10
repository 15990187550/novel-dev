import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from unittest.mock import patch

from novel_dev.api.routes import router, get_session

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_get_novel_state_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/novels/novel_x/state")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_novel_passes_data_dir_to_service(tmp_path):
    captured = {}

    class FakeDeletionService:
        def __init__(self, session, data_dir):
            captured["session"] = session
            captured["data_dir"] = data_dir

        async def delete_novel(self, novel_id):
            captured["novel_id"] = novel_id
            return True

    session = object()

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    mock_settings = type("MockSettings", (), {"data_dir": str(tmp_path)})()
    transport = ASGITransport(app=app)
    try:
        with (
            patch("novel_dev.api.routes.NovelDeletionService", FakeDeletionService),
            patch("novel_dev.api.routes.settings", mock_settings),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.delete("/api/novels/n_delete")

        assert response.status_code == 204
        assert captured == {
            "session": session,
            "data_dir": str(tmp_path),
            "novel_id": "n_delete",
        }
    finally:
        app.dependency_overrides.clear()
