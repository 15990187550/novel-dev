import pytest

from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository


@pytest.mark.asyncio
async def test_crud(async_session):
    repo = PendingExtractionRepository(async_session)
    pe = await repo.create(
        pe_id="pe_1",
        novel_id="n1",
        extraction_type="setting",
        raw_result={"worldview": "test"},
        proposed_entities=[{"name": "Lin Feng"}],
    )
    assert pe.status == "pending"

    fetched = await repo.get_by_id("pe_1")
    assert fetched is not None

    items = await repo.list_by_novel("n1")
    assert len(items) == 1

    await repo.update_status("pe_1", "approved")
    updated = await repo.get_by_id("pe_1")
    assert updated.status == "approved"
