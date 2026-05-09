from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from novel_dev.agents._llm_helpers import call_and_parse_model, register_structured_normalizer
from novel_dev.schemas.context import BeatPlan, ChapterPlan


class ChapterStructureGuardResult(BaseModel):
    passed: bool
    completed_current_beat: bool = True
    premature_future_beat: bool = False
    introduced_plan_external_fact: bool = False
    changed_event_order: bool = False
    issues: list[str] = Field(default_factory=list)
    suggested_rewrite_focus: str = ""

    def evidence(self, *, beat_index: int, mode: str) -> dict[str, Any]:
        return {
            "mode": mode,
            "beat_index": beat_index,
            "passed": self.passed,
            "completed_current_beat": self.completed_current_beat,
            "premature_future_beat": self.premature_future_beat,
            "introduced_plan_external_fact": self.introduced_plan_external_fact,
            "changed_event_order": self.changed_event_order,
            "issues": list(self.issues),
            "suggested_rewrite_focus": self.suggested_rewrite_focus,
        }


class ChapterStructureGuardService:
    async def check_writer_beat(
        self,
        *,
        novel_id: str,
        chapter_plan: ChapterPlan | dict[str, Any],
        beat_index: int,
        beat: BeatPlan | dict[str, Any],
        generated_text: str,
        previous_text: str = "",
    ) -> ChapterStructureGuardResult:
        prompt = (
            "你是小说章节结构守卫。请判断当前节拍正文是否严格遵守章节计划。\n"
            "只返回符合 ChapterStructureGuardResult schema 的 JSON。\n\n"
            "## 判定规则\n"
            "1. 当前节拍必须完成当前 beat 的核心事件。\n"
            "2. 不得提前写后续 beat 的核心事件、揭示、战斗、追兵到达或章末钩子。\n"
            "3. 不得新增章节计划外事实、人物动机、线索、台词或因果。\n"
            "4. 不得改变已完成文本与当前 beat 的事件顺序。\n\n"
            f"### beat_index\n{beat_index}\n\n"
            f"### 章节计划\n{json.dumps(_to_jsonable(chapter_plan), ensure_ascii=False)}\n\n"
            f"### 当前 beat\n{json.dumps(_to_jsonable(beat), ensure_ascii=False)}\n\n"
            f"### 前文\n{previous_text[:2000]}\n\n"
            f"### 当前节拍正文\n{generated_text[:4000]}"
        )
        return await call_and_parse_model(
            "ChapterStructureGuardService",
            "check_writer_beat",
            prompt,
            ChapterStructureGuardResult,
            max_retries=2,
            novel_id=novel_id,
        )

    async def check_editor_beat(
        self,
        *,
        novel_id: str,
        chapter_plan: ChapterPlan | dict[str, Any],
        beat_index: int,
        source_text: str,
        polished_text: str,
    ) -> ChapterStructureGuardResult:
        prompt = (
            "你是小说章节结构守卫。请比较润色前后文本，判断润色是否只改表达，"
            "没有改剧情结构。\n"
            "只返回符合 ChapterStructureGuardResult schema 的 JSON。\n\n"
            "## 判定规则\n"
            "1. 润色后不得新增章节计划外事实、人物动机、线索、台词或因果。\n"
            "2. 润色后不得改变事件先后顺序。\n"
            "3. 润色后不得提前写后续 beat 的核心事件。\n"
            "4. 允许删减冗余、改善文风、压缩 AI 腔表达。\n\n"
            f"### beat_index\n{beat_index}\n\n"
            f"### 章节计划\n{json.dumps(_to_jsonable(chapter_plan), ensure_ascii=False)}\n\n"
            f"### 润色前\n{source_text[:4000]}\n\n"
            f"### 润色后\n{polished_text[:4000]}"
        )
        return await call_and_parse_model(
            "ChapterStructureGuardService",
            "check_editor_beat",
            prompt,
            ChapterStructureGuardResult,
            max_retries=1,
            novel_id=novel_id,
        )


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _normalize_writer_guard_payload(payload: Any, error: Exception | None) -> Any:
    return _normalize_guard_payload(payload, error, empty_policy="unchanged")


def _normalize_editor_guard_payload(payload: Any, error: Exception | None) -> Any:
    return _normalize_guard_payload(payload, error, empty_policy="fail")


def _normalize_guard_payload(payload: Any, error: Exception | None, *, empty_policy: str) -> Any:
    if not isinstance(payload, dict):
        return payload
    if not payload:
        if empty_policy == "fail":
            return {
                "passed": False,
                "completed_current_beat": True,
                "premature_future_beat": False,
                "introduced_plan_external_fact": True,
                "changed_event_order": False,
                "issues": ["结构守卫未返回有效判定，保守回退原文"],
                "suggested_rewrite_focus": "保留润色前文本，避免结构漂移",
            }
        return payload

    data = dict(payload)
    for wrapper_key in ("result", "guard", "verdict", "data"):
        wrapped = data.get(wrapper_key)
        if isinstance(wrapped, dict):
            data = dict(wrapped)
            break

    normalized = {
        "completed_current_beat": _first_bool(
            data,
            "completed_current_beat",
            "current_beat_completed",
            "beat_completed",
            "completed_beat",
            default=True,
        ),
        "premature_future_beat": _first_bool(
            data,
            "premature_future_beat",
            "premature_future_events",
            "future_beat",
            "advanced_future_beat",
            "spoiled_future_beat",
            default=False,
        ),
        "introduced_plan_external_fact": _first_bool(
            data,
            "introduced_plan_external_fact",
            "introduced_external_fact",
            "plan_external_fact",
            "has_external_fact",
            "changed_fact",
            "added_fact",
            "introduced_new_fact",
            default=False,
        ),
        "changed_event_order": _first_bool(
            data,
            "changed_event_order",
            "event_order_changed",
            "changed_order",
            "order_changed",
            default=False,
        ),
        "issues": _coerce_issues(
            data.get("issues")
            or data.get("problems")
            or data.get("violations")
            or data.get("reasons")
            or data.get("reason")
        ),
        "suggested_rewrite_focus": str(
            data.get("suggested_rewrite_focus")
            or data.get("rewrite_focus")
            or data.get("suggestion")
            or data.get("suggested_fix")
            or data.get("fix")
            or ""
        ),
    }

    passed = _first_bool(data, "passed", "is_valid", "valid", "approved", "ok", default=None)
    if passed is None:
        has_violation = (
            not normalized["completed_current_beat"]
            or normalized["premature_future_beat"]
            or normalized["introduced_plan_external_fact"]
            or normalized["changed_event_order"]
            or bool(normalized["issues"])
        )
        passed = not has_violation
    normalized["passed"] = passed
    return normalized


def _first_bool(data: dict[str, Any], *keys: str, default: bool | None) -> bool | None:
    for key in keys:
        if key in data:
            return _coerce_bool(data[key])
    return default


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "1", "pass", "passed", "valid", "ok"}:
            return True
        if normalized in {"false", "no", "n", "0", "fail", "failed", "invalid"}:
            return False
    return bool(value)


def _coerce_issues(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [item if isinstance(item, str) else json.dumps(item, ensure_ascii=False) for item in value]
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False)]
    return [str(value)]


register_structured_normalizer(
    "ChapterStructureGuardService",
    "check_writer_beat",
    _normalize_writer_guard_payload,
)
register_structured_normalizer(
    "ChapterStructureGuardService",
    "check_editor_beat",
    _normalize_editor_guard_payload,
)
