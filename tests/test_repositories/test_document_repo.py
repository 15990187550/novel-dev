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
