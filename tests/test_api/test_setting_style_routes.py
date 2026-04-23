import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from novel_dev.llm.exceptions import LLMTimeoutError

from novel_dev.api.routes import router, get_session
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository

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
            assert matched["source_filename"] == "setting.txt"
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
async def test_batch_upload_setting_returns_per_file_results_and_pending_source_filename(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/novels/n1/documents/upload/batch",
                json={
                    "items": [
                        {"filename": "setting-1.txt", "content": "世界观：天玄大陆。主角林风。"},
                        {"filename": "setting-2.txt", "content": "世界观：沧澜界。主角陆照。"},
                    ]
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 2
            assert data["accepted"] == 2
            assert data["failed"] == 0
            assert all(item["pending_id"] for item in data["items"])
            assert all(item["status"] == "processing" for item in data["items"])

            resp2 = await client.get("/api/novels/n1/documents/pending")
            pending_items = resp2.json()["items"]
            filenames = {item["source_filename"] for item in pending_items}
            assert {"setting-1.txt", "setting-2.txt"} <= filenames
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_batch_upload_continues_when_one_item_times_out(async_session, monkeypatch):
    from novel_dev.services.extraction_service import ExtractionService

    async def override():
        yield async_session

    original = ExtractionService.complete_processing_upload

    async def fake_complete_processing_upload(self, pe_id: str, novel_id: str, filename: str, content: str):
        if filename == "bad.txt":
            raise LLMTimeoutError("Request timed out")
        return await original(self, pe_id, novel_id, filename, content)

    monkeypatch.setattr(ExtractionService, "complete_processing_upload", fake_complete_processing_upload)
    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/novels/n1/documents/upload/batch",
                json={
                    "items": [
                        {"filename": "good.txt", "content": "世界观：天玄大陆。主角林风。"},
                        {"filename": "bad.txt", "content": "boom"},
                    ]
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 2
            assert data["accepted"] == 2
            assert data["failed"] == 0
            failed = next(item for item in data["items"] if item["filename"] == "bad.txt")
            succeeded = next(item for item in data["items"] if item["filename"] == "good.txt")
            assert failed["pending_id"] is not None
            assert failed["status"] == "processing"
            assert succeeded["pending_id"] is not None
            assert succeeded["status"] == "processing"

            await asyncio.sleep(0.05)
            resp2 = await client.get("/api/novels/n1/documents/pending")
            items_by_name = {item["source_filename"]: item for item in resp2.json()["items"]}
            assert items_by_name["good.txt"]["status"] == "pending"
            assert items_by_name["bad.txt"]["status"] == "failed"
            assert "超时" in items_by_name["bad.txt"]["error_message"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_batch_upload_creates_processing_records_before_background_completion(async_session, monkeypatch):
    from novel_dev.services.extraction_service import ExtractionService

    async def override():
        yield async_session

    blocker = asyncio.Event()

    original = ExtractionService.complete_processing_upload

    async def slow_complete(self, pe_id: str, novel_id: str, filename: str, content: str):
        await blocker.wait()
        return await original(self, pe_id, novel_id, filename, content)

    monkeypatch.setattr(ExtractionService, "complete_processing_upload", slow_complete)
    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/novels/n1/documents/upload/batch",
                json={
                    "items": [
                        {"filename": "setting-1.txt", "content": "世界观：天玄大陆。主角林风。"},
                    ]
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["accepted"] == 1
            assert data["items"][0]["status"] == "processing"

            pending_resp = await client.get("/api/novels/n1/documents/pending")
            assert pending_resp.status_code == 200
            pending_items = pending_resp.json()["items"]
            assert len(pending_items) == 1
            assert pending_items[0]["source_filename"] == "setting-1.txt"
            assert pending_items[0]["status"] == "processing"

            blocker.set()
            await asyncio.sleep(0.05)
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
async def test_documents_library_returns_active_setting_and_style_docs(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            setting_resp = await client.post(
                "/api/novels/n1/documents/upload",
                json={"filename": "setting.txt", "content": "世界观：天玄大陆。修炼体系：炼气、筑基。剧情梗概：主角入宗修行。"},
            )
            setting_pending_id = setting_resp.json()["id"]
            await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": setting_pending_id})

            style_resp = await client.post(
                "/api/novels/n1/documents/upload",
                json={"filename": "style.txt", "content": "a" * 10000},
            )
            style_pending_id = style_resp.json()["id"]
            await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": style_pending_id})

            library_resp = await client.get("/api/novels/n1/documents/library")
            assert library_resp.status_code == 200
            payload = library_resp.json()
            assert payload["items"]
            assert payload["active_style_profile_version"] == 1

            doc_types = {item["doc_type"] for item in payload["items"]}
            assert {"worldview", "setting", "synopsis", "style_profile"} <= doc_types

            style_doc = next(item for item in payload["items"] if item["doc_type"] == "style_profile")
            assert style_doc["is_active"] is True
            assert isinstance(style_doc["style_config"], dict)
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
async def test_delete_failed_pending_record(async_session):
    async def override():
        yield async_session
    repo = PendingExtractionRepository(async_session)
    await repo.create(
        pe_id="pe_failed1",
        novel_id="n1",
        source_filename="broken.md",
        extraction_type="setting",
        raw_result={},
        status="failed",
        error_message="bad json",
    )
    await async_session.commit()
    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            pending_before = await client.get("/api/novels/n1/documents/pending")
            before_items = pending_before.json()["items"]
            failed_item = next(item for item in before_items if item["id"] == "pe_failed1")
            assert failed_item["status"] == "failed"

            delete_resp = await client.delete("/api/novels/n1/documents/pending/pe_failed1")
            assert delete_resp.status_code == 204

            pending_after = await client.get("/api/novels/n1/documents/pending")
            after_items = pending_after.json()["items"]
            assert all(item["id"] != "pe_failed1" for item in after_items)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_failed_pending_rejects_non_failed(async_session):
    async def override():
        yield async_session
    repo = PendingExtractionRepository(async_session)
    await repo.create(
        pe_id="pe_pending1",
        novel_id="n1",
        source_filename="setting.txt",
        extraction_type="setting",
        raw_result={},
        status="pending",
    )
    await async_session.commit()
    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            delete_resp = await client.delete("/api/novels/n1/documents/pending/pe_pending1")
            assert delete_resp.status_code == 409
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
