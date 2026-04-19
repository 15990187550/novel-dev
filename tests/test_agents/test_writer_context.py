import pytest
from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.schemas.context import (
    ChapterContext, ChapterPlan, BeatPlan, LocationContext,
    EntityState, NarrativeRelay,
)


def _make_context(**overrides):
    defaults = dict(
        chapter_plan=ChapterPlan(
            chapter_number=1, title="Test", target_word_count=2000,
            beats=[BeatPlan(summary="开场", target_mood="压抑")],
        ),
        style_profile={"style_guide": "简洁有力"},
        worldview_summary="测试世界观",
        active_entities=[],
        location_context=LocationContext(current="默认"),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    defaults.update(overrides)
    return ChapterContext(**defaults)


class TestBuildSystemPrompt:
    def test_contains_style_and_rules(self):
        ctx = _make_context()
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_system_prompt(ctx, is_last=False)
        assert "简洁有力" in result
        assert "禁用词" in result

    def test_no_worldview_or_entities(self):
        ctx = _make_context(worldview_summary="这是一段很长的世界观描述" * 100)
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_system_prompt(ctx, is_last=False)
        assert "世界观描述" not in result

    def test_last_beat_has_hook_clause(self):
        ctx = _make_context()
        agent = WriterAgent.__new__(WriterAgent)
        result_last = agent._build_system_prompt(ctx, is_last=True)
        result_mid = agent._build_system_prompt(ctx, is_last=False)
        assert "章末钩子" in result_last
        assert "章末钩子" not in result_mid


class TestBuildContextMessage:
    def test_includes_chapter_plan(self):
        ctx = _make_context()
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[0], ctx, [], "", 0, 1, False
        )
        assert "Test" in result
        assert "开场" in result

    def test_includes_relay_history(self):
        ctx = _make_context()
        relay = NarrativeRelay(
            scene_state="秦风在山洞中",
            emotional_tone="紧张",
            new_info_revealed="发现密道",
            open_threads="密道通向哪里",
            next_beat_hook="火把快灭了",
        )
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[0], ctx, [relay], "", 1, 3, False
        )
        assert "秦风在山洞中" in result
        assert "火把快灭了" in result

    def test_includes_last_beat_text(self):
        ctx = _make_context()
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[0], ctx, [], "上一段正文内容", 1, 3, False
        )
        assert "上一段正文内容" in result

    def test_no_full_context_dump(self):
        ctx = _make_context(worldview_summary="很长的世界观" * 200)
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[0], ctx, [], "", 0, 1, False
        )
        assert "很长的世界观" not in result
        assert len(result) < 5000


class TestFallbackRetrieval:
    def test_matches_by_key_entities(self):
        ctx = _make_context(active_entities=[
            EntityState(entity_id="e1", name="秦风", type="character", current_state="武功高强的剑客"),
            EntityState(entity_id="e2", name="玉佩", type="item", current_state="古老的传家之宝"),
        ])
        beat = BeatPlan(summary="秦风拿起玉佩", target_mood="压抑", key_entities=["秦风"])
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._fallback_retrieval(beat, ctx)
        assert "秦风" in result
        assert "玉佩" not in result

    def test_empty_when_no_match(self):
        ctx = _make_context(active_entities=[
            EntityState(entity_id="e1", name="秦风", type="character", current_state="剑客"),
        ])
        beat = BeatPlan(summary="开场", target_mood="压抑", key_entities=["柳月"])
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._fallback_retrieval(beat, ctx)
        assert result == ""
