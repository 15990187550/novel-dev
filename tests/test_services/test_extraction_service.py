from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.services.extraction_service import ExtractionService
from novel_dev.services.embedding_service import EmbeddingService
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
                if "文件名：style.txt" in prompt or "文件名：style" in prompt:
                    return type("Resp", (), {"text": FileClassificationResult(file_type="style_sample", confidence=0.95, reason="mock").model_dump_json()})()
                return type("Resp", (), {"text": FileClassificationResult(file_type="setting", confidence=0.95, reason="mock").model_dump_json()})()
            if "设定提取专家" in prompt:
                return type("Resp", (), {"text": ExtractedSetting(
                    worldview="天玄大陆",
                    power_system="修炼体系",
                    factions="宗门分布",
                    character_profiles=[CharacterProfile(name="林风", identity="外门弟子", personality="坚韧", goal="变强", appearance="黑衣少年", background="寒门出身", ability="剑术", realm="筑基", relationships="与宗门长老关系紧张", resources="祖传玉佩", secrets="体内藏有残魂", conflict="与内门弟子敌对", arc="从求生走向担当", notes="遇强则强")],
                    important_items=[],
                    plot_synopsis="剧情梗概",
                ).model_dump_json()})()
            if "文学风格分析师" in prompt or "小说文风分析师" in prompt:
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
    assert pe.diff_result is not None
    assert pe.diff_result["entity_diffs"]

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
    pe1 = await svc.process_upload("n1", "style.txt", "a" * 10000)
    await svc.approve_pending(pe1.id)
    pe2 = await svc.process_upload("n1", "style.txt", "b" * 10000)
    await svc.approve_pending(pe2.id)

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
async def test_approve_setting_succeeds_when_entity_embedding_dimensions_mismatch(async_session, mock_llm):
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    svc = ExtractionService(async_session, EmbeddingService(async_session, mock_embedder))
    pe = await svc.process_upload(
        novel_id="n_dim",
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
        profile = latest.state
        assert profile.get("identity") or profile.get("personality") or profile.get("goal")
        assert profile.get("appearance") is not None
        assert profile.get("background") is not None
        assert profile.get("ability") is not None
        assert profile.get("realm") is not None
        assert profile.get("relationships") is not None


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


@pytest.mark.asyncio
async def test_approve_setting_merges_duplicate_character_entities(async_session):
    from novel_dev.agents.setting_extractor import ExtractedSetting, CharacterProfile
    from novel_dev.agents.file_classifier import FileClassificationResult
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    first = ExtractedSetting(
        worldview="test",
        power_system="test",
        factions="test",
        character_profiles=[CharacterProfile(name="陆照", identity="主角", personality="坚毅", goal="修炼")],
        important_items=[],
        plot_synopsis="剧情",
    )
    second = ExtractedSetting(
        worldview="test",
        power_system="test",
        factions="test",
        character_profiles=[CharacterProfile(name="陆照", identity="道经继承者", personality="正统", goal="超脱")],
        important_items=[],
        plot_synopsis="剧情",
    )

    with patch("novel_dev.llm.llm_factory.get") as mock_get:
        mock_client = AsyncMock()
        mock_client.acomplete.side_effect = [
            type("R", (), {"text": FileClassificationResult(file_type="setting", confidence=0.95, reason="").model_dump_json()})(),
            type("R", (), {"text": first.model_dump_json()})(),
            type("R", (), {"text": FileClassificationResult(file_type="setting", confidence=0.95, reason="").model_dump_json()})(),
            type("R", (), {"text": second.model_dump_json()})(),
        ]
        mock_get.return_value = mock_client

        svc = ExtractionService(async_session)
        pe1 = await svc.process_upload("n_dedup", "setting1.txt", "first")
        await svc.approve_pending(pe1.id)
        pe2 = await svc.process_upload("n_dedup", "setting2.txt", "second")
        await svc.approve_pending(pe2.id)

    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    entities = await entity_repo.list_by_novel("n_dedup")
    char_entities = [e for e in entities if e.type == "character" and e.name == "陆照"]

    assert len(char_entities) == 1
    assert char_entities[0].current_version == 1
    latest = await version_repo.get_latest(char_entities[0].id)
    assert latest.state["identity"] == "主角"
    assert latest.state["goal"] == "修炼"


@pytest.mark.asyncio
async def test_approve_setting_merges_character_alias_by_normalized_name(async_session):
    from novel_dev.agents.setting_extractor import ExtractedSetting, CharacterProfile
    from novel_dev.agents.file_classifier import FileClassificationResult
    from novel_dev.repositories.entity_repo import EntityRepository

    first = ExtractedSetting(
        worldview="test",
        power_system="test",
        factions="test",
        character_profiles=[CharacterProfile(name="陆照（主角）", identity="主角", personality="坚毅", goal="修炼")],
        important_items=[],
        plot_synopsis="剧情",
    )
    second = ExtractedSetting(
        worldview="test",
        power_system="test",
        factions="test",
        character_profiles=[CharacterProfile(name="陆照", identity="道经继承者", personality="沉稳", goal="超脱")],
        important_items=[],
        plot_synopsis="剧情",
    )

    with patch("novel_dev.llm.llm_factory.get") as mock_get:
        mock_client = AsyncMock()
        mock_client.acomplete.side_effect = [
            type("R", (), {"text": FileClassificationResult(file_type="setting", confidence=0.95, reason="").model_dump_json()})(),
            type("R", (), {"text": first.model_dump_json()})(),
            type("R", (), {"text": FileClassificationResult(file_type="setting", confidence=0.95, reason="").model_dump_json()})(),
            type("R", (), {"text": second.model_dump_json()})(),
        ]
        mock_get.return_value = mock_client

        svc = ExtractionService(async_session)
        pe1 = await svc.process_upload("n_alias", "setting1.txt", "first")
        await svc.approve_pending(pe1.id)
        pe2 = await svc.process_upload("n_alias", "setting2.txt", "second")
        await svc.approve_pending(pe2.id)

    entity_repo = EntityRepository(async_session)
    entities = await entity_repo.list_by_novel("n_alias")
    char_entities = [e for e in entities if e.type == "character"]

    assert len(char_entities) == 1
    assert char_entities[0].name == "陆照（主角）"


@pytest.mark.asyncio
async def test_approve_setting_auto_applies_additive_entity_diff(async_session):
    from novel_dev.agents.setting_extractor import ExtractedSetting, CharacterProfile
    from novel_dev.agents.file_classifier import FileClassificationResult
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository
    from novel_dev.services.entity_service import EntityService

    entity_svc = EntityService(async_session)
    await entity_svc.create_entity(
        "ent_existing",
        "character",
        "陆照",
        novel_id="n_additive",
        initial_state={"name": "陆照", "identity": "主角", "goal": "修炼"},
    )
    extracted = ExtractedSetting(
        worldview="test",
        power_system="test",
        factions="test",
        character_profiles=[CharacterProfile(name="陆照", identity="主角", goal="修炼", appearance="青衫少年", resources="道经传承")],
        important_items=[],
        plot_synopsis="剧情",
    )

    with patch("novel_dev.llm.llm_factory.get") as mock_get:
        mock_client = AsyncMock()
        mock_client.acomplete.side_effect = [
            type("R", (), {"text": FileClassificationResult(file_type="setting", confidence=0.95, reason="").model_dump_json()})(),
            type("R", (), {"text": extracted.model_dump_json()})(),
        ]
        mock_get.return_value = mock_client

        svc = ExtractionService(async_session)
        pe = await svc.process_upload("n_additive", "setting.txt", "content")
        assert pe.diff_result["summary"] == "1 个可自动补充实体"
        changes = pe.diff_result["entity_diffs"][0]["field_changes"]
        assert {c["field"] for c in changes} == {"appearance", "resources"}
        assert all(c["auto_applicable"] for c in changes)
        await svc.approve_pending(pe.id)

    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    entity = await entity_repo.find_by_name("陆照", entity_type="character", novel_id="n_additive")
    latest = await version_repo.get_latest(entity.id)
    assert latest.state["appearance"] == "青衫少年"
    assert latest.state["resources"] == "道经传承"

    refreshed = await svc.pending_repo.get_by_id(pe.id)
    assert refreshed.resolution_result == {
        "field_resolutions": [
            {"entity_type": "character", "entity_name": "陆照", "field": "appearance", "action": "auto_apply", "applied": True},
            {"entity_type": "character", "entity_name": "陆照", "field": "resources", "action": "auto_apply", "applied": True},
        ]
    }


@pytest.mark.asyncio
async def test_approve_setting_records_conflict_resolution_result(async_session):
    from novel_dev.agents.setting_extractor import ExtractedSetting, CharacterProfile
    from novel_dev.agents.file_classifier import FileClassificationResult
    from novel_dev.services.entity_service import EntityService

    entity_svc = EntityService(async_session)
    await entity_svc.create_entity(
        "ent_resolution_log",
        "character",
        "陆照",
        novel_id="n_resolution_log",
        initial_state={"name": "陆照", "identity": "主角", "goal": "修炼"},
    )
    extracted = ExtractedSetting(
        worldview="test",
        power_system="test",
        factions="test",
        character_profiles=[CharacterProfile(name="陆照", identity="道经继承者", goal="超脱")],
        important_items=[],
        plot_synopsis="剧情",
    )

    with patch("novel_dev.llm.llm_factory.get") as mock_get:
        mock_client = AsyncMock()
        mock_client.acomplete.side_effect = [
            type("R", (), {"text": FileClassificationResult(file_type="setting", confidence=0.95, reason="").model_dump_json()})(),
            type("R", (), {"text": extracted.model_dump_json()})(),
        ]
        mock_get.return_value = mock_client

        svc = ExtractionService(async_session)
        pe = await svc.process_upload("n_resolution_log", "setting.txt", "content")
        await svc.approve_pending(
            pe.id,
            field_resolutions=[
                {"entity_type": "character", "entity_name": "陆照", "field": "identity", "action": "use_new"},
                {"entity_type": "character", "entity_name": "陆照", "field": "goal", "action": "skip"},
            ],
        )

    refreshed = await svc.pending_repo.get_by_id(pe.id)
    assert refreshed.resolution_result == {
        "field_resolutions": [
            {"entity_type": "character", "entity_name": "陆照", "field": "identity", "action": "use_new", "applied": True},
            {"entity_type": "character", "entity_name": "陆照", "field": "goal", "action": "skip", "applied": False},
        ]
    }


@pytest.mark.asyncio
async def test_approve_setting_records_keep_old_resolution_result(async_session):
    from novel_dev.agents.setting_extractor import ExtractedSetting, CharacterProfile
    from novel_dev.agents.file_classifier import FileClassificationResult
    from novel_dev.services.entity_service import EntityService

    entity_svc = EntityService(async_session)
    await entity_svc.create_entity(
        "ent_keep_old",
        "character",
        "陆照",
        novel_id="n_keep_old",
        initial_state={"name": "陆照", "identity": "主角", "goal": "修炼"},
    )
    extracted = ExtractedSetting(
        worldview="test",
        power_system="test",
        factions="test",
        character_profiles=[CharacterProfile(name="陆照", identity="道经继承者", goal="超脱")],
        important_items=[],
        plot_synopsis="剧情",
    )

    with patch("novel_dev.llm.llm_factory.get") as mock_get:
        mock_client = AsyncMock()
        mock_client.acomplete.side_effect = [
            type("R", (), {"text": FileClassificationResult(file_type="setting", confidence=0.95, reason="").model_dump_json()})(),
            type("R", (), {"text": extracted.model_dump_json()})(),
        ]
        mock_get.return_value = mock_client

        svc = ExtractionService(async_session)
        pe = await svc.process_upload("n_keep_old", "setting.txt", "content")
        await svc.approve_pending(pe.id)

    refreshed = await svc.pending_repo.get_by_id(pe.id)
    assert refreshed.resolution_result == {
        "field_resolutions": [
            {"entity_type": "character", "entity_name": "陆照", "field": "identity", "action": "keep_old", "applied": False},
            {"entity_type": "character", "entity_name": "陆照", "field": "goal", "action": "keep_old", "applied": False},
        ]
    }


@pytest.mark.asyncio
async def test_approve_setting_applies_conflict_resolution_use_new(async_session):
    from novel_dev.agents.setting_extractor import ExtractedSetting, CharacterProfile
    from novel_dev.agents.file_classifier import FileClassificationResult
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository
    from novel_dev.services.entity_service import EntityService

    entity_svc = EntityService(async_session)
    await entity_svc.create_entity(
        "ent_conflict",
        "character",
        "陆照",
        novel_id="n_resolution",
        initial_state={"name": "陆照", "identity": "主角", "goal": "修炼"},
    )
    extracted = ExtractedSetting(
        worldview="test",
        power_system="test",
        factions="test",
        character_profiles=[CharacterProfile(name="陆照", identity="道经继承者", goal="超脱")],
        important_items=[],
        plot_synopsis="剧情",
    )

    with patch("novel_dev.llm.llm_factory.get") as mock_get:
        mock_client = AsyncMock()
        mock_client.acomplete.side_effect = [
            type("R", (), {"text": FileClassificationResult(file_type="setting", confidence=0.95, reason="").model_dump_json()})(),
            type("R", (), {"text": extracted.model_dump_json()})(),
        ]
        mock_get.return_value = mock_client

        svc = ExtractionService(async_session)
        pe = await svc.process_upload("n_resolution", "setting.txt", "content")
        assert pe.diff_result["summary"] == "1 个冲突实体"
        await svc.approve_pending(
            pe.id,
            field_resolutions=[
                {"entity_type": "character", "entity_name": "陆照", "field": "identity", "action": "use_new"},
                {"entity_type": "character", "entity_name": "陆照", "field": "goal", "action": "use_new"},
            ],
        )

    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    entity = await entity_repo.find_by_name("陆照", entity_type="character", novel_id="n_resolution")
    latest = await version_repo.get_latest(entity.id)
    assert latest.state["identity"] == "道经继承者"
    assert latest.state["goal"] == "超脱"


@pytest.mark.asyncio
async def test_approve_setting_builds_diff_for_legacy_pending(async_session):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    svc = ExtractionService(async_session)
    pe = await svc.pending_repo.create(
        pe_id="pe_legacy",
        novel_id="n_legacy",
        extraction_type="setting",
        raw_result={
            "worldview": "旧世界观",
            "power_system": "旧体系",
            "factions": "旧势力",
            "plot_synopsis": "旧剧情",
            "character_profiles": [
                {
                    "name": "陆照",
                    "identity": "主角",
                    "personality": "坚毅",
                    "goal": "修炼",
                }
            ],
            "important_items": [],
        },
        proposed_entities=[{"type": "character", "name": "陆照", "data": {"name": "陆照", "identity": "主角", "personality": "坚毅", "goal": "修炼"}}],
    )

    docs = await svc.approve_pending(pe.id)
    assert len(docs) > 0

    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    entity = await entity_repo.find_by_name("陆照", entity_type="character", novel_id="n_legacy")
    assert entity is not None
    latest = await version_repo.get_latest(entity.id)
    assert latest.state["identity"] == "主角"

    refreshed = await svc.pending_repo.get_by_id(pe.id)
    assert refreshed.resolution_result is not None
    assert refreshed.resolution_result["field_resolutions"]

