"""Tests for ChapterPlan.archetype + BeatPlan.mood_phase — Task 20 Phase 4.

Covers:
- ChapterPlan accepts an `archetype` field (chapter type, e.g. action / climax)
- BeatPlan accepts an optional `mood_phase` field (per-beat mood)
- Default values are safe / backward compatible
- Volume planner's batch expansion prompt asks the LLM for `archetype`
  (chapter-level) and `mood_phase` (per-beat)
"""

from __future__ import annotations

import pytest


def test_chapter_plan_has_archetype_field():
    from novel_dev.schemas.context import ChapterPlan

    cp = ChapterPlan(
        chapter_number=1,
        title="陆照逃出",
        target_word_count=3000,
        beats=[],
        archetype="action",
    )
    assert cp.archetype == "action"


def test_chapter_plan_archetype_defaults_to_empty_string():
    from novel_dev.schemas.context import ChapterPlan

    cp = ChapterPlan(
        chapter_number=2,
        title="过渡",
        target_word_count=3000,
        beats=[],
    )
    # Backward compat: missing archetype must not break construction
    assert cp.archetype == ""


def test_beat_plan_has_optional_mood_phase():
    from novel_dev.schemas.context import BeatPlan

    # Provided value is preserved as-is
    bp = BeatPlan(beat_index=0, summary="...", target_mood="tense", mood_phase="climax")
    assert bp.mood_phase == "climax"

    # Omitted value must remain None (Optional[str] = None contract), NOT be
    # silently coerced to "" by the text-coercion validator. Downstream code
    # (Task 21) keys off None to mean "not set" vs "" for "explicitly empty".
    bp_default = BeatPlan(beat_index=1, summary="...", target_mood="calm")
    assert bp_default.mood_phase is None


def test_beat_plan_mood_phase_defaults_to_none():
    from novel_dev.schemas.context import BeatPlan

    bp2 = BeatPlan(beat_index=1, summary="...", target_mood="calm")
    assert bp2.mood_phase is None


def test_volume_beat_propagates_archetype_and_mood_phase():
    from novel_dev.schemas.context import BeatPlan
    from novel_dev.schemas.outline import VolumeBeat

    chapter = VolumeBeat(
        chapter_id="vol_1_ch_1",
        chapter_number=1,
        title="初战立威",
        summary="主角在考核中一鸣惊人。",
        target_word_count=3000,
        target_mood="tense",
        archetype="climax",
        beats=[
            BeatPlan(beat_index=0, summary="铺垫", target_mood="calm", mood_phase="calm"),
            BeatPlan(beat_index=1, summary="爆发", target_mood="tense", mood_phase="climax"),
        ],
    )
    assert chapter.archetype == "climax"
    assert chapter.beats[0].mood_phase == "calm"
    assert chapter.beats[1].mood_phase == "climax"


def test_volume_beat_archetype_defaults_to_empty_string():
    from novel_dev.schemas.outline import VolumeBeat

    chapter = VolumeBeat(
        chapter_id="vol_1_ch_1",
        chapter_number=1,
        title="某章",
        summary="…",
        target_word_count=3000,
        target_mood="tense",
    )
    assert chapter.archetype == ""


def test_volume_beat_beat_mood_phase_defaults_to_none():
    from novel_dev.schemas.context import BeatPlan
    from novel_dev.schemas.outline import VolumeBeat

    chapter = VolumeBeat(
        chapter_id="vol_1_ch_1",
        chapter_number=1,
        title="某章",
        summary="…",
        target_word_count=3000,
        target_mood="tense",
        beats=[BeatPlan(beat_index=0, summary="…", target_mood="calm")],
    )
    assert chapter.beats[0].mood_phase is None


@pytest.mark.asyncio
async def test_volume_planner_batch_prompt_asks_for_archetype_and_mood_phase(async_session):
    """Phase 4 / Task 20: 批量扩展 prompt 必须引导 LLM 输出 archetype + mood_phase。"""
    from novel_dev.agents.volume_planner import VolumePlannerAgent, VolumePlanBlueprint
    from novel_dev.schemas.outline import SynopsisData

    agent = VolumePlannerAgent(async_session)
    blueprint = VolumePlanBlueprint.model_validate(
        {
            "volume_id": "vol_1",
            "volume_number": 1,
            "title": "卷一",
            "summary": "卷总述",
            "total_chapters": 1,
            "estimated_total_words": 3000,
            "chapters": [
                {"chapter_number": 1, "title": "旧案重启", "summary": "主角发现旧案线索。"},
            ],
        }
    )
    synopsis = SynopsisData(
        title="测试",
        logline="主角追查旧案。",
        core_conflict="真相与秩序冲突",
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=3000,
    )

    prompt = agent._build_volume_plan_batch_prompt(
        blueprint,
        synopsis,
        blueprint.chapters,
        world_snapshot=None,
        genre_prompt_block="",
    )

    # Chapter-level: archetype must be requested
    assert "archetype" in prompt
    # Per-beat: mood_phase must be requested
    assert "mood_phase" in prompt
