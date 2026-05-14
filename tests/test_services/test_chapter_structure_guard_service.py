from unittest.mock import AsyncMock

import pytest

from novel_dev.schemas.context import BeatPlan, ChapterPlan
from novel_dev.services.chapter_structure_guard_service import (
    ChapterStructureGuardResult,
    ChapterStructureGuardService,
    _normalize_editor_guard_payload,
    _normalize_writer_guard_payload,
)


@pytest.mark.asyncio
async def test_writer_guard_returns_structured_result(monkeypatch):
    async def fake_call_and_parse_model(*args, **kwargs):
        return ChapterStructureGuardResult(
            passed=False,
            completed_current_beat=True,
            premature_future_beat=True,
            introduced_plan_external_fact=False,
            changed_event_order=False,
            issues=["提前写到后续节拍"],
            suggested_rewrite_focus="停在当前节拍结尾",
        )

    monkeypatch.setattr(
        "novel_dev.services.chapter_structure_guard_service.call_and_parse_model",
        fake_call_and_parse_model,
    )
    service = ChapterStructureGuardService()

    result = await service.check_writer_beat(
        novel_id="novel-guard",
        chapter_plan=ChapterPlan(
            chapter_number=1,
            title="第一章",
            target_word_count=1000,
            beats=[
                BeatPlan(summary="林照发现玉佩", target_mood="tense"),
                BeatPlan(summary="追兵赶到", target_mood="danger"),
            ],
        ),
        beat_index=0,
        beat=BeatPlan(summary="林照发现玉佩", target_mood="tense"),
        generated_text="林照发现玉佩后，追兵已经冲进屋内。",
        previous_text="",
    )

    assert result.passed is False
    assert result.premature_future_beat is True
    assert result.issues == ["提前写到后续节拍"]


@pytest.mark.asyncio
async def test_editor_guard_compares_source_and_polished(monkeypatch):
    fake_call = AsyncMock(
        return_value=ChapterStructureGuardResult(
            passed=False,
            completed_current_beat=True,
            premature_future_beat=False,
            introduced_plan_external_fact=True,
            changed_event_order=False,
            issues=["新增计划外黑影台词"],
            suggested_rewrite_focus="删除计划外台词",
        )
    )
    monkeypatch.setattr(
        "novel_dev.services.chapter_structure_guard_service.call_and_parse_model",
        fake_call,
    )
    service = ChapterStructureGuardService()

    result = await service.check_editor_beat(
        novel_id="novel-guard-editor",
        chapter_plan={"beats": [{"summary": "林照藏起玉佩"}]},
        beat_index=0,
        source_text="林照藏起玉佩。",
        polished_text="林照藏起玉佩。黑影说：你逃不掉。",
    )

    assert result.passed is False
    assert result.introduced_plan_external_fact is True
    assert fake_call.await_count == 1


@pytest.mark.asyncio
async def test_editor_guard_times_out_to_closed_failure(monkeypatch):
    async def fail_call(*args, **kwargs):
        raise RuntimeError("Request timed out")

    monkeypatch.setattr(
        "novel_dev.services.chapter_structure_guard_service.call_and_parse_model",
        fail_call,
    )
    service = ChapterStructureGuardService()

    result = await service.check_editor_beat(
        novel_id="novel-guard-timeout",
        chapter_plan={"beats": [{"summary": "林照藏起玉佩"}]},
        beat_index=0,
        source_text="林照藏起玉佩。",
        polished_text="林照藏起玉佩，呼吸一窒。",
    )

    assert result.passed is False
    assert result.introduced_plan_external_fact is True
    assert result.issues == ["结构守卫超时或失败，保守回退原文"]
    assert result.suggested_rewrite_focus == "保留润色前文本，避免结构漂移"


def test_guard_normalizer_accepts_common_alias_fields():
    normalized = _normalize_writer_guard_payload(
        {
            "is_valid": False,
            "current_beat_completed": True,
            "changed_fact": True,
            "reason": "新增了计划外线索",
            "suggestion": "删除计划外线索",
        },
        None,
    )

    assert normalized["passed"] is False
    assert normalized["completed_current_beat"] is True
    assert normalized["introduced_plan_external_fact"] is True
    assert normalized["issues"] == ["新增了计划外线索"]
    assert normalized["suggested_rewrite_focus"] == "删除计划外线索"


def test_editor_guard_empty_payload_fails_closed():
    normalized = _normalize_editor_guard_payload({}, None)

    assert normalized["passed"] is False
    assert normalized["introduced_plan_external_fact"] is True
    assert normalized["issues"] == ["结构守卫未返回有效判定，保守回退原文"]


def test_writer_guard_empty_payload_still_uses_retry_path():
    payload = {}

    assert _normalize_writer_guard_payload(payload, None) is payload
