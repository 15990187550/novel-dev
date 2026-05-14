from __future__ import annotations

from collections import Counter
from typing import Any

from novel_dev.schemas.quality import QualityIssue, QualitySource


class QualityIssueService:
    """Normalize quality diagnostics into shared QualityIssue objects."""

    _DIMENSION_CATEGORIES = {
        "readability": "prose",
        "humanity": "prose",
        "characterization": "character",
        "plot_tension": "plot",
        "hook_strength": "plot",
        "consistency": "continuity",
    }

    @classmethod
    def from_dimension_issues(cls, raw_issues: list[Any] | None) -> list[QualityIssue]:
        if raw_issues is None:
            return []

        issues: list[QualityIssue] = []
        for raw_issue in raw_issues:
            if not isinstance(raw_issue, dict):
                continue

            problem = cls._clean_string(raw_issue.get("problem"))
            if not problem:
                continue

            dim = cls._clean_string(raw_issue.get("dim")) or "unknown"
            beat_index = raw_issue.get("beat_idx")
            is_beat_scoped = isinstance(beat_index, int)
            issues.append(
                QualityIssue(
                    code=dim,
                    category=cls._DIMENSION_CATEGORIES.get(dim, "prose"),
                    severity="warn",
                    scope="beat" if is_beat_scoped else "chapter",
                    beat_index=beat_index if is_beat_scoped else None,
                    repairability="guided",
                    evidence=[problem],
                    suggestion=cls._clean_string(raw_issue.get("suggestion")),
                    source="critic",
                )
            )
        return issues

    @classmethod
    def from_structure_guard(
        cls,
        evidence: Any,
        source: QualitySource = "structure_guard",
    ) -> list[QualityIssue]:
        if not isinstance(evidence, dict):
            return []

        issue_evidence = cls._structure_guard_evidence(evidence)
        if not issue_evidence:
            return []

        suggestion = (
            cls._clean_string(evidence.get("suggested_rewrite_focus"))
            or "回到当前 beat 边界内重写。"
        )
        beat_index = evidence.get("beat_index")
        return [
            QualityIssue(
                code="plan_boundary_violation",
                category="structure",
                severity="block",
                scope="beat",
                beat_index=beat_index if isinstance(beat_index, int) else None,
                repairability="guided",
                evidence=issue_evidence,
                suggestion=suggestion,
                source=source,
            )
        ]

    @staticmethod
    def summarize(issues: list[QualityIssue]) -> dict[str, Any]:
        return {
            "total": len(issues),
            "by_category": dict(Counter(issue.category for issue in issues)),
            "by_code": dict(Counter(issue.code for issue in issues)),
            "by_severity": dict(Counter(issue.severity for issue in issues)),
            "by_repairability": dict(Counter(issue.repairability for issue in issues)),
        }

    @classmethod
    def _structure_guard_evidence(cls, evidence: dict[str, Any]) -> list[str]:
        raw_issues = evidence.get("issues")
        if not isinstance(raw_issues, list):
            return []
        return [cleaned for item in raw_issues if (cleaned := cls._clean_string(item))][:5]

    @staticmethod
    def _clean_string(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""
