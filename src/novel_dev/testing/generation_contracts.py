from __future__ import annotations

from collections.abc import Mapping, Set as AbstractSet
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ChapterPlanExtraction:
    source: str
    plan: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChapterTextStatus:
    field: str
    length: int
    has_text: bool


@dataclass(frozen=True, slots=True)
class QualityGateSummary:
    status: str
    reasons: str


@dataclass(frozen=True, slots=True)
class _ChapterTextAdapter:
    raw_draft: Any
    polished_text: Any


def extract_chapter_plan(
    response: dict[str, Any] | None,
    checkpoint: dict[str, Any] | None,
) -> ChapterPlanExtraction | None:
    response = response if isinstance(response, dict) else {}
    checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
    candidates = [
        ("current_chapter_plan", checkpoint.get("current_chapter_plan")),
        (
            "current_volume_plan.chapters[0]",
            _first_chapter_from_volume_plan(checkpoint.get("current_volume_plan")),
        ),
        ("response.chapter", response.get("chapter")),
        ("response.current_chapter_plan", response.get("current_chapter_plan")),
    ]
    for source, value in candidates:
        if isinstance(value, dict) and _is_usable_chapter_plan(value):
            return ChapterPlanExtraction(source=source, plan=dict(value))
    return None


def build_volume_plan_contract_evidence(
    response: dict[str, Any] | None,
    checkpoint: dict[str, Any] | None,
) -> list[str]:
    response = response if isinstance(response, dict) else {}
    checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
    current_volume_plan = checkpoint.get("current_volume_plan")
    evidence = [
        f"response_keys={_sorted_keys(response)}",
        f"checkpoint_keys={_sorted_keys(checkpoint)}",
        "current_chapter_plan_present="
        f"{str(isinstance(checkpoint.get('current_chapter_plan'), dict)).lower()}",
    ]
    if isinstance(current_volume_plan, dict):
        chapters = current_volume_plan.get("chapters")
        count = len(chapters) if isinstance(chapters, list) else 0
        evidence.extend(
            [
                f"current_volume_plan_keys={_sorted_keys(current_volume_plan)}",
                f"current_volume_plan_chapter_count={count}",
            ]
        )
        review_status = current_volume_plan.get("review_status")
        if isinstance(review_status, dict):
            evidence.extend(
                [
                    f"review_status_status={str(review_status.get('status') or '').strip() or 'none'}",
                    f"review_status_reason={str(review_status.get('reason') or '').strip() or 'none'}",
                ]
            )
    else:
        evidence.append("current_volume_plan_present=false")
    return evidence


def detect_chapter_text(chapter: Any | None) -> ChapterTextStatus:
    if chapter is None:
        return ChapterTextStatus(field="none", length=0, has_text=False)
    polished = _normalize_text(_chapter_value(chapter, "polished_text"))
    if polished:
        return ChapterTextStatus(
            field="polished_text",
            length=len(polished),
            has_text=True,
        )
    raw = _normalize_text(_chapter_value(chapter, "raw_draft"))
    if raw:
        return ChapterTextStatus(field="raw_draft", length=len(raw), has_text=True)
    return ChapterTextStatus(field="none", length=0, has_text=False)


def summarize_chapter_counts(chapters: list[dict[str, Any]] | None) -> dict[str, int]:
    chapter_items = chapters if isinstance(chapters, list) else []
    counts = {
        "planned": len(chapter_items),
        "generated_text": 0,
        "archived": 0,
        "blocked": 0,
        "pending": 0,
    }
    for chapter in chapter_items:
        if not isinstance(chapter, dict):
            continue
        text_status = detect_chapter_text(
            _ChapterTextAdapter(
                raw_draft=chapter.get("raw_draft"),
                polished_text=chapter.get("polished_text"),
            )
        )
        if text_status.has_text:
            counts["generated_text"] += 1

        status = _normalize_status(chapter.get("status"))
        quality_status = _normalize_status(chapter.get("quality_status"))
        if status == "archived":
            counts["archived"] += 1
        if quality_status == "block":
            counts["blocked"] += 1
        if status == "pending":
            counts["pending"] += 1
    return counts


def classify_export_result(
    response: dict[str, Any] | None,
    *,
    archived_chapter_count: int,
) -> str:
    response = response if isinstance(response, dict) else {}
    if "exported_path" in response:
        exported_path = response.get("exported_path")
        if _normalize_text(exported_path):
            return "export_succeeded"
        return "export_failed"
    if "exported_path" not in response:
        if archived_chapter_count <= 0:
            return "no_archived_chapters"
        return "export_not_requested"
    return "export_failed"


def summarize_quality_gate(chapter: Any | None) -> QualityGateSummary:
    if chapter is None:
        return QualityGateSummary(status="missing_chapter", reasons="")
    status = str(getattr(chapter, "quality_status", "unchecked") or "unchecked")
    reasons_value = getattr(chapter, "quality_reasons", None)
    if isinstance(reasons_value, dict):
        reasons = ",".join(sorted(str(key) for key in reasons_value))
    elif reasons_value is None:
        reasons = ""
    else:
        reasons = _format_quality_reasons(reasons_value)
    return QualityGateSummary(status=status, reasons=reasons)


def _first_chapter_from_volume_plan(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    chapters = value.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return None
    first = chapters[0]
    return first if isinstance(first, dict) else None


def _is_usable_chapter_plan(value: dict[str, Any]) -> bool:
    has_id_or_number = bool(value.get("chapter_id")) or value.get("chapter_number") is not None
    has_text_material = any(
        _has_text_material(value.get(key)) for key in ("title", "summary", "beats")
    )
    return has_id_or_number and has_text_material


def _sorted_keys(value: dict[str, Any]) -> str:
    keys = sorted(str(key) for key in value.keys())
    return ",".join(keys) if keys else "none"


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _chapter_value(chapter: Any, key: str) -> Any:
    if isinstance(chapter, Mapping):
        return chapter.get(key)
    return getattr(chapter, key, None)


def _normalize_status(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def _has_text_material(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _format_quality_reasons(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        parts = [part for item in value if (part := _normalize_reason_item(item))]
        return ",".join(parts)
    if isinstance(value, AbstractSet):
        parts = sorted(
            part for item in value if (part := _normalize_reason_item(item))
        )
        return ",".join(parts)
    normalized = _normalize_reason_item(value)
    return normalized or ""


def _normalize_reason_item(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, tuple, set, frozenset, dict)):
        return type(value).__name__
    return str(value)
