from unittest.mock import AsyncMock, patch
from pathlib import Path

import pytest
import yaml

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.schemas.context import ChapterPlan, BeatPlan, LocationContext
from novel_dev.llm.models import LLMResponse, TaskConfig
from novel_dev.llm.orchestrator import OrchestratedTaskConfig


@pytest.mark.asyncio
async def test_load_location_context(async_session):
    from novel_dev.repositories.spaceline_repo import SpacelineRepository
    from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
    from novel_dev.repositories.timeline_repo import TimelineRepository

    sp_repo = SpacelineRepository(async_session)
    await sp_repo.create(location_id="loc1", name="青云宗", novel_id="n_test")

    fs_repo = ForeshadowingRepository(async_session)
    await fs_repo.create(
        fs_id="fs1", content="玉佩发光", 埋下_time_tick=1,
        相关人物_ids=[], novel_id="n_test"
    )

    tl_repo = TimelineRepository(async_session)
    await tl_repo.create(tick=1, narrative="入门测试", novel_id="n_test")

    mock_client = AsyncMock()
    mock_client.config = TaskConfig(provider="anthropic", model="context-model")
    mock_client.acomplete.side_effect = [
        LLMResponse(text='{"locations": ["青云宗"], "entities": ["林风"], "time_range": {"start_tick": -1, "end_tick": 1}, "foreshadowing_keywords": ["玉佩"]}'),
        LLMResponse(
            text="",
            structured_payload={
                "current": "青云宗大殿",
                "parent": "青云宗",
                "narrative": "晨光透过雕花窗棂，洒落在青石地面上，钟声从殿外传来，林风在光影里停住脚步。",
            },
        ),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = ContextAgent(async_session)
        plan = ChapterPlan(
            chapter_number=1, title="测试", target_word_count=3000,
            beats=[BeatPlan(summary="开场", target_mood="tense", key_entities=["林风"])]
        )
        result = await agent._load_location_context(plan, "n_test")

    assert result.current == "青云宗大殿"
    assert "晨光" in result.narrative
    assert mock_client.acomplete.call_count == 2


def test_llm_config_enables_context_agent_orchestration():
    config = yaml.safe_load(Path("llm_config.yaml").read_text())

    orchestration = config["agents"]["context_agent"]["orchestration"]
    assert orchestration["enabled"] is True
    assert orchestration["tool_allowlist"] == [
        "get_context_location_details",
        "get_context_entity_states",
        "get_context_foreshadowing_details",
        "get_context_timeline_events",
        "get_novel_state",
        "get_chapter_draft_status",
    ]
    assert orchestration["enable_subtasks"] is True
    assert orchestration["validator_subtask"] == "location_context_quality"
    assert orchestration["repairer_subtask"] == "schema_repair"


@pytest.mark.asyncio
async def test_load_location_context_uses_orchestrated_scene_tools_when_configured(async_session, monkeypatch):
    from novel_dev.db.models import Entity, EntityVersion, NovelState
    from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
    from novel_dev.repositories.spaceline_repo import SpacelineRepository

    await SpacelineRepository(async_session).create(
        location_id="loc_orch",
        name="青云宗",
        novel_id="n_ctx_orch",
        narrative="SECRET_LOCATION_DETAIL",
    )
    async_session.add(Entity(id="ent_ctx_orch", name="林风", type="character", novel_id="n_ctx_orch"))
    async_session.add(EntityVersion(entity_id="ent_ctx_orch", version=1, state={"status": "SECRET_ENTITY_STATE"}))
    async_session.add(NovelState(novel_id="n_ctx_orch", current_phase="context_preparation", checkpoint_data={}))
    await ForeshadowingRepository(async_session).create(
        fs_id="fs_ctx_orch",
        content="SECRET_FORESHADOWING_DETAIL",
        埋下_time_tick=1,
        相关人物_ids=[],
        novel_id="n_ctx_orch",
    )
    await async_session.flush()

    orchestration_config = OrchestratedTaskConfig(
        tool_allowlist=[
            "get_context_location_details",
            "get_context_entity_states",
            "get_context_foreshadowing_details",
            "get_context_timeline_events",
            "get_novel_state",
        ],
        max_tool_calls=4,
        max_tool_result_chars=1200,
    )
    monkeypatch.setattr(
        "novel_dev.agents.context_agent.llm_factory.resolve_orchestration_config",
        lambda agent_name, task: orchestration_config,
    )

    async def fake_call_and_parse_model(agent_name, task, prompt, model_cls, max_retries=3, novel_id=""):
        assert task == "analyze_context_needs"
        return model_cls.model_validate({
            "locations": ["青云宗"],
            "entities": ["林风"],
            "time_range": {},
            "foreshadowing_keywords": ["SECRET"],
        })

    async def fake_orchestrated_call_and_parse_model(
        agent_name,
        task,
        prompt,
        model_cls,
        *,
        tools,
        task_config,
        novel_id="",
        max_retries=3,
    ):
        assert agent_name == "ContextAgent"
        assert task == "build_scene_context"
        assert model_cls is LocationContext
        assert novel_id == "n_ctx_orch"
        assert max_retries == 3
        assert task_config is orchestration_config
        assert "SECRET_LOCATION_DETAIL" not in prompt
        assert "SECRET_ENTITY_STATE" not in prompt
        assert "SECRET_FORESHADOWING_DETAIL" not in prompt
        assert "优先用批量工具一次查询同类数据" in prompt
        tool_names = [tool.name for tool in tools]
        assert "get_context_scene_inputs" not in tool_names
        assert "get_context_location_details" in tool_names
        assert "get_context_entity_states" in tool_names
        assert "get_context_foreshadowing_details" in tool_names
        assert "get_context_timeline_events" in tool_names
        location_tool = next(tool for tool in tools if tool.name == "get_context_location_details")
        entity_tool = next(tool for tool in tools if tool.name == "get_context_entity_states")
        fs_tool = next(tool for tool in tools if tool.name == "get_context_foreshadowing_details")
        timeline_tool = next(tool for tool in tools if tool.name == "get_context_timeline_events")
        locations = await location_tool.handler({"names": ["青云宗", "不存在"]})
        entities = await entity_tool.handler({"names": ["林风", "不存在"]})
        foreshadowings = await fs_tool.handler({"ids": ["fs_ctx_orch", "missing"]})
        timeline = await timeline_tool.handler({})
        assert locations["items"][0]["narrative"] == "SECRET_LOCATION_DETAIL"
        assert locations["missing"] == ["不存在"]
        assert entities["items"][0]["state"] == "{'status': 'SECRET_ENTITY_STATE'}"
        assert entities["missing"] == ["不存在"]
        assert foreshadowings["items"][0]["content"] == "SECRET_FORESHADOWING_DETAIL"
        assert foreshadowings["missing"] == ["missing"]
        assert timeline == []
        return LocationContext(current="青云宗", parent="", narrative="云气压低，林风立在殿前。")

    monkeypatch.setattr("novel_dev.agents.context_agent.call_and_parse_model", fake_call_and_parse_model)
    monkeypatch.setattr(
        "novel_dev.agents.context_agent.orchestrated_call_and_parse_model",
        fake_orchestrated_call_and_parse_model,
    )

    agent = ContextAgent(async_session)
    plan = ChapterPlan(
        chapter_number=1,
        title="测试",
        target_word_count=3000,
        beats=[BeatPlan(summary="林风进入青云宗", target_mood="tense", key_entities=["林风"])],
    )

    result = await agent._load_location_context(plan, "n_ctx_orch")

    assert result.current == "青云宗"
