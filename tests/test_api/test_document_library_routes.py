import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.repositories.document_repo import DocumentRepository


app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_list_approved_documents(async_session):
    async def override():
        yield async_session

    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "worldview", "世界观", "内容一", version=1)
    await repo.create("d2", "n1", "concept", "人物设定", "内容二", version=1)
    await repo.create("d3", "n2", "worldview", "其他小说", "内容三", version=1)

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/documents")
            assert resp.status_code == 200
            data = resp.json()["items"]
            assert {item["id"] for item in data} == {"d1", "d2"}
            assert all("content_preview" in item for item in data)
            assert all("word_count" in item for item in data)
            assert all("has_embedding" in item for item in data)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_approved_documents_with_doc_type_filter(async_session):
    async def override():
        yield async_session

    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "worldview", "世界观", "内容一", version=1)
    await repo.create("d2", "n1", "concept", "人物设定", "内容二", version=1)

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/documents", params={"doc_type": "concept"})
            assert resp.status_code == 200
            data = resp.json()["items"]
            assert [item["id"] for item in data] == ["d2"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_document_detail_and_versions(async_session):
    async def override():
        yield async_session

    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "worldview", "世界观", "内容一", version=1)
    await repo.create("d2", "n1", "worldview", "世界观", "内容二", version=2)

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            detail = await client.get("/api/novels/n1/documents/d2")
            assert detail.status_code == 200
            assert detail.json()["content"] == "内容二"
            assert detail.json()["version"] == 2

            versions = await client.get("/api/novels/n1/documents/types/worldview/versions")
            assert versions.status_code == 200
            assert [item["version"] for item in versions.json()["items"]] == [2, 1]

            versions_by_document = await client.get("/api/novels/n1/documents/d2/versions")
            assert versions_by_document.status_code == 200
            assert [item["version"] for item in versions_by_document.json()["items"]] == [2, 1]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_save_new_version_and_reindex(async_session):
    async def override():
        yield async_session

    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "worldview", "世界观", "内容一", version=1)

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            saved = await client.post(
                "/api/novels/n1/documents/d1/versions",
                json={"title": "世界观", "content": "内容二"},
            )
            assert saved.status_code == 200
            assert saved.json()["version"] == 2
            assert saved.json()["title"] == "世界观"

            reindex = await client.post("/api/novels/n1/documents/d1/reindex")
            assert reindex.status_code == 200
            assert reindex.json()["reindexed"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cross_novel_document_returns_404(async_session):
    async def override():
        yield async_session

    repo = DocumentRepository(async_session)
    await repo.create("d1", "n2", "worldview", "世界观", "内容一", version=1)

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            detail = await client.get("/api/novels/n1/documents/d1")
            assert detail.status_code == 404

            versions = await client.get("/api/novels/n1/documents/d1/versions")
            assert versions.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_document_not_found(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/novels/n1/documents/nonexistent")
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
