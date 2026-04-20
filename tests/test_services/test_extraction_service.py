from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.services.extraction_service import ExtractionService
from novel_dev.agents.file_classifier import FileClassificationResult
from novel_dev.agents.setting_extractor import ExtractedSetting, CharacterProfile
from novel_dev.agents.style_profiler import StyleProfile, StyleConfig


@pytest.fixture
def mock_llm():
    with patch("novel_dev.llm.llm_factory.get") as mock_get:
        mock_client = AsyncMock()

        async def acomplete(messages, **kwargs):
            prompt = messages[0].content if messages else ""
            if "文件分类专家" in prompt:
                # The prompt always contains 'style_sample' in schema instructions,
                # so discriminate by the actual filename line in the prompt.
                if "文件名：style.txt" in prompt or "文件名：style" in prompt:
                    return type("Resp", (), {"text": FileClassificationResult(file_type="style_sample", confidence=0.95, reason="mock").model_dump_json()})()
                return type("Resp", (), {"text": FileClassificationResult(file_type="setting", confidence=0.95, reason="mock").model_dump_json()})()
            if "设定提取专家" in prompt:
                return type("Resp", (), {"text": ExtractedSetting(
                    worldview="天玄大陆",
                    power_system="修炼体系",
                    factions="宗门分布",
                    character_profiles=[CharacterProfile(name="林风", identity="外门弟子")],
                    important_items=[],
                    plot_synopsis="剧情梗概",
                ).model_dump_json()})()
            if "文学风格分析师" in prompt:
                # Return the input text as style_guide so rollback assertions work.
                text_start = prompt.find("文本样本：\n\n")
                style_guide = prompt[text_start + len("文本样本：\n\n"):] if text_start != -1 else "简洁有力"
                return type("Resp", (), {"text": StyleProfile(style_guide=style_guide, style_config=StyleConfig()).model_dump_json()})()
            raise ValueError(f"Unexpected prompt: {prompt[:50]}")

        mock_client.acomplete.side_effect = acomplete
        mock_get.return_value = mock_client
        yield mock_get


@pytest.mark.asyncio
async def test_process_setting_upload(async_session, mock_llm):
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
async def test_process_style_upload(async_session, mock_llm):
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
async def test_style_rollback(async_session, mock_llm):
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


@pytest.mark.asyncio
async def test_list_approved_documents_returns_novel_scoped_documents(async_session):
    svc = ExtractionService(async_session)
    await svc.doc_repo.create("d1", "n1", "worldview", "World", "world")
    await svc.doc_repo.create("d2", "n1", "concept", "People", "people")
    await svc.doc_repo.create("d3", "n2", "worldview", "Other", "other")

    docs = await svc.list_approved_documents("n1")

    assert [doc.id for doc in docs] == ["d2", "d1"]


@pytest.mark.asyncio
async def test_get_approved_document_returns_none_for_other_novel(async_session):
    svc = ExtractionService(async_session)
    await svc.doc_repo.create("d1", "n1", "worldview", "World", "world")
    await svc.doc_repo.create("d2", "n2", "worldview", "Other", "other")

    doc = await svc.get_approved_document("n1", "d1")
    missing = await svc.get_approved_document("n1", "d2")

    assert doc is not None
    assert doc.id == "d1"
    assert missing is None


@pytest.mark.asyncio
async def test_list_document_versions_returns_versions_for_doc_type(async_session):
    svc = ExtractionService(async_session)
    await svc.doc_repo.create("d1", "n1", "style_profile", "v1", "content1", version=1)
    await svc.doc_repo.create("d2", "n1", "style_profile", "v2", "content2", version=2)

    versions = await svc.list_document_versions("n1", "style_profile")

    assert [doc.id for doc in versions] == ["d2", "d1"]


@pytest.mark.asyncio
async def test_save_document_version_indexes_embedding_when_service_available(async_session):
    embedding_service = AsyncMock()
    svc = ExtractionService(async_session, embedding_service=embedding_service)
    original = await svc.doc_repo.create("d1", "n1", "worldview", "v1", "content1", version=1)

    saved = await svc.save_document_version("n1", original.id, title="v2", content="content2")

    assert saved.version == 2
    embedding_service.index_document.assert_awaited_once_with(saved.id)


@pytest.mark.asyncio
async def test_reindex_document_indexes_existing_document(async_session):
    embedding_service = AsyncMock()
    svc = ExtractionService(async_session, embedding_service=embedding_service)
    doc = await svc.doc_repo.create("d1", "n1", "worldview", "v1", "content1", version=1)

    result = await svc.reindex_document("n1", doc.id)

    assert result is doc
    embedding_service.index_document.assert_awaited_once_with(doc.id)


@pytest.mark.asyncio
async def test_approve_pending_indexes_created_documents(async_session, mock_llm):
    embedding_service = AsyncMock()
    svc = ExtractionService(async_session, embedding_service=embedding_service)
    pe = await svc.process_upload(
        novel_id="n1",
        filename="setting.txt",
        content="世界观：天玄大陆。主角林风，外门弟子。",
    )

    docs = await svc.approve_pending(pe.id)

    assert len(docs) > 0
    assert embedding_service.index_document.await_count == len(docs)
    embedding_service.index_document.assert_any_await(docs[0].id)
