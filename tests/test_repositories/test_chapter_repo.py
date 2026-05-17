import pytest

from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.schemas.outline import VolumeBeat
from novel_dev.schemas.context import BeatPlan


@pytest.mark.asyncio
async def test_chapter_crud(async_session):
    repo = ChapterRepository(async_session)
    ch = await repo.create("ch_001", "vol_1", 1, title="Prologue")
    assert ch.status == "pending"
    await repo.update_text("ch_001", raw_draft="draft text", polished_text="final text")
    updated = await repo.get_by_id("ch_001")
    assert updated.polished_text == "final text"


@pytest.mark.asyncio
async def test_novel_state_checkpoint(async_session):
    repo = NovelStateRepository(async_session)
    await repo.save_checkpoint(
        "novel_1",
        current_phase="writing_chapter_1_draft",
        checkpoint_data={"retry_count": 0},
        current_volume_id="vol_1",
        current_chapter_id="ch_1",
    )
    state = await repo.get_state("novel_1")
    assert state.current_phase == "writing_chapter_1_draft"


@pytest.mark.asyncio
async def test_get_previous_chapter(async_session):
    repo = ChapterRepository(async_session)
    await repo.create("c1", "v1", 1, "First")
    await repo.create("c2", "v1", 2, "Second")
    prev = await repo.get_previous_chapter("v1", 2)
    assert prev is not None
    assert prev.chapter_number == 1


@pytest.mark.asyncio
async def test_update_fast_review(async_session):
    repo = ChapterRepository(async_session)
    await repo.create("c3", "v1", 3, "Third")
    await repo.update_fast_review("c3", 92, {"word_count_ok": True})
    ch = await repo.get_by_id("c3")
    assert ch.fast_review_score == 92
    assert ch.fast_review_feedback["word_count_ok"] is True


@pytest.mark.asyncio
async def test_update_quality_gate_fields(async_session):
    repo = ChapterRepository(async_session)
    await repo.create("c_quality", "v1", 4, "Quality")

    await repo.update_quality_gate(
        "c_quality",
        quality_status="warn",
        quality_reasons={
            "warning_items": [{"code": "word_count_drift", "message": "字数偏离目标"}],
            "blocking_items": [],
        },
        final_review_score=76,
        final_review_feedback={"summary_feedback": "成稿可用但偏长"},
        draft_review_score=62,
        draft_review_feedback={"summary_feedback": "草稿问题较多"},
        world_state_ingested=False,
    )

    ch = await repo.get_by_id("c_quality")
    assert ch.quality_status == "warn"
    assert ch.final_review_score == 76
    assert ch.final_review_feedback["summary_feedback"] == "成稿可用但偏长"
    assert ch.draft_review_score == 62
    assert ch.quality_reasons["warning_items"][0]["code"] == "word_count_drift"
    assert ch.world_state_ingested is False


@pytest.mark.asyncio
async def test_update_text_clears_stale_quality_gate_on_new_polished_text(async_session):
    repo = ChapterRepository(async_session)
    await repo.create("c_polish_reset", "v1", 5, "Rewrite")
    await repo.update_text("c_polish_reset", raw_draft="旧草稿", polished_text="旧成稿")
    await repo.update_fast_review("c_polish_reset", 50, {"notes": ["old"]})
    await repo.update_quality_gate(
        "c_polish_reset",
        quality_status="block",
        quality_reasons={"status": "block", "blocking_items": [{"code": "beat_cohesion"}]},
        final_review_score=68,
        final_review_feedback={"summary_feedback": "旧问题"},
        world_state_ingested=True,
    )

    await repo.update_text("c_polish_reset", polished_text="新成稿")

    ch = await repo.get_by_id("c_polish_reset")
    assert ch.polished_text == "新成稿"
    assert ch.quality_status == "unchecked"
    assert ch.quality_reasons is None
    assert ch.fast_review_score is None
    assert ch.fast_review_feedback is None
    assert ch.final_review_score is None
    assert ch.final_review_feedback is None
    assert ch.world_state_ingested is False


