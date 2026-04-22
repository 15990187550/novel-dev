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


@pytest.mark.asyncio
async def test_processing_record_can_be_completed_and_failed(async_session):
    repo = PendingExtractionRepository(async_session)
    pe = await repo.create(
        pe_id="pe_processing",
        novel_id="n1",
        extraction_type="processing",
        raw_result={},
        source_filename="setting.txt",
        status="processing",
    )
    assert pe.status == "processing"

    await repo.update_payload(
        "pe_processing",
        extraction_type="setting",
        raw_result={"worldview": "test"},
        proposed_entities=[{"name": "Lin Feng"}],
        diff_result={"summary": "1 个新增实体"},
        status="pending",
    )
    pending = await repo.get_by_id("pe_processing")
    assert pending is not None
    assert pending.extraction_type == "setting"
    assert pending.status == "pending"

    await repo.update_status("pe_processing", "failed", error_message="boom")
    failed = await repo.get_by_id("pe_processing")
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_message == "boom"
