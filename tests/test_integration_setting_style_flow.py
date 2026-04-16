import pytest

from novel_dev.services.extraction_service import ExtractionService
from novel_dev.repositories.document_repo import DocumentRepository


@pytest.mark.asyncio
async def test_setting_upload_to_documents(async_session):
    svc = ExtractionService(async_session)
    pe = await svc.process_upload(
        novel_id="novel_integration",
        filename="world_setting.txt",
        content="""
世界观：天玄大陆，万族林立。
修炼体系：炼气、筑基、金丹。
势力：青云宗是正道魁首，魔道横行。
主角林风，青云宗外门弟子，性格坚韧隐忍，目标为父报仇。
重要物品：残缺玉佩，上古魔宗信物，揭示主角身世。
剧情梗概：林风因家族被灭门，拜入青云宗修炼报仇。
""",
    )
    assert pe.extraction_type == "setting"

    docs = await svc.approve_pending(pe.id)
    # worldview, setting (power_system), setting (factions), synopsis, concept (chars), concept (items)
    assert len(docs) == 6

    doc_types = {d.doc_type for d in docs}
    assert {"worldview", "setting", "synopsis", "concept"} <= doc_types

    doc_repo = DocumentRepository(async_session)
    worldview_docs = await doc_repo.get_by_type("novel_integration", "worldview")
    assert len(worldview_docs) == 1
    assert "天玄大陆" in worldview_docs[0].content

    style_docs = await doc_repo.get_by_type("novel_integration", "style_profile")
    assert len(style_docs) == 0


@pytest.mark.asyncio
async def test_style_upload_versioning_and_rollback(async_session):
    svc = ExtractionService(async_session)
    doc_repo = DocumentRepository(async_session)

    # 12000 chars = 4 chunks, enough to exercise sampling and produce a style guide
    v1_text = "a" * 12000
    v2_text = "b" * 12000

    # v1
    pe1 = await svc.process_upload("novel_style", "style_sample.txt", v1_text)
    await svc.approve_pending(pe1.id)

    # v2
    pe2 = await svc.process_upload("novel_style", "style_sample.txt", v2_text)
    await svc.approve_pending(pe2.id)

    versions = await doc_repo.get_by_type("novel_style", "style_profile")
    assert len(versions) == 2

    # Rollback to v1
    await svc.rollback_style_profile("novel_style", 1)
    active = await svc.get_active_style_profile("novel_style")
    assert active is not None
    assert active.version == 1
    # active.content is the generated style_guide, not raw input
    assert "Overall:" in active.content


@pytest.mark.asyncio
async def test_rollback_nonexistent_version(async_session):
    svc = ExtractionService(async_session)
    pe = await svc.process_upload("novel_empty", "style.txt", "c" * 12000)
    await svc.approve_pending(pe.id)

    # Rollback to version 99 which does not exist
    await svc.rollback_style_profile("novel_empty", 99)
    active = await svc.get_active_style_profile("novel_empty")
    # get_active_style_profile reads checkpoint_data version 99 and returns None when no doc matches
    assert active is None
