"""Tests for WriterAgent root_cause_segment insertion at the top of chapter_context."""

import pytest


def test_insert_root_cause_segment_adds_at_top():
    from novel_dev.agents.writer_agent import WriterAgent

    base_context = {"chapter_plan": "plan", "existing_data": "x"}
    segment = "## 上轮根因建议\n- summary: beat 2 越界"
    result = WriterAgent._insert_root_cause_segment(base_context, segment)
    assert "root_cause_segment" in result
    assert result["root_cause_segment"] == segment
    keys = list(result.keys())
    assert keys[0] == "root_cause_segment"
    # Original keys must still be present
    assert result["chapter_plan"] == "plan"
    assert result["existing_data"] == "x"


def test_insert_root_cause_segment_empty_unchanged():
    from novel_dev.agents.writer_agent import WriterAgent

    base_context = {"chapter_plan": "plan"}
    result = WriterAgent._insert_root_cause_segment(base_context, "")
    assert result == base_context

    none_result = WriterAgent._insert_root_cause_segment(base_context, None)
    assert none_result == base_context


def test_whole_chapter_prompt_includes_root_cause_segment_at_top():
    """Verify the rendered prompt includes the root cause segment when provided."""
    from novel_dev.agents.writer_agent import WriterAgent
    from novel_dev.schemas.context import BeatPlan, ChapterContext, ChapterPlan, LocationContext

    agent = WriterAgent.__new__(WriterAgent)
    beat = BeatPlan(summary="主角在压力下做出选择。", target_mood="紧张", target_word_count=300)
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="第一章", target_word_count=800, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="测试场景"),
        timeline_events=[],
        pending_foreshadowings=[],
        story_contract={},
    )
    segment = "## 上轮根因建议\n- summary: beat 2 越界"

    prompt = agent._build_whole_chapter_context_message(context, rewrite_plan=None, root_cause_segment=segment)

    # Segment must appear
    assert "## 上轮根因建议" in prompt
    assert "beat 2 越界" in prompt
    # Segment must be at or near the top, before the rest of the prompt body
    assert prompt.index("## 上轮根因建议") < prompt.index("### 整章写作模式")


def test_whole_chapter_prompt_without_segment_unchanged():
    """Verify that absence of segment doesn't add anything to the prompt."""
    from novel_dev.agents.writer_agent import WriterAgent
    from novel_dev.schemas.context import BeatPlan, ChapterContext, ChapterPlan, LocationContext

    agent = WriterAgent.__new__(WriterAgent)
    beat = BeatPlan(summary="主角在压力下做出选择。", target_mood="紧张", target_word_count=300)
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="第一章", target_word_count=800, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="测试场景"),
        timeline_events=[],
        pending_foreshadowings=[],
        story_contract={},
    )

    prompt_no_segment = agent._build_whole_chapter_context_message(context)
    prompt_empty_segment = agent._build_whole_chapter_context_message(
        context, rewrite_plan=None, root_cause_segment=""
    )
    prompt_none_segment = agent._build_whole_chapter_context_message(
        context, rewrite_plan=None, root_cause_segment=None
    )

    assert "## 上轮根因建议" not in prompt_no_segment
    assert "## 上轮根因建议" not in prompt_empty_segment
    assert "## 上轮根因建议" not in prompt_none_segment
    # All three should be equal
    assert prompt_no_segment == prompt_empty_segment
    assert prompt_no_segment == prompt_none_segment


@pytest.mark.asyncio
async def test_write_standalone_passes_root_cause_segment_to_prompt(async_session):
    """Verify that write_standalone forwards a root_cause_segment to the rendered prompt."""
    from unittest.mock import AsyncMock, patch

    from novel_dev.agents.writer_agent import WriterAgent
    from novel_dev.schemas.context import BeatPlan, ChapterContext, ChapterPlan, LocationContext

    captured = {}

    agent = WriterAgent(async_session)
    beat = BeatPlan(summary="主角在压力下做出选择。", target_mood="紧张", target_word_count=300)
    context = ChapterContext(
        chapter_plan=ChapterPlan(chapter_number=1, title="第一章", target_word_count=800, beats=[beat]),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="测试场景"),
        timeline_events=[],
        pending_foreshadowings=[],
        story_contract={},
    )

    segment = "## 上轮根因建议\n- summary: beat 2 越界"

    async def fake_generate(self, *, novel_id, context, rewrite_plan, genre_template=None, root_cause_segment=""):
        captured["rewrite_plan"] = rewrite_plan
        captured["root_cause_segment"] = root_cause_segment
        # Build the user content to verify the segment is at the top
        user_content = self._build_whole_chapter_context_message(
            context, rewrite_plan=rewrite_plan, root_cause_segment=root_cause_segment
        )
        captured["user_content"] = user_content
        return "主角在压力下做出选择，阻力被具体行动化解，停点落在当场决策上。"

    # Patch at class level to record the user content
    with patch.object(
        WriterAgent, "_generate_whole_chapter", new=fake_generate
    ), patch.object(
        agent.chapter_repo, "update_text", new_callable=AsyncMock
    ), patch.object(
        agent.chapter_repo, "update_status", new_callable=AsyncMock
    ):
        await agent.write_standalone(
            "test-novel",
            context,
            "ch-root-cause-test",
            rewrite_plan=None,
            root_cause_segment=segment,
        )

    assert captured["root_cause_segment"] == segment
    assert "## 上轮根因建议" in captured["user_content"]
    assert "beat 2 越界" in captured["user_content"]
    # Segment must be at the top
    assert captured["user_content"].index("## 上轮根因建议") < captured["user_content"].index("### 整章写作模式")
