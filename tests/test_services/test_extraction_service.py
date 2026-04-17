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
