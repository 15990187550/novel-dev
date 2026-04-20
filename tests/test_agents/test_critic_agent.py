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
