import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_upload_setting_and_approve(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/novels/n1/documents/upload",
            json={"filename": "setting.txt", "content": "世界观：天玄大陆。主角林风。"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["extraction_type"] == "setting"

        pe_id = data["id"]
        resp2 = await client.get("/api/novels/n1/documents/pending")
        assert resp2.status_code == 200
        assert any(item["id"] == pe_id for item in resp2.json()["items"])

        resp3 = await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": pe_id})
        assert resp3.status_code == 200
        assert len(resp3.json()["documents"]) > 0

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_style_profile_versions_and_rollback(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Upload v1
        r1 = await client.post(
            "/api/novels/n1/documents/upload",
            json={"filename": "style.txt", "content": "a" * 10000},
        )
        pe1 = r1.json()["id"]
        await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": pe1})

        # Upload v2
        r2 = await client.post(
            "/api/novels/n1/documents/upload",
            json={"filename": "style.txt", "content": "b" * 10000},
        )
        pe2 = r2.json()["id"]
        await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": pe2})

        versions = await client.get("/api/novels/n1/style_profile/versions")
        assert versions.status_code == 200
        assert len(versions.json()["versions"]) == 2

        rollback = await client.post("/api/novels/n1/style_profile/rollback", json={"version": 1})
        assert rollback.status_code == 200

    app.dependency_overrides.clear()
