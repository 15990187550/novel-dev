import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session

app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session

    return override


@pytest.mark.asyncio
async def test_list_versions(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/prompts/writer/versions",
                json={"version": "v1.0", "content": "hello"},
            )
            resp = await client.get("/api/prompts/writer/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["versions"]) == 1
        assert data["versions"][0]["version"] == "v1.0"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_version(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/prompts/writer/versions",
                json={"version": "v1.0", "content": "hi", "is_active": True},
            )
        assert resp.status_code == 201
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_duplicate_version_409(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/prompts/writer/versions",
                json={"version": "v1.0", "content": "a"},
            )
            resp = await client.post(
                "/api/prompts/writer/versions",
                json={"version": "v1.0", "content": "b"},
            )
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_set_active(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/prompts/writer/versions",
                json={"version": "v1.0", "content": "a", "is_active": True},
            )
            await client.post(
                "/api/prompts/writer/versions",
                json={"version": "v2.0", "content": "b"},
            )
            resp = await client.patch(
                "/api/prompts/writer/versions/v2.0",
                json={"is_active": True},
            )
            assert resp.status_code == 200
            list_resp = await client.get("/api/prompts/writer/versions")
        v1 = next(v for v in list_resp.json()["versions"] if v["version"] == "v1.0")
        assert v1["is_active"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_inactive(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/prompts/writer/versions",
                json={"version": "v1.0", "content": "a", "is_active": True},
            )
            await client.post(
                "/api/prompts/writer/versions",
                json={"version": "v2.0", "content": "b"},
            )
            resp = await client.delete("/api/prompts/writer/versions/v2.0")
        assert resp.status_code == 204
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_active_rejected(async_session):
    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/prompts/writer/versions",
                json={"version": "v1.0", "content": "a", "is_active": True},
            )
            resp = await client.delete("/api/prompts/writer/versions/v1.0")
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()
