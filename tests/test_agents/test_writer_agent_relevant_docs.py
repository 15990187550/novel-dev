import pytest
from unittest.mock import MagicMock

from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.schemas.context import ChapterContext, ChapterPlan, BeatPlan, LocationContext
from novel_dev.schemas.similar_document import SimilarDocument


def test_relevant_docs_text_block_in_prompt():
    context = ChapterContext(
        chapter_plan=ChapterPlan(
            chapter_number=1, title="第一章", target_word_count=3000,
            beats=[BeatPlan(summary="主角进入学院", target_mood="好奇", key_entities=["主角"])],
        ),
        style_profile={}, worldview_summary="", active_entities=[],
        location_context=LocationContext(current=""), timeline_events=[], pending_foreshadowings=[],
        relevant_documents=[
            SimilarDocument(doc_id="d1", doc_type="setting", title="星辰学院",
                content_preview="位于大陆中央的魔法学院", similarity_score=0.95),
        ],
    )
    agent = WriterAgent(MagicMock())
    beat = context.chapter_plan.beats[0]
    prompt = agent._build_beat_prompt(beat, context, "")
    assert "相关设定补充" in prompt
    assert "星辰学院" in prompt
    assert "位于大陆中央的魔法学院" in prompt


def test_relevant_docs_text_block_empty_when_no_docs():
    context = ChapterContext(
        chapter_plan=ChapterPlan(
            chapter_number=1, title="第一章", target_word_count=3000,
            beats=[BeatPlan(summary="主角进入学院", target_mood="好奇", key_entities=["主角"])],
        ),
        style_profile={}, worldview_summary="", active_entities=[],
        location_context=LocationContext(current=""), timeline_events=[], pending_foreshadowings=[],
        relevant_documents=[],
    )
    agent = WriterAgent(MagicMock())
    beat = context.chapter_plan.beats[0]
    prompt = agent._build_beat_prompt(beat, context, "")
    assert "相关设定补充" not in prompt
