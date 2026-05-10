import pytest
from unittest.mock import AsyncMock

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.schemas.similar_document import SimilarDocument
from novel_dev.db.models import Entity, EntityVersion, Foreshadowing, NovelState
from novel_dev.services.log_service import LogService


@pytest.fixture(autouse=True)
def clear_log_buffers():
    LogService._buffers.clear()
    LogService._listeners.clear()
    LogService._pending_tasks.clear()


@pytest.mark.asyncio
async def test_assemble_with_embedding_service_includes_related_entities(async_session, mock_llm_factory):
    state = NovelState(
        novel_id="n1", current_phase="context_preparation",
        checkpoint_data={
            "current_chapter_plan": {
                "chapter_number": 1, "title": "第一章", "target_word_count": 3000,
                "beats": [{"summary": "主角进入学院", "target_mood": "好奇", "key_entities": ["主角"]}],
            },
            "current_time_tick": 1,
        },
    )
    async_session.add(state)
    await async_session.flush()

    mock_emb_svc = AsyncMock()
    mock_emb_svc.search_similar = AsyncMock(return_value=[])
    mock_emb_svc.search_similar_entities = AsyncMock(return_value=[
        SimilarDocument(doc_id="ent_1", doc_type="character", title="李长老",
            content_preview="青云宗长老，修为高深", similarity_score=0.92),
        SimilarDocument(doc_id="ent_2", doc_type="faction", title="魔道联盟",
            content_preview="暗中策划入侵", similarity_score=0.88),
    ])

    agent = ContextAgent(async_session, embedding_service=mock_emb_svc)
    context = await agent.assemble("n1", "ch1")

    assert len(context.related_entities) == 2
    assert context.related_entities[0].entity_id == "ent_1"
    assert context.related_entities[0].name == "李长老"
    assert context.related_entities[0].type == "character"
    mock_emb_svc.search_similar_entities.assert_awaited_once()


@pytest.mark.asyncio
async def test_assemble_excludes_active_entities_from_related(async_session, mock_llm_factory):
    from novel_dev.db.models import Entity, EntityVersion

    state = NovelState(
        novel_id="n1", current_phase="context_preparation",
        checkpoint_data={
            "current_chapter_plan": {
                "chapter_number": 1, "title": "第一章", "target_word_count": 3000,
                "beats": [{"summary": "主角与林风相遇", "target_mood": "好奇", "key_entities": ["林风"]}],
            },
            "current_time_tick": 1,
        },
    )
    async_session.add(state)

    entity = Entity(id="ent_active", name="林风", type="character", novel_id="n1")
    async_session.add(entity)
    version = EntityVersion(entity_id="ent_active", version=1, state={"status": "alive"})
    async_session.add(version)
    await async_session.flush()

    mock_emb_svc = AsyncMock()
    mock_emb_svc.search_similar = AsyncMock(return_value=[])
    mock_emb_svc.search_similar_entities = AsyncMock(return_value=[
        SimilarDocument(doc_id="ent_active", doc_type="character", title="林风",
            content_preview="主角的好友", similarity_score=0.95),
        SimilarDocument(doc_id="ent_other", doc_type="character", title="张三",
            content_preview="路人甲", similarity_score=0.80),
    ])

    agent = ContextAgent(async_session, embedding_service=mock_emb_svc)
    context = await agent.assemble("n1", "ch1")

    related_ids = {e.entity_id for e in context.related_entities}
    assert "ent_active" not in related_ids
    assert "ent_other" in related_ids
    assert len(context.active_entities) == 1
    assert context.active_entities[0].entity_id == "ent_active"


@pytest.mark.asyncio
async def test_assemble_without_embedding_service_has_empty_related_entities(async_session, mock_llm_factory):
    state = NovelState(
        novel_id="n1", current_phase="context_preparation",
        checkpoint_data={
            "current_chapter_plan": {
                "chapter_number": 1, "title": "第一章", "target_word_count": 3000,
                "beats": [{"summary": "主角进入学院", "target_mood": "好奇", "key_entities": []}],
            },
            "current_time_tick": 1,
        },
    )
    async_session.add(state)
    await async_session.flush()

    agent = ContextAgent(async_session)
    context = await agent.assemble("n1", "ch1")
    assert context.related_entities == []


