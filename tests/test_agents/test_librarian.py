import pytest
from unittest.mock import AsyncMock, patch

from novel_dev.agents.librarian import LibrarianAgent
from novel_dev.llm.models import LLMResponse
from novel_dev.schemas.librarian import ExtractionResult


@pytest.mark.asyncio
async def test_librarian_calls_llm_factory(async_session):
    agent = LibrarianAgent(async_session)
    mock_response = ExtractionResult(
        timeline_events=[{"tick": 10, "narrative": "战斗结束"}],
        new_entities=[{"type": "character", "name": "Lin Feng", "state": {"level": 2}}],
    )
    mock_client = AsyncMock()
    # pass 1: ExtractionResult JSON; pass 2: soft state JSON(空即可)
    mock_client.acomplete.side_effect = [
        LLMResponse(text=mock_response.model_dump_json()),
        LLMResponse(text='{"character_updates": [], "new_relationships": []}'),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await agent.extract("n1", "c1", "Lin Feng leveled up after the battle.")

    assert len(result.timeline_events) == 1
    assert result.timeline_events[0].tick == 10
    # 两 pass:硬事实 extract + 软状态 extract_relationships
    tasks = [call.kwargs.get("task") for call in mock_factory.get.call_args_list]
    assert "extract" in tasks
    assert "extract_relationships" in tasks


@pytest.mark.asyncio
async def test_librarian_llm_extraction_success(async_session):
    agent = LibrarianAgent(async_session)
    mock_result = ExtractionResult(
        timeline_events=[{"tick": 10, "narrative": "战斗结束"}],
        new_entities=[{"type": "character", "name": "Lin Feng", "state": {"level": 2}}],
    )
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=mock_result.model_dump_json()),
        LLMResponse(text='{"character_updates": [], "new_relationships": []}'),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await agent.extract("n1", "c1", "Lin Feng leveled up after the battle.")
    assert len(result.timeline_events) == 1
    assert result.timeline_events[0].tick == 10


@pytest.mark.asyncio
async def test_librarian_fallback_on_llm_failure(async_session):
    agent = LibrarianAgent(async_session)
    with patch.object(agent, "_call_llm", new_callable=AsyncMock, side_effect=TimeoutError("LLM timeout")):
        result = agent.fallback_extract("三天后，Lin Feng 来到 Qingyun City。", {})
    assert len(result.timeline_events) == 1
    assert result.timeline_events[0].narrative == "三天后"
    assert any(c.name == "Qingyun City" for c in result.spaceline_changes)


@pytest.mark.asyncio
async def test_librarian_persist_writes_to_database(async_session):
    from novel_dev.repositories.timeline_repo import TimelineRepository
    from novel_dev.repositories.spaceline_repo import SpacelineRepository
    from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.relationship_repo import RelationshipRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    agent = LibrarianAgent(async_session)
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await entity_repo.create("e_ldz", "character", "陆照", novel_id="n1")
    await entity_repo.create("e_sqh", "character", "苏清寒", novel_id="n1")
    await version_repo.create("e_ldz", 1, {"name": "陆照"})
    await version_repo.create("e_sqh", 1, {"name": "苏清寒"})
    await entity_repo.update_version("e_ldz", 1)
    await entity_repo.update_version("e_sqh", 1)

    extraction = ExtractionResult(
        timeline_events=[{"tick": 5, "narrative": "启程"}],
        spaceline_changes=[{"location_id": "loc_1", "name": "Cloud City"}],
        new_foreshadowings=[{"content": "神秘的戒指"}],
        new_relationships=[{"source_entity_id": "陆照", "target_entity_id": "苏清寒", "relation_type": "ally"}],
    )
    await agent.persist(extraction, "c1", "n1")
    await async_session.commit()

    timeline = await TimelineRepository(async_session).get_current_tick()
    assert timeline == 5
    sp = await SpacelineRepository(async_session).get_by_id("loc_1")
    assert sp is not None
    assert sp.novel_id == "n1"
    fs_list = await ForeshadowingRepository(async_session).list_active()
    assert any(fs.content == "神秘的戒指" and fs.novel_id == "n1" for fs in fs_list)
    rels = await RelationshipRepository(async_session).list_by_source("e_ldz", novel_id="n1")
    assert len(rels) == 1
    assert rels[0].target_id == "e_sqh"
    assert rels[0].relation_type == "ally"


