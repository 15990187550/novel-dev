from __future__ import annotations

import re

from typing import Any, Literal

from pydantic import BaseModel, Field


AcceptanceStatus = Literal["accepted", "repairable", "manual_review_required", "continue_with_risk"]
ContinuePolicy = Literal["continue", "repair_once", "pause"]


class ChapterAcceptanceResult(BaseModel):
    status: AcceptanceStatus
    summary: str
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    warning_issues: list[dict[str, Any]] = Field(default_factory=list)
    repair_directives: list[dict[str, Any]] = Field(default_factory=list)
    continue_policy: ContinuePolicy = "continue"


class ChapterAcceptanceService:
    """Lightweight structured acceptance gate before heavier repair decisions."""

    BLOCKING_CODES = {
        "continuity_audit",
        "consistency",
        "dead_entity_acted",
        "canonical_identity_drift",
        "text_integrity",
    }
    ENDING_CODES = {"hook_strength", "required_payoff"}
    VOICE_CODES = {"ai_flavor", "language_style", "humanity"}

    @classmethod
    def assess(
        cls,
        *,
        content: str,
        quality_issues: list[dict[str, Any]] | None = None,
        target_word_count: int | None = None,
    ) -> ChapterAcceptanceResult:
        issues = [issue for issue in quality_issues or [] if isinstance(issue, dict)]
        blocking = [cls._normalize_issue(issue) for issue in issues if cls._is_blocking(issue)]
        warnings = [cls._normalize_issue(issue) for issue in issues if not cls._is_blocking(issue)]

        if blocking:
            return ChapterAcceptanceResult(
                status="manual_review_required",
                summary="存在连续性、文本完整性或事实边界阻断问题，需要人工确认或进入重修。",
                blocking_issues=blocking,
                warning_issues=warnings,
                continue_policy="pause",
            )

        repairable = [issue for issue in warnings if cls._is_patchable(issue)]
        if repairable:
            return ChapterAcceptanceResult(
                status="repairable",
                summary="章节主体可保留，存在适合局部补丁修复的问题。",
                warning_issues=warnings,
                repair_directives=[cls._repair_directive(issue, content) for issue in repairable[:3]],
                continue_policy="repair_once",
            )

        if warnings:
            return ChapterAcceptanceResult(
                status="continue_with_risk",
                summary="章节可以继续推进，但保留非阻断质量风险。",
                warning_issues=warnings,
                continue_policy="continue",
            )

        return ChapterAcceptanceResult(
            status="accepted",
            summary="章节可接收。",
            continue_policy="continue",
        )

    @classmethod
    def _is_blocking(cls, issue: dict[str, Any]) -> bool:
        severity = str(issue.get("severity") or issue.get("status") or "").lower()
        code = str(issue.get("code") or "").strip()
        return severity in {"block", "critical", "high"} and code in cls.BLOCKING_CODES

    @classmethod
    def _is_patchable(cls, issue: dict[str, Any]) -> bool:
        return str(issue.get("code") or "") in cls.ENDING_CODES | cls.VOICE_CODES

    @classmethod
    def _normalize_issue(cls, issue: dict[str, Any]) -> dict[str, Any]:
        code = str(issue.get("code") or "quality_issue")
        return {
            "code": code,
            "category": cls._category_for_code(code),
            "severity": str(issue.get("severity") or "warn"),
            "message": str(issue.get("message") or issue.get("evidence") or issue.get("problem") or ""),
            "evidence": issue.get("evidence") or [],
            "suggestion": str(issue.get("suggestion") or issue.get("fixSuggestion") or ""),
        }

    @classmethod
    def _category_for_code(cls, code: str) -> str:
        if code in {"continuity_audit", "consistency", "dead_entity_acted", "canonical_identity_drift"}:
            return "continuity"
        if code in cls.ENDING_CODES:
            return "ending"
        if code in cls.VOICE_CODES:
            return "voice"
        if code == "text_integrity":
            return "structure"
        return "plot"

    @classmethod
    def _repair_directive(cls, issue: dict[str, Any], content: str) -> dict[str, Any]:
        code = str(issue.get("code") or "")
        target = "ending" if code in cls.ENDING_CODES else "voice"
        source = str(issue.get("suggestion") or issue.get("message") or "").strip()
        if not source:
            source = "保留原事件事实，只做局部表达修复。"
        anchor = cls._anchor_from_issue(issue)
        instruction = f"{source}；优先使用原文已有素材{('：' + anchor) if anchor else ''}。"
        return {
            "mode": "patch",
            "target": target,
            "instruction": instruction,
        }

    @staticmethod
    def _anchor_from_issue(issue: dict[str, Any]) -> str:
        fragments: list[str] = []
        evidence = issue.get("evidence")
        if isinstance(evidence, list):
            fragments.extend(str(item) for item in evidence)
        elif evidence:
            fragments.append(str(evidence))
        for fragment in fragments:
            anchor = _extract_concrete_anchor(fragment)
            if anchor:
                return anchor
        return ""


def _extract_concrete_anchor(text: str) -> str:
    for match in re.finditer(r"([\u4e00-\u9fff]{2,8})(?:出现|带出|形成|没有|上的|里|外|前|后)", text):
        candidate = match.group(1).strip("，。；、：")
        if candidate:
            return candidate
    return ""
