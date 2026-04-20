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


class FailingFlushEmbeddingService:
    async def index_entity(self, entity_id: str) -> None:
        raise ValueError("expected 1536 dimensions, not 1024")


@pytest.mark.asyncio
async def test_approve_setting_succeeds_when_entity_indexing_fails(async_session, mock_llm):
    svc = ExtractionService(async_session, FailingFlushEmbeddingService())
    pe = await svc.process_upload(
        novel_id="n1",
        filename="setting.txt",
        content="世界观：天玄大陆。主角林风，外门弟子。",
    )

    docs = await svc.approve_pending(pe.id)

    assert len(docs) > 0
    assert pe.status == "approved"


@pytest.mark.asyncio
async def test_approve_setting_creates_character_entities_with_full_state(async_session, mock_llm):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    svc = ExtractionService(async_session)
    pe = await svc.process_upload(
        novel_id="n_char",
        filename="setting.txt",
        content="世界观：天玄大陆。",
    )
    await svc.approve_pending(pe.id)

    char_docs = [d for d in (await (svc.doc_repo).get_by_type("n_char", "concept")) if d.title == "人物设定"]
    assert len(char_docs) == 1

    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    entities = await entity_repo.list_by_novel("n_char")
    char_entities = [e for e in entities if e.type == "character"]
    assert len(char_entities) >= 1

    for ent in char_entities:
        latest = await version_repo.get_latest(ent.id)
        assert latest is not None
        assert "name" in latest.state
        # identity/personality/goal from CharacterProfile should be in state
        profile = latest.state
        assert profile.get("identity") or profile.get("personality") or profile.get("goal")


@pytest.mark.asyncio
async def test_approve_setting_creates_item_entities_with_description(async_session, mock_llm):
    from novel_dev.agents.setting_extractor import ExtractedSetting, CharacterProfile, ImportantItem
    from novel_dev.agents.file_classifier import FileClassificationResult
    from unittest.mock import AsyncMock, patch

    mock_resp = ExtractedSetting(
        worldview="test",
        power_system="test",
        factions="test",
        character_profiles=[CharacterProfile(name="林风", identity="主角", personality="坚毅", goal="成神")],
        important_items=[
            ImportantItem(name="神秘戒指", description="蕴含上古力量", significance="主角崛起关键"),
        ],
        plot_synopsis="剧情",
    )

    with patch("novel_dev.llm.llm_factory.get") as mock_get:
        mock_client = AsyncMock()
        mock_client.acomplete.side_effect = [
            type("R", (), {"text": FileClassificationResult(file_type="setting", confidence=0.95, reason="").model_dump_json()})(),
            type("R", (), {"text": mock_resp.model_dump_json()})(),
        ]
        mock_get.return_value = mock_client

        svc = ExtractionService(async_session)
        pe = await svc.process_upload("n_item", "setting.txt", "test content")
        await svc.approve_pending(pe.id)

    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)

    entities = await entity_repo.list_by_novel("n_item")
    item_entities = [e for e in entities if e.type == "item"]
    assert len(item_entities) == 1

    latest = await version_repo.get_latest(item_entities[0].id)
    assert latest.state.get("name") == "神秘戒指"
    assert latest.state.get("description") == "蕴含上古力量"
    assert latest.state.get("significance") == "主角崛起关键"