@pytest.mark.asyncio
async def test_librarian_persist_merges_duplicate_timeline_tick(async_session):
    from novel_dev.repositories.timeline_repo import TimelineRepository

    agent = LibrarianAgent(async_session)
    timeline_repo = TimelineRepository(async_session)
    existing = await timeline_repo.create(
        tick=0,
        narrative="旧版：陆照在坡顶休息。",
        anchor_chapter_id="vol_1_ch_1",
        novel_id="n1",
    )
    extraction = ExtractionResult(
        timeline_events=[{
            "tick": 0,
            "narrative": "陆照在前往后山途中于坡顶休息，回忆七岁丧父母后独自谋生的经历。",
        }],
    )

    await agent.persist(extraction, "vol_1_ch_1", "n1")
    await async_session.commit()

    timelines = await timeline_repo.list_by_novel("n1")
    assert len(timelines) == 1
    assert timelines[0].id == existing.id
    assert timelines[0].tick == 0
    assert "旧版：陆照在坡顶休息。" in timelines[0].narrative
    assert "独自谋生" in timelines[0].narrative


@pytest.mark.asyncio
async def test_librarian_persist_updates_existing_new_entity_by_name(async_session):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    agent = LibrarianAgent(async_session)
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    await entity_repo.create("e_ldz", "character", "陆照", novel_id="n1")
    await version_repo.create("e_ldz", 1, {"name": "陆照", "status": "existing"})
    await entity_repo.update_version("e_ldz", 1)

    extraction = ExtractionResult(
        new_entities=[{
            "type": "character",
            "name": "陆照",
            "state": {"状态": "chapter_updated"},
        }],
    )

    await agent.persist(extraction, "vol_1_ch_1", "n1")
    await async_session.commit()

    entities = await entity_repo.list_by_novel("n1")
    assert [entity.id for entity in entities] == ["e_ldz"]
    latest = await version_repo.get_latest("e_ldz")
    assert latest.state["current_state"]["condition"] == "chapter_updated"


@pytest.mark.asyncio
async def test_librarian_persist_creates_new_entity_with_policy_state(async_session):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    agent = LibrarianAgent(async_session)
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)

    extraction = ExtractionResult(
        new_entities=[{
            "type": "character",
            "name": "陆照",
            "state": {"身份": "主角", "状态": "昏迷"},
        }],
    )

    await agent.persist(extraction, "vol_1_ch_1", "n1")
    await async_session.commit()

    entities = await entity_repo.list_by_novel("n1")
    assert len(entities) == 1
    entity = entities[0]
    assert entity.name == "陆照"
    latest = await version_repo.get_latest(entity.id)
    assert latest.version == 1
    assert latest.state["canonical_profile"]["name"] == "陆照"
    assert latest.state["canonical_profile"]["identity_role"] == "主角"
    assert latest.state["current_state"]["condition"] == "昏迷"


