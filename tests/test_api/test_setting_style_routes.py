import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from novel_dev.llm.exceptions import LLMTimeoutError

from novel_dev.api.routes import router, get_session
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.services.extraction_service import ExtractionService

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


@pytest.mark.asyncio
async def test_update_pending_draft_field_only_changes_pending_payload(async_session):
    async def override():
        yield async_session

    repo = PendingExtractionRepository(async_session)
    await repo.create(
        pe_id="pe_edit1",
        novel_id="n1",
        source_filename="setting.txt",
        extraction_type="setting",
        status="pending",
        raw_result={
            "worldview": "",
            "power_system": "",
            "factions": [],
            "locations": [],
            "character_profiles": [
                {
                    "name": "孟奇",
                    "identity": "道经传承者",
                    "background": "已超脱",
                }
            ],
            "important_items": [],
            "plot_synopsis": "",
        },
        proposed_entities=[
            {
                "type": "character",
                "name": "孟奇",
                "data": {
                    "name": "孟奇",
                    "identity": "道经传承者",
                    "background": "已超脱",
                },
            }
        ],
        diff_result={
            "summary": "1 个新增实体",
            "document_changes": [],
            "entity_diffs": [
                {
                    "entity_type": "character",
                    "entity_name": "孟奇",
                    "operation": "create",
                    "field_changes": [
                        {"field": "identity", "label": "身份", "old_value": "", "new_value": "道经传承者"},
                        {"field": "background", "label": "背景", "old_value": "", "new_value": "已超脱"},
                    ],
                }
            ],
        },
    )
    await async_session.commit()

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            update_resp = await client.patch(
                "/api/novels/n1/documents/pending/pe_edit1/draft-field",
                json={
                    "entity_type": "character",
                    "entity_name": "孟奇",
                    "field": "identity",
                    "value": "将道经传给陆照",
                },
            )
            assert update_resp.status_code == 200
            item = update_resp.json()["item"]
            assert item["status"] == "pending"
            assert item["raw_result"]["character_profiles"][0]["identity"] == "将道经传给陆照"
            assert item["proposed_entities"][0]["data"]["identity"] == "将道经传给陆照"

            pending_resp = await client.get("/api/novels/n1/documents/pending")
            refreshed = next(doc for doc in pending_resp.json()["items"] if doc["id"] == "pe_edit1")
            assert refreshed["raw_result"]["character_profiles"][0]["identity"] == "将道经传给陆照"
            identity_change = next(
                change
                for change in refreshed["diff_result"]["entity_diffs"][0]["field_changes"]
                if change["field"] == "identity"
            )
            assert identity_change["new_value"] == "将道经传给陆照"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approve_pending_uses_edited_draft_field_values(async_session):
    async def override():
        yield async_session

    repo = PendingExtractionRepository(async_session)
    await repo.create(
        pe_id="pe_edit2",
        novel_id="n1",
        source_filename="setting.txt",
        extraction_type="setting",
        status="pending",
        raw_result={
            "worldview": "",
            "power_system": "",
            "factions": [],
            "locations": [],
            "character_profiles": [
                {
                    "name": "孟奇",
                    "identity": "道经传承者",
                    "background": "已超脱",
                    "resources": "道经",
                }
            ],
            "important_items": [],
            "plot_synopsis": "",
        },
        proposed_entities=[
            {
                "type": "character",
                "name": "孟奇",
                "data": {
                    "name": "孟奇",
                    "identity": "道经传承者",
                    "background": "已超脱",
                    "resources": "道经",
                },
            }
        ],
        diff_result={
            "summary": "1 个新增实体",
            "document_changes": [],
            "entity_diffs": [
                {
                    "entity_type": "character",
                    "entity_name": "孟奇",
                    "operation": "create",
                    "field_changes": [
                        {"field": "identity", "label": "身份", "old_value": "", "new_value": "道经传承者"},
                        {"field": "background", "label": "背景", "old_value": "", "new_value": "已超脱"},
                        {"field": "resources", "label": "资源", "old_value": "", "new_value": "道经"},
                    ],
                }
            ],
        },
    )
    await async_session.commit()

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            update_resp = await client.patch(
                "/api/novels/n1/documents/pending/pe_edit2/draft-field",
                json={
                    "entity_type": "character",
                    "entity_name": "孟奇",
                    "field": "background",
                    "value": "最后与陆照一起超脱",
                },
            )
            assert update_resp.status_code == 200

            approve_resp = await client.post(
                "/api/novels/n1/documents/pending/approve",
                json={"pending_id": "pe_edit2"},
            )
            assert approve_resp.status_code == 200

            entities_resp = await client.get("/api/novels/n1/entities")
            assert entities_resp.status_code == 200
            target = next(
                item for item in entities_resp.json()["items"]
                if item["type"] == "character" and item["name"] == "孟奇"
            )
            assert target["latest_state"]["background"] == "最后与陆照一起超脱"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approve_pending_merges_same_type_and_title_into_new_version(async_session, monkeypatch):
    async def override():
        yield async_session

    pending_repo = PendingExtractionRepository(async_session)
    await pending_repo.create(
        pe_id="pe_merge_old",
        novel_id="n1",
        source_filename="setting-old.txt",
        extraction_type="setting",
        status="pending",
        raw_result={
            "worldview": "旧世界观：诸天万界并立。",
            "power_system": "",
            "factions": [],
            "locations": [],
            "character_profiles": [],
            "important_items": [],
            "plot_synopsis": "",
        },
        proposed_entities=[],
        diff_result={"summary": "无实体变更", "document_changes": [], "entity_diffs": []},
    )
    await pending_repo.create(
        pe_id="pe_merge_new",
        novel_id="n1",
        source_filename="setting-new.txt",
        extraction_type="setting",
        status="pending",
        raw_result={
            "worldview": "新世界观：以真实界为核心，辐射诸天万界。",
            "power_system": "",
            "factions": [],
            "locations": [],
            "character_profiles": [],
            "important_items": [],
            "plot_synopsis": "",
        },
        proposed_entities=[],
        diff_result={"summary": "无实体变更", "document_changes": [], "entity_diffs": []},
    )
    await async_session.commit()

    merge_calls = []

    async def fake_merge(self, **kwargs):
        merge_calls.append(kwargs)
        return "合并世界观：诸天万界以真实界为核心。"

    monkeypatch.setattr(ExtractionService, "_request_setting_document_merge", fake_merge)

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": "pe_merge_old"})
            assert first.status_code == 200

            second = await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": "pe_merge_new"})
            assert second.status_code == 200
            worldview_doc = next(doc for doc in second.json()["documents"] if doc["doc_type"] == "worldview")
            assert worldview_doc["version"] == 2
            assert worldview_doc["content"] == "合并世界观：诸天万界以真实界为核心。"

            repo = DocumentRepository(async_session)
            worldview_versions = await repo.get_by_type_and_title("n1", "worldview", "世界观")
            assert len(worldview_versions) == 2
            assert worldview_versions[0].version == 2
            assert worldview_versions[0].content == "合并世界观：诸天万界以真实界为核心。"

            library = await client.get("/api/novels/n1/documents/library")
            assert library.status_code == 200
            worldview_items = [item for item in library.json()["items"] if item["doc_type"] == "worldview"]
            assert len(worldview_items) == 1
            assert worldview_items[0]["content"] == "合并世界观：诸天万界以真实界为核心。"

            assert len(merge_calls) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approve_pending_retries_merge_once_then_falls_back_to_latest(async_session, monkeypatch):
    async def override():
        yield async_session

    pending_repo = PendingExtractionRepository(async_session)
    await pending_repo.create(
        pe_id="pe_merge_retry_old",
        novel_id="n1",
        source_filename="setting-old.txt",
        extraction_type="setting",
        status="pending",
        raw_result={
            "worldview": "旧世界观",
            "power_system": "",
            "factions": [],
            "locations": [],
            "character_profiles": [],
            "important_items": [],
            "plot_synopsis": "",
        },
        proposed_entities=[],
        diff_result={"summary": "无实体变更", "document_changes": [], "entity_diffs": []},
    )
    await pending_repo.create(
        pe_id="pe_merge_retry_new",
        novel_id="n1",
        source_filename="setting-new.txt",
        extraction_type="setting",
        status="pending",
        raw_result={
            "worldview": "最终采用的新世界观",
            "power_system": "",
            "factions": [],
            "locations": [],
            "character_profiles": [],
            "important_items": [],
            "plot_synopsis": "",
        },
        proposed_entities=[],
        diff_result={"summary": "无实体变更", "document_changes": [], "entity_diffs": []},
    )
    await async_session.commit()

    attempts = {"count": 0}

    async def always_fail_merge(self, **kwargs):
        attempts["count"] += 1
        raise RuntimeError("mock merge failed")

    monkeypatch.setattr(ExtractionService, "_request_setting_document_merge", always_fail_merge)

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": "pe_merge_retry_old"})
            assert first.status_code == 200

            second = await client.post("/api/novels/n1/documents/pending/approve", json={"pending_id": "pe_merge_retry_new"})
            assert second.status_code == 200
            worldview_doc = next(doc for doc in second.json()["documents"] if doc["doc_type"] == "worldview")
            assert worldview_doc["version"] == 2
            assert worldview_doc["content"] == "最终采用的新世界观"

            repo = DocumentRepository(async_session)
            latest = await repo.get_latest_by_type_and_title("n1", "worldview", "世界观")
            assert latest is not None
            assert latest.content == "最终采用的新世界观"
            assert attempts["count"] == 2
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_existing_duplicate_library_documents(async_session, monkeypatch):
    async def override():
        yield async_session

    repo = DocumentRepository(async_session)
    await repo.create("d_old_1", "n1", "worldview", "世界观", "旧版本一：诸天万界。", version=1)
    await repo.create("d_old_2", "n1", "worldview", "世界观", "旧版本二：以真实界为核心。", version=1)
    await repo.create("d_setting_1", "n1", "setting", "修炼体系", "炼气、筑基。", version=1)
    await repo.create("d_setting_2", "n1", "setting", "修炼体系", "法身、彼岸。", version=1)
    await async_session.commit()

    merge_calls = []

    async def fake_merge(self, **kwargs):
        merge_calls.append((kwargs["doc_type"], kwargs["title"]))
        if kwargs["doc_type"] == "worldview":
            return "合并世界观：以真实界为核心的诸天万界。"
        return "合并体系：炼气、筑基、法身、彼岸。"

    monkeypatch.setattr(ExtractionService, "_request_setting_document_merge", fake_merge)

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels/n1/documents/library/merge-duplicates")
            assert resp.status_code == 200
            payload = resp.json()
            assert len(payload["merged"]) == 2

            worldview_doc = next(item for item in payload["merged"] if item["doc_type"] == "worldview")
            setting_doc = next(item for item in payload["merged"] if item["doc_type"] == "setting")
            assert worldview_doc["version"] == 2
            assert worldview_doc["content"] == "合并世界观：以真实界为核心的诸天万界。"
            assert setting_doc["version"] == 2
            assert setting_doc["content"] == "合并体系：炼气、筑基、法身、彼岸。"

            library_resp = await client.get("/api/novels/n1/documents/library")
            assert library_resp.status_code == 200
            worldview_items = [
                item for item in library_resp.json()["items"]
                if item["doc_type"] == "worldview" and item["title"] == "世界观"
            ]
            setting_items = [
                item for item in library_resp.json()["items"]
                if item["doc_type"] == "setting" and item["title"] == "修炼体系"
            ]
            assert len(worldview_items) == 1
            assert worldview_items[0]["content"] == "合并世界观：以真实界为核心的诸天万界。"
            assert len(setting_items) == 1
            assert setting_items[0]["content"] == "合并体系：炼气、筑基、法身、彼岸。"

            assert sorted(merge_calls) == [("setting", "修炼体系"), ("worldview", "世界观")]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_library_document_creates_new_setting_version(async_session):
    async def override():
        yield async_session

    repo = DocumentRepository(async_session)
    await repo.create("doc_library_1", "n1", "worldview", "世界观", "旧世界观", version=1)
    await async_session.commit()

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                "/api/novels/n1/documents/library/doc_library_1",
                json={"content": "新世界观"},
            )
            assert resp.status_code == 200
            item = resp.json()["item"]
            assert item["doc_type"] == "worldview"
            assert item["title"] == "世界观"
            assert item["version"] == 2
            assert item["content"] == "新世界观"

            docs = await repo.get_by_type_and_title("n1", "worldview", "世界观")
            assert len(docs) == 2
            assert docs[0].version == 2
            assert docs[0].content == "新世界观"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_library_document_creates_new_style_version_and_activates_it(async_session):
    async def override():
        yield async_session

    repo = DocumentRepository(async_session)
    await repo.create(
        "doc_style_1",
        "n1",
        "style_profile",
        '{"tone":"热血"}',
        "旧文风",
        version=1,
    )
    await async_session.commit()

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                "/api/novels/n1/documents/library/doc_style_1",
                json={"content": "新文风"},
            )
            assert resp.status_code == 200
            item = resp.json()["item"]
            assert item["doc_type"] == "style_profile"
            assert item["version"] == 2
            assert item["content"] == "新文风"
            assert item["is_active"] is True

            library_resp = await client.get("/api/novels/n1/documents/library")
            assert library_resp.status_code == 200
            active = next(doc for doc in library_resp.json()["items"] if doc["doc_type"] == "style_profile" and doc["is_active"])
            assert active["version"] == 2
            assert active["content"] == "新文风"
    finally:
        app.dependency_overrides.clear()
