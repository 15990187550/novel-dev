import pytest

from novel_dev.agents.critic_agent import CriticAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.schemas.review import ScoreResult, DimensionScore


@pytest.mark.asyncio
async def test_review_pass_high_score(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")])
    context = ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_crit_pass",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump(), "draft_attempt_count": 0},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="a" * 100)

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
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=3000, beats=[])
    context = ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_crit_fail",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump(), "draft_attempt_count": 0},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")

    agent = CriticAgent(async_session)
    result = await agent.review("novel_crit_fail", "c1")
    assert result.overall < 70

    state = await director.resume("novel_crit_fail")
    assert state.current_phase == Phase.DRAFTING.value
    assert state.checkpoint_data["draft_attempt_count"] == 1


@pytest.mark.asyncio
async def test_review_red_line_rollback(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=3000, beats=[])
    context = ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_crit_red",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")

    agent = CriticAgent(async_session)
    agent._generate_score = lambda draft, ctx: ScoreResult(
        overall=75,
        dimensions=[
            DimensionScore(name="plot_tension", score=80, comment=""),
            DimensionScore(name="characterization", score=80, comment=""),
            DimensionScore(name="readability", score=80, comment=""),
            DimensionScore(name="consistency", score=20, comment=""),
            DimensionScore(name="humanity", score=80, comment=""),
        ],
        summary_feedback="red line",
    )
    result = await agent.review("novel_crit_red", "c1")
    assert result.overall == 75

    state = await director.resume("novel_crit_red")
    assert state.current_phase == Phase.DRAFTING.value


@pytest.mark.asyncio
async def test_review_max_attempts_exceeded(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=3000, beats=[])
    context = ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_crit_max",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump(), "draft_attempt_count": 2},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")

    agent = CriticAgent(async_session)
    with pytest.raises(RuntimeError, match="Max draft attempts exceeded"):
        await agent.review("novel_crit_max", "c1")