@pytest.mark.asyncio
async def test_librarian_persist_new_entity_update_uses_entity_state_policy(async_session):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    agent = LibrarianAgent(async_session)
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)

    await entity_repo.create("e_ldz", "character", "陆照", novel_id="n1")
    await version_repo.create(
        "e_ldz",
        1,
        {
            "canonical_profile": {"name": "陆照", "identity_role": "主角"},
            "current_state": {},
            "observations": {},
            "canonical_meta": {"identity_role": {"source": "setting"}},
        },
        chapter_id="setting",
    )
    await entity_repo.update_version("e_ldz", 1)

    extraction = ExtractionResult(
        new_entities=[{
            "type": "character",
            "name": "陆照",
            "state": {"身份": "小人物", "职业": "采药人"},
        }],
    )

    await agent.persist(extraction, "vol_1_ch_1", "n1")
    await async_session.commit()

    entities = await entity_repo.list_by_novel("n1")
    assert [entity.id for entity in entities] == ["e_ldz"]
    latest = await version_repo.get_latest("e_ldz")
    assert latest.version == 2
    assert latest.state["canonical_profile"]["identity_role"] == "主角"
    assert latest.state["current_state"]["social_position"] == "小人物"
    assert latest.state["current_state"]["occupation"] == "采药人"


@pytest.mark.asyncio
async def test_librarian_persist_skips_ambiguous_duplicate_new_entity(async_session):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    agent = LibrarianAgent(async_session)
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)

    await entity_repo.create("e_yf_1", "character", "叶凡", novel_id="n1")
    await entity_repo.create("e_yf_2", "character", "叶凡", novel_id="n1")

    extraction = ExtractionResult(
        new_entities=[{
            "type": "character",
            "name": "叶凡",
            "state": {"状态": "被再次提及"},
        }],
    )

    await agent.persist(extraction, "vol_1_ch_1", "n1")
    await async_session.commit()

    entities = await entity_repo.list_by_novel("n1")
    assert len(entities) == 2
    assert sorted(entity.id for entity in entities) == ["e_yf_1", "e_yf_2"]
    assert await version_repo.get_latest("e_yf_1") is None
    assert await version_repo.get_latest("e_yf_2") is None


@pytest.mark.asyncio
async def test_librarian_persist_treats_blank_spaceline_parent_as_root(async_session):
    from novel_dev.repositories.spaceline_repo import SpacelineRepository

    agent = LibrarianAgent(async_session)
    extraction = ExtractionResult(
        spaceline_changes=[{
            "location_id": "山村",
            "name": "山村",
            "parent_id": "",
            "narrative": "一座被晨雾笼罩的偏僻山村",
        }],
    )

    await agent.persist(extraction, "vol_1_ch_1", "n1")
    await async_session.commit()

    loc = await SpacelineRepository(async_session).get_by_id("山村")
    assert loc is not None
    assert loc.parent_id is None
    assert loc.novel_id == "n1"


@pytest.mark.asyncio
async def test_librarian_persist_drops_missing_spaceline_parent(async_session):
    from novel_dev.repositories.spaceline_repo import SpacelineRepository

    agent = LibrarianAgent(async_session)
    extraction = ExtractionResult(
        spaceline_changes=[{
            "location_id": "山村",
            "name": "山村",
            "parent_id": "不存在的父地点",
            "narrative": "一座被晨雾笼罩的偏僻山村",
        }],
    )

    await agent.persist(extraction, "vol_1_ch_1", "n1")
    await async_session.commit()

    loc = await SpacelineRepository(async_session).get_by_id("山村")
    assert loc is not None
    assert loc.parent_id is None


@pytest.mark.asyncio
async def test_librarian_persist_upserts_relationship_for_existing_pair(async_session):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.relationship_repo import RelationshipRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    agent = LibrarianAgent(async_session)
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    rel_repo = RelationshipRepository(async_session)

    await entity_repo.create("e_ldz", "character", "陆照", novel_id="n1")
    await entity_repo.create("e_sqh", "character", "苏清寒", novel_id="n1")
    await version_repo.create("e_ldz", 1, {"name": "陆照"})
    await version_repo.create("e_sqh", 1, {"name": "苏清寒"})
    await entity_repo.update_version("e_ldz", 1)
    await entity_repo.update_version("e_sqh", 1)
    await rel_repo.create("e_ldz", "e_sqh", "rival", novel_id="n1")

    extraction = ExtractionResult(
        new_relationships=[{"source_entity_id": "陆照", "target_entity_id": "苏清寒", "relation_type": "ally", "meta": {"chapter": 1}}],
    )
    await agent.persist(extraction, "c2", "n1")
    await async_session.commit()

    rels = await rel_repo.list_by_source("e_ldz", novel_id="n1")
    assert len(rels) == 1
    assert rels[0].target_id == "e_sqh"
    assert rels[0].relation_type == "ally"
    assert rels[0].meta == {"chapter": 1}


