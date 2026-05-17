from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.critic_agent import CriticAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.schemas.review import ScoreResult, DimensionScore
from novel_dev.llm.models import LLMResponse


def _make_context():
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")])
    return ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )


@pytest.mark.asyncio
async def test_review_pass_high_score(async_session):
    director = NovelDirector(session=async_session)
    context = _make_context()
    await director.save_checkpoint(
        "novel_crit_pass",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump(), "draft_attempt_count": 0},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="a" * 100)

    score_result = ScoreResult(
        overall=88,
        dimensions=[
            DimensionScore(name="plot_tension", score=85, comment="节奏稳定"),
            DimensionScore(name="characterization", score=85, comment="人物行为一致"),
            DimensionScore(name="readability", score=85, comment="可读性良好"),
            DimensionScore(name="consistency", score=85, comment="设定无冲突"),
            DimensionScore(name="humanity", score=85, comment="自然流畅"),
        ],
        summary_feedback="整体良好",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=score_result.model_dump_json()),
        LLMResponse(text='[{"beat_index": 0, "scores": {"plot_tension": 80, "humanity": 80}}]'),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        result = await agent.review("novel_crit_pass", "c1")

    assert result.overall >= 70

    ch = await ChapterRepository(async_session).get_by_id("c1")
    assert ch.score_breakdown == {
        d.name: {"score": d.score, "comment": d.comment} for d in result.dimensions
    }

    state = await director.resume("novel_crit_pass")
    assert state.current_phase == Phase.EDITING.value


@pytest.mark.asyncio
async def test_generate_score_prompt_requires_flagging_english_terms(async_session):
    score_result = ScoreResult(
        overall=88,
        dimensions=[
            DimensionScore(name="plot_tension", score=85, comment=""),
            DimensionScore(name="characterization", score=85, comment=""),
            DimensionScore(name="readability", score=85, comment=""),
            DimensionScore(name="consistency", score=85, comment=""),
            DimensionScore(name="humanity", score=85, comment=""),
        ],
        summary_feedback="ok",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=score_result.model_dump_json())

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        await agent._generate_score("他想按掉 snooze 再睡。", _make_context().model_dump(), "novel_crit_lang")

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "自然中文表达" in prompt
    assert "读者体验" in prompt
    assert "snooze" in prompt


@pytest.mark.asyncio
async def test_generate_score_prompt_flags_specific_ai_flavor_patterns(async_session):
    score_result = ScoreResult(
        overall=88,
        dimensions=[
            DimensionScore(name="plot_tension", score=85, comment=""),
            DimensionScore(name="characterization", score=85, comment=""),
            DimensionScore(name="readability", score=85, comment=""),
            DimensionScore(name="consistency", score=85, comment=""),
            DimensionScore(name="humanity", score=85, comment=""),
            DimensionScore(name="hook_strength", score=85, comment=""),
        ],
        summary_feedback="ok",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=score_result.model_dump_json())

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        await agent._generate_score(
            "光像潮水，意识深处又像万花筒，仿佛有什么存在从古经里醒来。",
            _make_context().model_dump(),
            "novel_crit_ai_flavor",
        )

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "读者体验" in prompt
    assert "相信人物" in prompt
    assert "愿意继续读" in prompt
    assert "正向改写目标" in prompt
    assert "比喻密度" in prompt
    assert "抽象玄幻词" in prompt
    assert "感官平均用力" in prompt
    assert "模板化奇遇" in prompt
    assert "现代吐槽突兀" in prompt
    assert "只保留最有辨识度的一处" in prompt


@pytest.mark.asyncio
async def test_generate_score_prompt_requests_source_stage_attribution(async_session):
    score_result = ScoreResult(
        overall=72,
        dimensions=[
            DimensionScore(name="plot_tension", score=72, comment=""),
            DimensionScore(name="characterization", score=75, comment=""),
            DimensionScore(name="readability", score=75, comment=""),
            DimensionScore(name="consistency", score=70, comment=""),
            DimensionScore(name="humanity", score=75, comment=""),
            DimensionScore(name="hook_strength", score=75, comment=""),
        ],
        summary_feedback="存在来源不清的新增线索。",
        per_dim_issues=[],
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=score_result.model_dump_json())

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        await agent._generate_score("林照忽然发现银线袖口。", _make_context().model_dump(), "n_source_stage")

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "source_stage" in prompt
    assert "setting_generation / brainstorm / volume_plan / drafting / editing" in prompt
    assert "问题来自哪个流程阶段" in prompt


