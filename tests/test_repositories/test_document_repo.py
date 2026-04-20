import pytest

from novel_dev.repositories.document_repo import DocumentRepository


@pytest.mark.asyncio
async def test_document_crud(async_session):
    repo = DocumentRepository(async_session)
    doc = await repo.create(
        doc_id="doc_001",
        novel_id="novel_1",
        doc_type="worldview",
        title="World Setting",
        content="In a land of cultivation...",
    )
    assert doc.doc_type == "worldview"
    fetched = await repo.get_by_type("novel_1", "worldview")
    assert fetched[0].title == "World Setting"


@pytest.mark.asyncio
async def test_get_latest_by_type(async_session):
    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "style_profile", "v1", "content1", version=1)
    await repo.create("d2", "n1", "style_profile", "v2", "content2", version=2)
    latest = await repo.get_latest_by_type("n1", "style_profile")
    assert latest is not None
    assert latest.version == 2


@pytest.mark.asyncio
async def test_get_by_type_and_version(async_session):
    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "style_profile", "v1", "content1", version=1)
    doc = await repo.get_by_type_and_version("n1", "style_profile", 1)
    assert doc is not None
    assert doc.id == "d1"


@pytest.mark.asyncio
async def test_list_by_novel_filters_and_orders(async_session):
    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "worldview", "世界观", "a", version=1)
    await repo.create("d2", "n1", "concept", "人物设定", "b", version=1)
    await repo.create("d3", "n2", "worldview", "其他小说", "c", version=1)

    docs = await repo.list_by_novel("n1")

    assert [doc.id for doc in docs] == ["d2", "d1"] or [doc.id for doc in docs] == ["d1", "d2"]
    assert all(doc.novel_id == "n1" for doc in docs)


@pytest.mark.asyncio
async def test_list_by_novel_supports_doc_type(async_session):
    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "worldview", "世界观", "a", version=1)
    await repo.create("d2", "n1", "concept", "人物设定", "b", version=1)

    docs = await repo.list_by_novel("n1", doc_type="concept")

    assert [doc.id for doc in docs] == ["d2"]


@pytest.mark.asyncio
async def test_get_by_id_for_novel_rejects_other_novel(async_session):
    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "worldview", "世界观", "a", version=1)

    assert await repo.get_by_id_for_novel("n2", "d1") is None
