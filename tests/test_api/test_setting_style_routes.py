import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.llm.exceptions import LLMTimeoutError

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_upload_setting_and_approve(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
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
            pending_items = resp2.json()["items"]
            matched = next(item for item in pending_items if item["id"] == pe_id)
            assert matched["diff_result"] is not None
            assert any(item["id"] == pe_id for item in pending_items)

            resp3 = await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": pe_id})
            assert resp3.status_code == 200
            assert len(resp3.json()["documents"]) > 0

            resp4 = await client.get("/api/novels/n1/documents/pending")
            matched_after = next(item for item in resp4.json()["items"] if item["id"] == pe_id)
            assert matched_after["resolution_result"] is not None
            assert matched_after["resolution_result"]["field_resolutions"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_upload_returns_504_when_setting_extraction_times_out(async_session, monkeypatch):
    async def override():
        yield async_session

    async def mock_extract(self, text: str, novel_id: str = ""):
        raise LLMTimeoutError("Request timed out")

    monkeypatch.setattr("novel_dev.agents.setting_extractor.SettingExtractorAgent.extract", mock_extract)
    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/novels/n1/documents/upload",
                json={"filename": "setting.txt", "content": "世界观：天玄大陆。主角林风。"},
            )
            assert resp.status_code == 504
            assert "超时" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_style_profile_versions_and_rollback(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.post(
                "/api/novels/n1/documents/upload",
                json={"filename": "style.txt", "content": "a" * 10000},
            )
            pe1 = r1.json()["id"]
            await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": pe1})

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
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approve_wrong_novel(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.post(
                "/api/novels/n1/documents/upload",
                json={"filename": "setting.txt", "content": "世界观：天玄大陆。"},
            )
            pe1 = r1.json()["id"]

            resp = await client.post("/api/novels/n2/documents/pending/approve", json={"pending_id": pe1})
            assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approve_with_field_resolutions(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/novels/n1/documents/upload",
                json={"filename": "setting.txt", "content": "世界观：天玄大陆。主角林风。"},
            )
            pe_id = resp.json()["id"]
            resp2 = await client.post(
                "/api/novels/n1/documents/pending/approve",
                json={
                    "pending_id": pe_id,
                    "field_resolutions": [
                        {"entity_type": "character", "entity_name": "林风", "field": "identity", "action": "use_new"}
                    ],
                },
            )
            assert resp2.status_code == 200
            assert len(resp2.json()["documents"]) > 0

            resp3 = await client.get("/api/novels/n1/documents/pending")
            matched = next(item for item in resp3.json()["items"] if item["id"] == pe_id)
            assert matched["resolution_result"] is not None
            assert matched["resolution_result"]["field_resolutions"]
    finally:
        app.dependency_overrides.clear()