@pytest.mark.asyncio
async def test_librarian_persist_skips_ambiguous_duplicate_entity_name(async_session):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.relationship_repo import RelationshipRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    agent = LibrarianAgent(async_session)
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)

    await entity_repo.create("e_yf_1", "character", "叶凡", novel_id="n1")
    await entity_repo.create("e_yf_2", "character", "叶凡", novel_id="n1")
    await entity_repo.create("e_ldz", "character", "陆照", novel_id="n1")
    await version_repo.create("e_ldz", 1, {"name": "陆照"})
    await entity_repo.update_version("e_ldz", 1)

    extraction = ExtractionResult(
        character_updates=[{
            "entity_id": "叶凡",
            "state": {"状态": "被再次提及"},
            "diff_summary": {"source": "chapter"},
        }],
        new_relationships=[{
            "source_entity_id": "陆照",
            "target_entity_id": "叶凡",
            "relation_type": "mentioned",
        }],
    )

    await agent.persist(extraction, "c1", "n1")
    await async_session.commit()

    rels = await RelationshipRepository(async_session).list_by_source("e_ldz", novel_id="n1")
    assert rels == []


@pytest.mark.asyncio
async def test_librarian_persist_resolves_duplicate_same_group_entity_name(async_session):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.relationship_repo import RelationshipRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    agent = LibrarianAgent(async_session)
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)

    await entity_repo.create("e_ldz", "character", "陆照", novel_id="n1")
    await entity_repo.create("e_wmy_old", "character", "王明月", novel_id="n1")
    await entity_repo.create("e_wmy_new", "人物", "王明月", novel_id="n1")
    await version_repo.create("e_ldz", 1, {"name": "陆照"})
    await version_repo.create("e_wmy_old", 1, {"name": "王明月"})
    await version_repo.create("e_wmy_new", 2, {"name": "王明月"})
    await entity_repo.update_version("e_ldz", 1)
    await entity_repo.update_version("e_wmy_old", 1)
    await entity_repo.update_version("e_wmy_new", 2)

    extraction = ExtractionResult(
        new_relationships=[{
            "source_entity_id": "陆照",
            "target_entity_id": "王明月",
            "relation_type": "mentioned",
        }],
    )

    await agent.persist(extraction, "c1", "n1")
    await async_session.commit()

    rels = await RelationshipRepository(async_session).list_by_source("e_ldz", novel_id="n1")
    assert len(rels) == 1
    assert rels[0].target_id == "e_wmy_new"


@pytest.mark.asyncio
async def test_librarian_persist_demotes_canonical_conflict_to_current_state(async_session):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    agent = LibrarianAgent(async_session)
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)

    await entity_repo.create("e_ldz", "character", "陆照", novel_id="n1")
    await version_repo.create(
        "e_ldz",
        1,
        {
            "canonical_profile": {"name": "陆照", "identity_role": "主角"},
            "current_state": {},
            "observations": {},
            "canonical_meta": {"identity_role": {"source": "setting"}},
        },
        chapter_id="setting",
    )
    await entity_repo.update_version("e_ldz", 1)

    extraction = ExtractionResult(
        character_updates=[{
            "entity_id": "陆照",
            "state": {"身份": "小人物", "职业": "采药人", "状态": "昏迷"},
            "diff_summary": {"source": "chapter"},
        }],
    )

    await agent.persist(extraction, "vol_1_ch_1", "n1")
    await async_session.commit()

    latest = await version_repo.get_latest("e_ldz")
    assert latest.version == 2
    assert latest.state["canonical_profile"]["identity_role"] == "主角"
    assert latest.state["current_state"]["social_position"] == "小人物"
    assert latest.state["current_state"]["occupation"] == "采药人"
    assert latest.state["current_state"]["condition"] == "昏迷"


