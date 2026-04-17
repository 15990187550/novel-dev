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
async def test_advance_unsupported_phase(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_draft",
        phase=Phase.DRAFTING,
        checkpoint_data={},
        volume_id="v1",
        chapter_id="c1",
    )
    with pytest.raises(ValueError, match="Cannot auto-advance from"):
        await director.advance("novel_draft")
