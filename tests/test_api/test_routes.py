import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_get_novel_state_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/novels/novel_x/state")
    assert response.status_code == 404
