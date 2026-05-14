import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.schemas.context import ChapterPlan, BeatPlan, ChapterContext, LocationContext
from novel_dev.repositories.chapter_repo import ChapterRepository


@pytest.mark.asyncio
async def test_advance_review_to_editing(async_session, mock_llm_factory):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="T", target_word_count=100, beats=[BeatPlan(summary="B1", target_mood="tense")])
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
        "novel_adv",
        phase=Phase.REVIEWING,
        checkpoint_data={"chapter_context": context.model_dump()},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await ChapterRepository(async_session).update_text("c1", raw_draft="a" * 100, polished_text="a" * 100)

    state = await director.advance("novel_adv")
    assert state.current_phase == Phase.EDITING.value

    state = await director.advance("novel_adv")
    assert state.current_phase == Phase.FAST_REVIEWING.value

    state = await director.advance("novel_adv")
    assert state.current_phase == Phase.LIBRARIAN.value


@pytest.mark.asyncio
async def test_advance_missing_novel(async_session):
    director = NovelDirector(session=async_session)
    with pytest.raises(ValueError, match="Novel state not found"):
        await director.advance("nonexistent")


@pytest.mark.asyncio
async def test_advance_drafting_missing_draft(async_session):
    director = NovelDirector(session=async_session)
    await ChapterRepository(async_session).create("c1", "v1", 1, "Test")
    await director.save_checkpoint(
        "novel_draft",
        phase=Phase.DRAFTING,
        checkpoint_data={},
        volume_id="v1",
        chapter_id="c1",
    )
    with pytest.raises(ValueError, match="Chapter draft not generated"):
        await director.advance("novel_draft")


@pytest.mark.asyncio
async def test_advance_context_preparation_rejects_stale_chapter_context(async_session):
    director = NovelDirector(session=async_session)
    current_plan = {
        "chapter_id": "c2",
        "chapter_number": 2,
        "title": "Current Chapter",
        "target_word_count": 1200,
        "beats": [{"summary": "beat2", "target_mood": "calm"}],
    }
    stale_context = ChapterContext(
        chapter_plan=ChapterPlan(
            chapter_number=1,
            title="Old Chapter",
            target_word_count=800,
            beats=[BeatPlan(summary="beat1", target_mood="tense")],
        ),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="旧地点"),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    await director.save_checkpoint(
        "novel_stale_ctx",
        phase=Phase.CONTEXT_PREPARATION,
        checkpoint_data={
            "current_chapter_plan": current_plan,
            "chapter_context": stale_context.model_dump(),
            "current_volume_plan": {"review_status": {"status": "accepted"}, "chapters": [current_plan]},
        },
        volume_id="v1",
        chapter_id="c2",
    )

    with pytest.raises(ValueError, match="Chapter context is stale"):
        await director.advance("novel_stale_ctx")
