import pytest
from unittest.mock import AsyncMock, patch

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.schemas.context import ChapterPlan, BeatPlan
from novel_dev.schemas.librarian import ExtractionResult


@pytest.mark.asyncio
async def test_director_librarian_to_completed(async_session, tmp_path, monkeypatch):
    monkeypatch.setattr("novel_dev.agents.director.settings.data_dir", str(tmp_path))
    director = NovelDirector(session=async_session)
    plans = [
        ChapterPlan(chapter_number=1, title="Ch1", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")]).model_dump(),
        ChapterPlan(chapter_number=2, title="Ch2", target_word_count=3000, beats=[BeatPlan(summary="B2", target_mood="calm")]).model_dump(),
    ]
    plans[0]["chapter_id"] = "c1"
    plans[1]["chapter_id"] = "c2"
    await director.save_checkpoint(
        "n_dir",
        phase=Phase.LIBRARIAN,
        checkpoint_data={"current_volume_plan": {"chapters": plans}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n_dir")
    await ChapterRepository(async_session).update_text("c1", polished_text="abc")

    with patch("novel_dev.agents.librarian.call_and_parse_model", new_callable=AsyncMock, return_value=ExtractionResult()):
        state = await director._run_librarian(await director.resume("n_dir"))

    assert state.current_phase == Phase.CONTEXT_PREPARATION.value
    ch = await ChapterRepository(async_session).get_by_id("c1")
    assert ch.status == "archived"
    assert (
        tmp_path.resolve()
        / "novels"
        / "n_dir"
        / "archive"
        / "v1"
        / "c1.md"
    ).exists()


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
async def test_director_continue_to_next_chapter_clears_chapter_scoped_checkpoint(async_session):
    director = NovelDirector(session=async_session)
    plans = [
        ChapterPlan(chapter_number=1, title="Ch1", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")]).model_dump(),
        ChapterPlan(chapter_number=2, title="Ch2", target_word_count=3000, beats=[BeatPlan(summary="B2", target_mood="calm")]).model_dump(),
    ]
    plans[0]["chapter_id"] = "c1"
    plans[1]["chapter_id"] = "c2"
    await director.save_checkpoint(
        "n_next_clear",
        phase=Phase.COMPLETED,
        checkpoint_data={
            "current_volume_plan": {"chapters": plans},
            "chapter_context": {"chapter_plan": {"title": "Ch1", "chapter_number": 1, "target_word_count": 3000, "beats": [{"summary": "B1", "target_mood": "tense"}]}},
            "drafting_progress": {"beat_index": 3},
            "relay_history": [{"scene_state": "old"}],
            "draft_metadata": {"total_words": 999},
        },
        volume_id="v1",
        chapter_id="c1",
    )

    state = await director._continue_to_next_chapter("n_next_clear")

    assert state.current_phase == Phase.CONTEXT_PREPARATION.value
    assert state.current_chapter_id == "c2"
    assert "chapter_context" not in state.checkpoint_data
    assert "drafting_progress" not in state.checkpoint_data
    assert "relay_history" not in state.checkpoint_data
    assert "draft_metadata" not in state.checkpoint_data


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
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n_fail")
    await ChapterRepository(async_session).update_text("c1", polished_text="abc")

    with patch("novel_dev.agents.librarian.call_and_parse_model", new_callable=AsyncMock, side_effect=Exception("LLM down")):
        with patch("novel_dev.agents.librarian.LibrarianAgent.fallback_extract", side_effect=Exception("fallback also fails")):
            with pytest.raises(RuntimeError):
                await director._run_librarian(await director.resume("n_fail"))

    state = await NovelStateRepository(async_session).get_state("n_fail")
    assert state.current_phase == Phase.LIBRARIAN.value
    assert "librarian_error" in state.checkpoint_data


@pytest.mark.asyncio
async def test_director_librarian_fallback_success(async_session, tmp_path, monkeypatch):
    monkeypatch.setattr("novel_dev.agents.director.settings.data_dir", str(tmp_path))
    director = NovelDirector(session=async_session)
    plans = [
        ChapterPlan(chapter_number=1, title="Ch1", target_word_count=3000, beats=[BeatPlan(summary="B1", target_mood="tense")]).model_dump(),
        ChapterPlan(chapter_number=2, title="Ch2", target_word_count=3000, beats=[BeatPlan(summary="B2", target_mood="calm")]).model_dump(),
    ]
    plans[0]["chapter_id"] = "c1"
    plans[1]["chapter_id"] = "c2"
    await director.save_checkpoint(
        "n_fallback",
        phase=Phase.LIBRARIAN,
        checkpoint_data={"current_volume_plan": {"chapters": plans}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n_fallback")
    await ChapterRepository(async_session).update_text("c1", polished_text="abc")

    with patch("novel_dev.agents.librarian.call_and_parse_model", new_callable=AsyncMock, side_effect=Exception("LLM down")):
        state = await director._run_librarian(await director.resume("n_fallback"))

    assert state.current_phase == Phase.CONTEXT_PREPARATION.value
    ch = await ChapterRepository(async_session).get_by_id("c1")
    assert ch.status == "archived"
    assert (
        tmp_path.resolve()
        / "novels"
        / "n_fallback"
        / "archive"
        / "v1"
        / "c1.md"
    ).exists()


@pytest.mark.asyncio
async def test_director_librarian_fallback_on_extract_timeout(async_session, tmp_path, monkeypatch):
    monkeypatch.setattr("novel_dev.agents.director.settings.data_dir", str(tmp_path))
    director = NovelDirector(session=async_session)
    plan = ChapterPlan(
        chapter_number=1,
        title="Ch1",
        target_word_count=3000,
        beats=[BeatPlan(summary="B1", target_mood="tense")],
    ).model_dump()
    plan["chapter_id"] = "c1"
    await director.save_checkpoint(
        "n_timeout",
        phase=Phase.LIBRARIAN,
        checkpoint_data={"current_volume_plan": {"chapters": [plan]}},
        volume_id="v1",
        chapter_id="c1",
    )
    await ChapterRepository(async_session).create("c1", "v1", 1, "Ch1", novel_id="n_timeout")
    await ChapterRepository(async_session).update_text("c1", polished_text="三天后，Lin Feng 来到 Qingyun City。")

    with patch(
        "novel_dev.agents.librarian.call_and_parse_model",
        new_callable=AsyncMock,
        side_effect=TimeoutError("LibrarianAgent/extract timed out after 120s waiting for LLM response"),
    ):
        state = await director._run_librarian(await director.resume("n_timeout"))

    assert state.current_phase == Phase.VOLUME_PLANNING.value
    ch = await ChapterRepository(async_session).get_by_id("c1")
    assert ch.status == "archived"
