import pytest
from unittest.mock import AsyncMock

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.schemas.similar_document import SimilarDocument
from novel_dev.db.models import Entity, EntityRelationship, EntityVersion, Foreshadowing, NovelState
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
async def test_assemble_formats_structured_entity_memory(async_session, mock_llm_factory):
    state = NovelState(
        novel_id="n_entity_memory",
        current_phase="context_preparation",
        checkpoint_data={
            "current_chapter_plan": {
                "chapter_number": 8,
                "title": "旧案再起",
                "target_word_count": 3000,
                "beats": [{"summary": "林照握着父亲玉佩追查旧案", "target_mood": "压抑", "key_entities": ["林照"]}],
            },
        },
    )
    async_session.add(state)
    async_session.add(Entity(id="ent_linzhao_memory", name="林照", type="character", novel_id="n_entity_memory"))
    async_session.add(EntityVersion(
        entity_id="ent_linzhao_memory",
        version=1,
        state={
            "canonical_profile": {
                "identity_role": "青云宗外门弟子",
                "long_term_goal": "查清灭门真相",
            },
            "current_state": {
                "location": "黑水城",
                "possessions": ["父亲玉佩"],
            },
            "observations": {
                "ch_2": ["在祠堂发现父亲玉佩裂纹"],
                "ch_7": ["得知血煞盟与旧案有关"],
            },
        },
    ))
    await async_session.flush()

    context = await ContextAgent(async_session).assemble("n_entity_memory", "ch_entity_memory")
    entity = context.active_entities[0]

    assert entity.memory_snapshot["canonical_profile"]["identity_role"] == "青云宗外门弟子"
    assert entity.memory_snapshot["current_state"]["location"] == "黑水城"
    assert "固定档案" in entity.current_state
    assert "青云宗外门弟子" in entity.current_state
    assert "黑水城" in entity.current_state
    assert "血煞盟与旧案有关" in entity.current_state


@pytest.mark.asyncio
async def test_assemble_includes_recent_active_entity_even_when_plan_omits_key_entities(async_session, mock_llm_factory):
    state = NovelState(
        novel_id="n_recent_context",
        current_phase="context_preparation",
        current_volume_id="v1",
        current_chapter_id="ch_12",
        checkpoint_data={
            "current_chapter_plan": {
                "chapter_id": "ch_12",
                "chapter_number": 12,
                "title": "旧债回声",
                "target_word_count": 3000,
                "beats": [{"summary": "陆照回到黑水城，听见有人提起旧债", "target_mood": "压抑", "key_entities": []}],
            },
            "current_volume_plan": {
                "chapters": [
                    {"chapter_id": "ch_10", "chapter_number": 10, "title": "十"},
                    {"chapter_id": "ch_11", "chapter_number": 11, "title": "十一"},
                    {"chapter_id": "ch_12", "chapter_number": 12, "title": "十二"},
                ],
            },
        },
    )
    async_session.add(state)
    async_session.add(Entity(id="ent_sqh_recent", name="苏清寒", type="character", novel_id="n_recent_context"))
    async_session.add(EntityVersion(
        entity_id="ent_sqh_recent",
        version=1,
        chapter_id="ch_11",
        state={
            "canonical_profile": {"identity_role": "黑水城旧案证人"},
            "current_state": {"condition": "重伤失踪"},
        },
    ))
    await async_session.flush()

    context = await ContextAgent(async_session).assemble("n_recent_context", "ch_12")

    assert [entity.name for entity in context.active_entities] == ["苏清寒"]
    assert "重伤失踪" in context.active_entities[0].current_state
    assert any("苏清寒" in item for item in context.guardrails)


@pytest.mark.asyncio
async def test_assemble_includes_relationship_neighbors_for_planned_entities(async_session, mock_llm_factory):
    state = NovelState(
        novel_id="n_neighbor_context",
        current_phase="context_preparation",
        checkpoint_data={
            "current_chapter_plan": {
                "chapter_number": 6,
                "title": "同盟裂痕",
                "target_word_count": 3000,
                "beats": [{"summary": "陆照怀疑盟约被人动过手脚", "target_mood": "紧张", "key_entities": ["陆照"]}],
            },
        },
    )
    async_session.add(state)
    async_session.add(Entity(id="ent_lz_neighbor", name="陆照", type="character", novel_id="n_neighbor_context"))
    async_session.add(Entity(id="ent_sqh_neighbor", name="苏清寒", type="character", novel_id="n_neighbor_context"))
    async_session.add(EntityVersion(
        entity_id="ent_lz_neighbor",
        version=1,
        state={"current_state": {"condition": "正在追查盟约"}},
    ))
    async_session.add(EntityVersion(
        entity_id="ent_sqh_neighbor",
        version=1,
        state={"current_state": {"condition": "盟友，但刚刚失联"}},
    ))
    async_session.add(EntityRelationship(
        novel_id="n_neighbor_context",
        source_id="ent_lz_neighbor",
        target_id="ent_sqh_neighbor",
        relation_type="ally",
        is_active=True,
    ))
    await async_session.flush()

    context = await ContextAgent(async_session).assemble("n_neighbor_context", "ch_6")

    assert [entity.name for entity in context.active_entities] == ["陆照", "苏清寒"]
    assert "盟友，但刚刚失联" in context.active_entities[1].current_state
    assert any("苏清寒" in item for item in context.guardrails)


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