@pytest.mark.asyncio
async def test_librarian_persist_policy_events_are_logged(async_session, monkeypatch):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    captured = []

    def fake_log_agent_detail(
        novel_id,
        agent,
        message,
        *,
        node,
        task,
        metadata=None,
        status="succeeded",
        level="info",
        **kwargs,
    ):
        captured.append({
            "novel_id": novel_id,
            "agent": agent,
            "message": message,
            "node": node,
            "task": task,
            "metadata": metadata or {},
            "status": status,
            "level": level,
            "extra_kwargs": kwargs,
        })

    monkeypatch.setattr("novel_dev.agents.librarian.log_agent_detail", fake_log_agent_detail)

    agent = LibrarianAgent(async_session)
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)

    await entity_repo.create("e_ldz", "character", "陆照", novel_id="n1")
    await version_repo.create(
        "e_ldz",
        1,
        {
            "canonical_profile": {"name": "陆照", "identity_role": "主角"},
            "current_state": {},
            "observations": {},
            "canonical_meta": {"identity_role": {"source": "setting"}},
        },
    )
    await entity_repo.update_version("e_ldz", 1)

    extraction = ExtractionResult(
        character_updates=[{
            "entity_id": "陆照",
            "state": {"身份": "小人物"},
            "diff_summary": {"source": "chapter"},
        }],
    )

    await agent.persist(extraction, "vol_1_ch_1", "n1")

    result_logs = [entry for entry in captured if entry["node"] == "librarian_persist_result"]
    assert result_logs
    metadata = result_logs[-1]["metadata"]
    assert "policy_events" in metadata, metadata
    events = metadata["policy_events"]
    assert any(event["type"] == "canonical_conflict_demoted" for event in events)


@pytest.mark.asyncio
async def test_librarian_persist_policy_events_are_bounded_and_counted(async_session, monkeypatch):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    captured = []

    def fake_log_agent_detail(
        novel_id,
        agent,
        message,
        *,
        node,
        task,
        metadata=None,
        status="succeeded",
        level="info",
        **kwargs,
    ):
        captured.append({
            "node": node,
            "metadata": metadata or {},
        })

    monkeypatch.setattr("novel_dev.agents.librarian.log_agent_detail", fake_log_agent_detail)

    agent = LibrarianAgent(async_session)
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)

    await entity_repo.create("e_ldz", "character", "陆照", novel_id="n1")
    await version_repo.create(
        "e_ldz",
        1,
        {
            "canonical_profile": {"name": "陆照", "identity_role": "主角"},
            "current_state": {},
            "observations": {},
            "canonical_meta": {"identity_role": {"source": "setting"}},
        },
    )
    await entity_repo.update_version("e_ldz", 1)

    long_value = "小人物" * 80
    noisy_state = {"身份": long_value}
    noisy_state.update({f"未知字段{i}": f"观察值{i}" for i in range(25)})
    extraction = ExtractionResult(
        character_updates=[{
            "entity_id": "陆照",
            "state": noisy_state,
            "diff_summary": {"source": "chapter"},
        }],
    )

    await agent.persist(extraction, "vol_1_ch_1", "n1")

    metadata = [entry["metadata"] for entry in captured if entry["node"] == "librarian_persist_result"][-1]
    assert metadata["policy_event_count"] == 26
    assert len(metadata["policy_events"]) == 20
    demotion = metadata["policy_events"][0]
    assert demotion["type"] == "canonical_conflict_demoted"
    assert demotion["to"] == long_value[:120]