@pytest.mark.asyncio
async def test_assemble_carries_story_contract_from_checkpoint(async_session, mock_llm_factory):
    story_contract = {
        "protagonist_goal": "查清灭门真相",
        "core_conflict": "家族旧案与宗门暗线",
        "must_carry_forward": ["父亲玉佩"],
    }
    state = NovelState(
        novel_id="n_contract_context",
        current_phase="context_preparation",
        checkpoint_data={
            "story_contract": story_contract,
            "current_chapter_plan": {
                "chapter_number": 1,
                "title": "第一章",
                "target_word_count": 3000,
                "beats": [{"summary": "陆照握住父亲玉佩入局", "target_mood": "压抑", "key_entities": []}],
            },
        },
    )
    async_session.add(state)
    await async_session.flush()

    context = await ContextAgent(async_session).assemble("n_contract_context", "ch_contract")

    assert context.story_contract == story_contract


@pytest.mark.asyncio
async def test_assemble_logs_specific_context_sources(async_session, mock_llm_factory):
    state = NovelState(
        novel_id="n_ctx_log", current_phase="context_preparation",
        checkpoint_data={
            "current_chapter_plan": {
                "chapter_number": 1, "title": "照见旧碑", "target_word_count": 3000,
                "beats": [
                    {
                        "summary": "陆照触发旧碑因果纹",
                        "target_mood": "mysterious",
                        "key_entities": ["陆照"],
                        "foreshadowings_to_embed": ["旧碑暗纹"],
                    }
                ],
            },
            "current_time_tick": 3,
        },
    )
    async_session.add(state)
    async_session.add(Entity(id="ent_luzhao", name="陆照", type="character", novel_id="n_ctx_log"))
    async_session.add(EntityVersion(entity_id="ent_luzhao", version=1, state={"status": "握有道印"}))
    async_session.add(Foreshadowing(
        id="fs_old_tablet",
        novel_id="n_ctx_log",
        content="旧碑暗纹",
        埋下_time_tick=3,
        相关人物_ids=["ent_luzhao"],
        回收状态="pending",
    ))
    await async_session.flush()

    mock_emb_svc = AsyncMock()
    mock_emb_svc.search_similar_entities = AsyncMock(return_value=[
        SimilarDocument(doc_id="ent_elder", doc_type="character", title="守碑长老",
            content_preview="守碑长老知道旧碑来历", similarity_score=0.91),
    ])
    mock_emb_svc.search_similar = AsyncMock(return_value=[
        SimilarDocument(doc_id="doc_world", doc_type="worldview", title="旧碑设定",
            content_preview="旧碑与因果道印相关", similarity_score=0.87),
    ])
    mock_emb_svc.search_similar_chapters = AsyncMock(return_value=[
        SimilarDocument(doc_id="ch_prev", doc_type="chapter", title="前章道印",
            content_preview="陆照取得道印", similarity_score=0.83),
    ])

    agent = ContextAgent(async_session, embedding_service=mock_emb_svc)
    await agent.assemble("n_ctx_log", "ch1")

    entries = list(LogService._buffers["n_ctx_log"])
    source_log = next(entry for entry in entries if entry.get("node") == "context_sources")
    assert source_log["message"] == "章节上下文来源已准备：实体 2 个，文档 1 个，相似章节 1 个，伏笔 1 条"
    assert source_log["metadata"]["query"].startswith("照见旧碑")
    assert source_log["metadata"]["active_entities"][0]["name"] == "陆照"
    assert source_log["metadata"]["semantic_entities"][0]["name"] == "守碑长老"
    assert source_log["metadata"]["documents"][0]["title"] == "旧碑设定"
    assert source_log["metadata"]["similar_chapters"][0]["title"] == "前章道印"
    assert source_log["metadata"]["foreshadowings"][0]["id"] == "fs_old_tablet"
    assert source_log["metadata"]["beat_contexts"][0]["entities"] == ["陆照"]
    assert "guardrail_count" in source_log["metadata"]["beat_contexts"][0]
