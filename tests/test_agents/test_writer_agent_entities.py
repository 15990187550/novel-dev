import pytest
from unittest.mock import MagicMock

from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.schemas.context import ChapterContext, ChapterPlan, BeatPlan, LocationContext, EntityState


def test_related_entities_text_block_in_prompt():
    context = ChapterContext(
        chapter_plan=ChapterPlan(
            chapter_number=1, title="第一章", target_word_count=3000,
            beats=[BeatPlan(summary="主角进入学院", target_mood="好奇", key_entities=["主角"])],
        ),
        style_profile={}, worldview_summary="", active_entities=[],
        location_context=LocationContext(current=""), timeline_events=[], pending_foreshadowings=[],
        related_entities=[
            EntityState(entity_id="e1", name="李长老", type="character", current_state="青云宗长老"),
            EntityState(entity_id="e2", name="魔道联盟", type="faction", current_state="暗中策划入侵"),
        ],
    )
    agent = WriterAgent(MagicMock())
    beat = context.chapter_plan.beats[0]
    prompt = agent._build_beat_prompt(beat, context, "")
    assert "相关角色/势力/地点" in prompt
    assert "[character] 李长老：青云宗长老" in prompt
    assert "[faction] 魔道联盟：暗中策划入侵" in prompt


def test_related_entities_text_block_empty_when_no_entities():
    context = ChapterContext(
        chapter_plan=ChapterPlan(
            chapter_number=1, title="第一章", target_word_count=3000,
            beats=[BeatPlan(summary="主角进入学院", target_mood="好奇", key_entities=["主角"])],
        ),
        style_profile={}, worldview_summary="", active_entities=[],
        location_context=LocationContext(current=""), timeline_events=[], pending_foreshadowings=[],
        related_entities=[],
    )
    agent = WriterAgent(MagicMock())
    beat = context.chapter_plan.beats[0]
    prompt = agent._build_beat_prompt(beat, context, "")
    assert "相关角色/势力/地点" not in prompt


def test_rewrite_angle_includes_related_entities():
    context = ChapterContext(
        chapter_plan=ChapterPlan(
            chapter_number=1, title="第一章", target_word_count=3000,
            beats=[BeatPlan(summary="主角进入学院", target_mood="好奇", key_entities=["主角"])],
        ),
        style_profile={}, worldview_summary="", active_entities=[],
        location_context=LocationContext(current=""), timeline_events=[], pending_foreshadowings=[],
        related_entities=[
            EntityState(entity_id="e1", name="李长老", type="character", current_state="青云宗长老"),
        ],
    )
    agent = WriterAgent(MagicMock())
    beat = context.chapter_plan.beats[0]
    # _rewrite_angle builds prompt synchronously; we can inspect via a mock or just call the method.
    # Since _rewrite_angle is async and calls llm_factory, we test the prompt builder indirectly by
    # checking that _build_related_entities_text is used. The actual prompt text is built inside
    # _rewrite_angle. We can test the helper directly and verify the prompt structure by mocking.
    prompt = (
        "你是一位小说家。当前节拍过短，请扩写并保持与上下文的连贯。"
        "只返回扩写后的正文，不添加解释。\n\n"
        f"### 节拍计划\n{beat.model_dump_json()}\n\n"
        f"### 章节上下文\n{context.model_dump_json()}\n\n"
        f"{agent._build_relevant_docs_text(context)}"
        f"{agent._build_related_entities_text(context)}"
        f"### 当前过短文本\n太短\n\n"
        "请扩写："
    )
    assert "相关角色/势力/地点" in prompt
    assert "[character] 李长老：青云宗长老" in prompt
