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
                "narrative": "晨光透过青云宗大殿的雕花窗棂，洒落在青石地面上，钟声从殿外传来，林风在光影里停住脚步。",
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


@pytest.mark.asyncio
async def test_load_location_context_falls_back_when_scene_narrative_empty(
    async_session,
    monkeypatch,
):
    agent = ContextAgent(async_session)
    monkeypatch.setattr(
        agent,
        "_analyze_context_needs",
        AsyncMock(
            return_value={
                "locations": [],
                "entities": [],
                "time_range": {"start_tick": -1, "end_tick": 1},
                "foreshadowing_keywords": [],
            }
        ),
    )
    monkeypatch.setattr(
        "novel_dev.agents.context_agent.orchestrated_call_and_parse_model",
        AsyncMock(
            side_effect=RuntimeError(
                "build_scene_context failed validator subtask after repair: "
                "{'valid': False, 'reason': 'narrative_too_short'}"
            )
        ),
    )

    class FakeFactory:
        @staticmethod
        def resolve_orchestration_config(_agent, _task):
            return OrchestratedTaskConfig(
                tool_allowlist=[],
                enable_subtasks=True,
                validator_subtask="location_context_quality",
                repairer_subtask="schema_repair",
            )

    monkeypatch.setattr("novel_dev.agents.context_agent.llm_factory", FakeFactory())
    plan = ChapterPlan(
        chapter_number=4,
        title="暗线初现",
        target_word_count=1667,
        beats=[
            BeatPlan(
                summary="陆照追查血海殿线索，在外门夜色里发现一枚陌生令符。",
                target_mood="紧张",
                key_entities=["陆照", "血海殿"],
            )
        ],
    )

    result = await agent._load_location_context(plan, "n_scene_fallback")

    assert result.current == "暗线初现"
    assert len(result.narrative) >= 30
    assert "陆照" in result.narrative
    assert "陌生令符" in result.narrative


@pytest.mark.asyncio
async def test_analyze_context_needs_falls_back_on_connection_error(
    async_session,
    monkeypatch,
):
    from novel_dev.repositories.spaceline_repo import SpacelineRepository

    await SpacelineRepository(async_session).create(
        location_id="loc_ctx_fb",
        name="青云宗",
        novel_id="n_ctx_fb",
    )

    async def fail_call(*args, **kwargs):
        raise RuntimeError("Connection error.")

    monkeypatch.setattr("novel_dev.agents.context_agent.call_and_parse_model", fail_call)

    agent = ContextAgent(async_session)
    plan = ChapterPlan(
        chapter_number=8,
        title="夜巡异兆",
        target_word_count=2200,
        beats=[
            BeatPlan(
                summary="陆照在青云宗夜巡时发现山门外血光一闪，怀疑有人借古镜引动旧阵。",
                target_mood="紧张",
                key_entities=["陆照", "青云宗", "古镜"],
                foreshadowings_to_embed=["旧阵异动"],
            )
        ],
    )

    result = await agent._analyze_context_needs(plan, "n_ctx_fb")

    assert result["locations"] == ["青云宗"]
    assert result["entities"] == ["陆照", "古镜"]
    assert result["time_range"] == {"start_tick": -2, "end_tick": 2}
    assert result["foreshadowing_keywords"] == ["旧阵异动"]


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


def test_context_agent_builds_writing_cards_from_chapter_plan(async_session):
    plan = ChapterPlan(
        chapter_number=1,
        title="第一章",
        target_word_count=2000,
        beats=[
            BeatPlan(
                summary="陆照为救妹妹潜入药库，却被执事发现；他必须在交出玉佩和暴露身世之间选择，结尾听见追兵逼近。",
                target_mood="紧张",
                key_entities=["陆照"],
            ),
            BeatPlan(
                summary="陆照利用玉佩残光脱身，但发现妹妹病情恶化，决定参加宗门试炼换药。",
                target_mood="压迫",
            ),
        ],
    )

    cards = ContextAgent(async_session)._build_writing_cards(plan)

    assert len(cards) == 2
    assert cards[0].objective
    assert cards[0].conflict
    assert cards[0].readability_contract
    assert cards[0].forbidden_future_events == ["陆照利用玉佩残光脱身"]


def test_context_agent_limits_scene_context_required_terms(async_session):
    agent = ContextAgent(async_session)
    plan = ChapterPlan(
        chapter_number=1,
        title="血月之下",
        target_word_count=1000,
        beats=[
            BeatPlan(
                summary="林照在青云宗外门试炼中觉醒血脉。",
                target_mood="紧张",
                key_entities=["林照", "青云宗", "长老会", "古血玉"],
            )
        ],
    )

    catalog = agent._build_scene_context_catalog(
        {
            "locations": [{"name": "青云宗", "narrative": "山门高耸"}],
            "entity_states": [
                {"name": "林照", "type": "character", "state": "紧张"},
                {"name": "长老会", "type": "faction", "state": "监视"},
                {"name": "古血玉", "type": "item", "state": "发烫"},
                {"name": "外门弟子", "type": "group", "state": "惊惧"},
            ],
            "timeline_events": [],
            "foreshadowings": [],
        },
        plan,
    )

    assert catalog["required_terms"] == ["青云宗", "林照", "古血玉"]


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
        assert "章节计划" in prompt
        assert "林风进入青云宗" in prompt
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
