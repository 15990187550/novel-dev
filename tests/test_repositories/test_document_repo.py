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
async def test_get_by_type_returns_all_versions_but_current_returns_latest_per_title(async_session):
    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "setting", "势力格局", "旧内容 魔佛一脉", version=1)
    await repo.create("d2", "n1", "setting", "势力格局", "新内容", version=2)
    await repo.create("d3", "n1", "setting", "修炼体系", "体系内容", version=1)

    all_docs = await repo.get_by_type("n1", "setting")
    current_docs = await repo.get_current_by_type("n1", "setting")

    assert {doc.id for doc in all_docs} == {"d1", "d2", "d3"}
    assert {doc.id for doc in current_docs} == {"d2", "d3"}
    assert all("魔佛" not in (doc.content or "") for doc in current_docs)


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
async def test_get_latest_by_type_and_title(async_session):
    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "setting", "修炼体系", "content1", version=1)
    await repo.create("d2", "n1", "setting", "修炼体系", "content2", version=2)
    await repo.create("d3", "n1", "setting", "地点设定", "content3", version=3)

    latest = await repo.get_latest_by_type_and_title("n1", "setting", "修炼体系")

    assert latest is not None
    assert latest.id == "d2"


@pytest.mark.asyncio
async def test_list_by_novel_returns_all_documents_in_updated_order(async_session):
    repo = DocumentRepository(async_session)
    first = await repo.create("d1", "n1", "worldview", "World", "world")
    second = await repo.create("d2", "n1", "concept", "People", "people")
    await repo.create("d3", "n2", "worldview", "Other", "other")

    docs = await repo.list_by_novel("n1")

    assert [doc.id for doc in docs] == [second.id, first.id]


@pytest.mark.asyncio
async def test_get_by_id_scopes_document_to_novel(async_session):
    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "worldview", "World", "world")
    await repo.create("d2", "n2", "worldview", "Other", "other")

    doc = await repo.get_by_id_for_novel("n1", "d1")
    missing = await repo.get_by_id_for_novel("n1", "d2")

    assert doc is not None
    assert doc.id == "d1"
    assert missing is None


@pytest.mark.asyncio
async def test_list_versions_returns_matching_type_versions_descending(async_session):
    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "style_profile", "v1", "content1", version=1)
    await repo.create("d2", "n1", "style_profile", "v2", "content2", version=2)
    await repo.create("d3", "n1", "worldview", "world", "content3", version=5)

    versions = await repo.list_versions("n1", "style_profile")

    assert [doc.id for doc in versions] == ["d2", "d1"]


@pytest.mark.asyncio
async def test_save_new_version_increments_version_from_latest(async_session):
    repo = DocumentRepository(async_session)
    await repo.create("d1", "n1", "style_profile", "v1", "content1", version=1)

    saved = await repo.save_new_version(
        doc_id="d2",
        novel_id="n1",
        doc_type="style_profile",
        title="v2",
        content="content2",
    )

    assert saved.version == 2


@pytest.mark.asyncio
async def test_save_new_version_starts_at_one_when_type_has_no_documents(async_session):
    repo = DocumentRepository(async_session)

    saved = await repo.save_new_version(
        doc_id="d1",
        novel_id="n1",
        doc_type="style_profile",
        title="v1",
        content="content1",
    )

    assert saved.version == 1