@pytest.mark.asyncio
async def test_update_text_clears_stale_polished_and_gate_on_new_raw_draft(async_session):
    repo = ChapterRepository(async_session)
    await repo.create("c_draft_reset", "v1", 6, "Rewrite Draft")
    await repo.update_text("c_draft_reset", raw_draft="旧草稿", polished_text="旧成稿")
    await repo.update_quality_gate(
        "c_draft_reset",
        quality_status="block",
        quality_reasons={"status": "block", "blocking_items": [{"code": "consistency"}]},
        final_review_score=70,
        final_review_feedback={"summary_feedback": "旧成稿问题"},
        world_state_ingested=True,
    )

    await repo.update_text("c_draft_reset", raw_draft="新草稿")

    ch = await repo.get_by_id("c_draft_reset")
    assert ch.raw_draft == "新草稿"
    assert ch.polished_text is None
    assert ch.quality_status == "unchecked"
    assert ch.quality_reasons is None
    assert ch.final_review_score is None
    assert ch.final_review_feedback is None
    assert ch.world_state_ingested is False


@pytest.mark.asyncio
async def test_ensure_from_plan_creates_chapter_record(async_session):
    repo = ChapterRepository(async_session)
    plan = VolumeBeat(
        chapter_id="ch_plan_1",
        chapter_number=1,
        title="Plan Chapter",
        summary="章摘要",
        target_word_count=3000,
        target_mood="tense",
        beats=[BeatPlan(summary="B1", target_mood="tense")],
    )

    chapter = await repo.ensure_from_plan("novel_plan", "vol_plan", plan)

    assert chapter.id == "ch_plan_1"
    assert chapter.novel_id == "novel_plan"
    assert chapter.volume_id == "vol_plan"
    assert chapter.chapter_number == 1
    assert chapter.title == "Plan Chapter"
    assert chapter.status == "pending"


@pytest.mark.asyncio
async def test_ensure_from_plan_updates_plan_fields_and_preserves_content(async_session):
    repo = ChapterRepository(async_session)
    plan = {
        "chapter_id": "ch_plan_2",
        "chapter_number": 2,
        "title": "Original Plan Title",
        "target_word_count": 3000,
        "beats": [{"summary": "B1", "target_mood": "tense"}],
    }
    await repo.ensure_from_plan("novel_plan", "vol_plan", plan)
    await repo.update_text("ch_plan_2", raw_draft="draft", polished_text="polished")
    await repo.update_scores("ch_plan_2", 88, {"plot": {"score": 88}}, {"summary": "ok"})
    await repo.update_status("ch_plan_2", "archived")

    updated = await repo.ensure_from_plan(
        "novel_plan",
        "vol_plan",
        {**plan, "title": "Changed Plan Title", "chapter_number": 99},
    )

    assert updated.chapter_number == 99
    assert updated.title == "Changed Plan Title"
    assert updated.raw_draft == "draft"
    assert updated.polished_text == "polished"
    assert updated.score_overall == 88
    assert updated.status == "archived"


@pytest.mark.asyncio
async def test_ensure_from_plan_does_not_cross_volume_when_ids_are_unique(async_session):
    repo = ChapterRepository(async_session)

    first = await repo.ensure_from_plan(
        "novel_plan",
        "vol_1",
        {"chapter_id": "vol_1_ch_1", "chapter_number": 1, "title": "第一卷第一章"},
    )
    second = await repo.ensure_from_plan(
        "novel_plan",
        "vol_2",
        {"chapter_id": "vol_2_ch_1", "chapter_number": 1, "title": "第二卷第一章"},
    )

    assert first.id == "vol_1_ch_1"
    assert second.id == "vol_2_ch_1"
    assert first.volume_id == "vol_1"
    assert second.volume_id == "vol_2"
    assert [chapter.id for chapter in await repo.list_by_volume("vol_1")] == ["vol_1_ch_1"]
    assert [chapter.id for chapter in await repo.list_by_volume("vol_2")] == ["vol_2_ch_1"]
