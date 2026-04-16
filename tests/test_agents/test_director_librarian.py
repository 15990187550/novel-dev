import pytest
from unittest.mock import AsyncMock, patch

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.schemas.context import ChapterPlan, BeatPlan


@pytest.mark.asyncio
async def test_director_librarian_to_completed(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="Ch1", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")])
    await director.save_checkpoint(
        "n_dir",
        phase=Phase.LIBRARIAN,
        checkpoint_data={"current_volume_plan": {"chapters": [plan.model_dump()]}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1")
    await ChapterRepository(async_session).update_text("c1", polished_text="abc")

    with patch("novel_dev.agents.librarian.LibrarianAgent._call_llm", new_callable=AsyncMock, return_value='{}'):
        state = await director._run_librarian(await director.resume("n_dir"))

    assert state.current_phase == Phase.COMPLETED.value
    ch = await ChapterRepository(async_session).get_by_id("c1")
    assert ch.status == "archived"


@pytest.mark.asyncio
async def test_director_continue_to_next_chapter(async_session):
    director = NovelDirector(session=async_session)
    plans = [
        ChapterPlan(chapter_number=1, title="Ch1", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")]).model_dump(),
        ChapterPlan(chapter_number=2, title="Ch2", target_word_count=3000, beats=[BeatPlan(summary="B2", target_mood="calm")]).model_dump(),
    ]
    plans[0]["chapter_id"] = "c1"
    plans[1]["chapter_id"] = "c2"
    await director.save_checkpoint(
        "n_next",
        phase=Phase.COMPLETED,
        checkpoint_data={"current_volume_plan": {"chapters": plans}},
        volume_id="v1",
        chapter_id="c1",
    )
    state = await director._continue_to_next_chapter("n_next")
    assert state.current_phase == Phase.CONTEXT_PREPARATION.value
    assert state.current_chapter_id == "c2"


@pytest.mark.asyncio
async def test_director_last_chapter_to_volume_planning(async_session):
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(chapter_number=1, title="Ch1", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")]).model_dump()
    plan["chapter_id"] = "c1"
    await director.save_checkpoint(
        "n_last",
        phase=Phase.COMPLETED,
        checkpoint_data={"current_volume_plan": {"chapters": [plan]}, "archive_stats": {"avg_word_count": 2500}},
        volume_id="vol_1",
        chapter_id="c1",
    )
    state = await director._continue_to_next_chapter("n_last")
    assert state.current_phase == Phase.VOLUME_PLANNING.value
    assert state.current_volume_id == "vol_2"
    assert "pending_volume_plans" in state.checkpoint_data


@pytest.mark.asyncio
async def test_director_librarian_both_extractions_fail(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "n_fail",
        phase=Phase.LIBRARIAN,
        checkpoint_data={},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1")
    await ChapterRepository(async_session).update_text("c1", polished_text="abc")

    with patch("novel_dev.agents.librarian.LibrarianAgent._call_llm", new_callable=AsyncMock, side_effect=Exception("LLM down")):
        with patch("novel_dev.agents.librarian.LibrarianAgent.fallback_extract", side_effect=Exception("fallback also fails")):
            with pytest.raises(RuntimeError):
                await director._run_librarian(await director.resume("n_fail"))

    state = await NovelStateRepository(async_session).get_state("n_fail")
    assert state.current_phase == Phase.LIBRARIAN.value
    assert "librarian_error" in state.checkpoint_data
