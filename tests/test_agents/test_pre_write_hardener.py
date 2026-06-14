import logging
import pytest
from novel_dev.schemas.context import ChapterContext, ChapterPlan, BeatPlan, LocationContext
from novel_dev.schemas.quality import BeatBoundaryCard
from novel_dev.agents.writer_agent import WriterAgent


@pytest.mark.asyncio
async def test_build_context_includes_beat_boundary_cards(caplog):
    plan = ChapterPlan(
        chapter_number=1,
        target_word_count=3000,
        beats=[
            BeatPlan(summary="陆照走在路上", target_mood="紧张"),
        ],
        beat_boundary_cards=[
            BeatBoundaryCard(beat_index=0, must_cover=["陆照"], forbidden_materials=["追兵"]),
        ],
    )
    context = ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    agent = WriterAgent(None, None)
    with caplog.at_level(logging.INFO, logger="novel_dev.agents.writer_agent"):
        prompt = agent._build_whole_chapter_context_message(context, None)
    assert "#### beat 0" in prompt
    assert "陆照" in prompt
    assert "追兵" in prompt
    # Check beat_cards_count via caplog.records (extra fields are in records, not text)
    whole_chapter_records = [r for r in caplog.records if r.message == "whole_chapter_prompt_built"]
    assert whole_chapter_records, f"expected whole_chapter_prompt_built in caplog.records, got: {[r.message for r in caplog.records]}"
    record = whole_chapter_records[0]
    assert hasattr(record, "beat_cards_count"), f"expected beat_cards_count in record.extra, got: {dir(record)}"
    assert record.beat_cards_count == 1
