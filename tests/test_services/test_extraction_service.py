import pytest

from novel_dev.services.extraction_service import ExtractionService
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository


@pytest.mark.asyncio
async def test_process_setting_upload(async_session):
    svc = ExtractionService(async_session)
    pe = await svc.process_upload(
        novel_id="n1",
        filename="setting.txt",
        content="世界观：天玄大陆。主角林风，外门弟子。",
    )
    assert pe.extraction_type == "setting"
    assert pe.status == "pending"

    # Approve
    docs = await svc.approve_pending(pe.id)
    assert len(docs) > 0
    doc_types = {d.doc_type for d in docs}
    assert "worldview" in doc_types


@pytest.mark.asyncio
async def test_process_style_upload(async_session):
    svc = ExtractionService(async_session)
    pe = await svc.process_upload(
        novel_id="n1",
        filename="style.txt",
        content="剑光一闪，敌人倒下。" * 100,
    )
    assert pe.extraction_type == "style_profile"

    docs = await svc.approve_pending(pe.id)
    assert len(docs) == 1
    assert docs[0].doc_type == "style_profile"


@pytest.mark.asyncio
async def test_style_rollback(async_session):
    svc = ExtractionService(async_session)
    # Create v1
    pe1 = await svc.process_upload("n1", "style.txt", "a" * 10000)
    await svc.approve_pending(pe1.id)
    # Create v2
    pe2 = await svc.process_upload("n1", "style.txt", "b" * 10000)
    await svc.approve_pending(pe2.id)

    # Rollback to v1
    await svc.rollback_style_profile("n1", 1)
    active = await svc.get_active_style_profile("n1")
    assert active is not None
    assert active.version == 1
    assert "a" * 10000 in active.content or "Overall:" in active.content


@pytest.mark.asyncio
async def test_approve_nonexistent_pending(async_session):
    svc = ExtractionService(async_session)
    docs = await svc.approve_pending("pe_does_not_exist")
    assert docs == []