@pytest.mark.asyncio
async def test_review_fail_low_score(async_session):
    director = NovelDirector(session=async_session)
    context = _make_context()
    await director.save_checkpoint(
        "novel_crit_fail",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump(), "draft_attempt_count": 0},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")

    score_result = ScoreResult(
        overall=55,
        dimensions=[
            DimensionScore(name="plot_tension", score=50, comment="节奏拖沓"),
            DimensionScore(name="characterization", score=50, comment="扁平"),
            DimensionScore(name="readability", score=50, comment="晦涩"),
            DimensionScore(name="consistency", score=60, comment="有小冲突"),
            DimensionScore(name="humanity", score=60, comment="稍生硬"),
        ],
        summary_feedback="需要重写",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=score_result.model_dump_json()),
        LLMResponse(text='[{"beat_index": 0, "scores": {"plot_tension": 50, "humanity": 50}}]'),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        result = await agent.review("novel_crit_fail", "c1")

    assert result.overall < 70

    state = await director.resume("novel_crit_fail")
    assert state.current_phase == Phase.DRAFTING.value
    assert state.checkpoint_data["draft_attempt_count"] == 1
    assert state.checkpoint_data["drafting_progress"] == {
        "beat_index": 0,
        "total_beats": 1,
        "current_word_count": 0,
    }
    assert "relay_history" not in state.checkpoint_data
    assert state.checkpoint_data["draft_rewrite_plan"]["rewrite_all"] is True
    assert state.checkpoint_data["draft_rewrite_plan"]["beat_issues"][0]["issues"]


def test_rewrite_plan_keeps_global_issues_separate_from_beat_issues():
    score_result = ScoreResult(
        overall=55,
        dimensions=[
            DimensionScore(name="plot_tension", score=50, comment="节奏拖沓"),
            DimensionScore(name="characterization", score=70, comment="尚可"),
            DimensionScore(name="readability", score=70, comment="尚可"),
            DimensionScore(name="consistency", score=70, comment="尚可"),
            DimensionScore(name="humanity", score=70, comment="尚可"),
        ],
        summary_feedback="整体需要重写",
        per_dim_issues=[
            {"dim": "plot_tension", "problem": "全章冲突不足", "suggestion": "提高主线压力"},
        ],
    )
    beat_scores = [
        {
            "beat_index": 1,
            "scores": {"humanity": 50},
            "issues": [{"dim": "humanity", "problem": "第二节拍对白生硬", "suggestion": "改成动作带情绪"}],
        }
    ]

    plan = CriticAgent.__new__(CriticAgent)._build_draft_rewrite_plan(
        score_result,
        beat_scores,
        beat_count=3,
        rewrite_all=True,
    )

    assert plan["global_issues"][0]["problem"] == "全章冲突不足"
    assert plan["beat_issues"][0]["issues"] == []
    assert plan["beat_issues"][1]["issues"][0]["problem"] == "第二节拍对白生硬"


@pytest.mark.asyncio
async def test_review_red_line_rollback(async_session):
    director = NovelDirector(session=async_session)
    context = _make_context()
    await director.save_checkpoint(
        "novel_crit_red",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")

    score_result = ScoreResult(
        overall=75,
        dimensions=[
            DimensionScore(name="plot_tension", score=80, comment=""),
            DimensionScore(name="characterization", score=80, comment=""),
            DimensionScore(name="readability", score=80, comment=""),
            DimensionScore(name="consistency", score=20, comment="严重冲突"),
            DimensionScore(name="humanity", score=80, comment=""),
        ],
        summary_feedback="red line",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=score_result.model_dump_json()),
        LLMResponse(text='[{"beat_index": 0, "scores": {"plot_tension": 80, "humanity": 80}}]'),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        result = await agent.review("novel_crit_red", "c1")

    assert result.overall == 75

    state = await director.resume("novel_crit_red")
    assert state.current_phase == Phase.DRAFTING.value


@pytest.mark.asyncio
async def test_review_max_attempts_exceeded(async_session):
    director = NovelDirector(session=async_session)
    context = _make_context()
    await director.save_checkpoint(
        "novel_crit_max",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump(), "draft_attempt_count": 2},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")

    score_result = ScoreResult(
        overall=55,
        dimensions=[DimensionScore(name="plot_tension", score=50, comment="") for _ in range(5)],
        summary_feedback="差",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=score_result.model_dump_json()),
        LLMResponse(text='[]'),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        with pytest.raises(RuntimeError, match="Max draft attempts exceeded"):
            await agent.review("novel_crit_max", "c1")


@pytest.mark.asyncio
async def test_review_max_attempts_forces_editing_for_real_longform(async_session):
    director = NovelDirector(session=async_session)
    context = _make_context()
    await director.save_checkpoint(
        "novel_crit_max_longform",
        phase=Phase.REVIEWING,
        checkpoint_data={
            "chapter_context": context.model_dump(),
            "draft_attempt_count": 2,
            "acceptance_scope": "real-longform-volume1",
        },
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")

    score_result = ScoreResult(
        overall=55,
        dimensions=[DimensionScore(name="plot_tension", score=50, comment="") for _ in range(5)],
        summary_feedback="差",
    )
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=score_result.model_dump_json()),
        LLMResponse(text='[]'),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        result = await agent.review("novel_crit_max_longform", "c1")

    assert result.overall == 55
    state = await director.resume("novel_crit_max_longform")
    assert state.current_phase == Phase.EDITING.value
    assert state.checkpoint_data["draft_attempt_count"] == 3
    assert state.checkpoint_data["critic_forced_editing"]["overall"] == 55
    assert state.checkpoint_data["draft_rewrite_plan"]["rewrite_all"] is True
