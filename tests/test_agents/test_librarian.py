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
