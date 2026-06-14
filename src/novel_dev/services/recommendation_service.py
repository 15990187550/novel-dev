"""Rule-based recommendation engine for chapter quality decisions.

The rules in this module are explicit, ordered, and testable. Phase 3
may add an LLM-driven override layer; the public interface
(`RecommendationService.recommend`) is designed to remain stable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from novel_dev.config.quality_config import get_quality_config


class RecommendationType(str, Enum):
    ACCEPT = "accept"
    MINOR_REPAIR = "minor_repair"
    MAJOR_REPAIR = "major_repair"
    STOP_AND_INSPECT = "stop_and_inspect"


@dataclass
class SuggestedAction:
    type: str
    scope: list[str] = field(default_factory=list)
    estimated_iterations: Optional[int] = None
    reason: Optional[str] = None


@dataclass
class Recommendation:
    chapter_id: Optional[str]
    recommendation: RecommendationType
    confidence: float
    rationale: list[str]
    suggested_actions: list[SuggestedAction]


class RecommendationService:
    def __init__(
        self,
        chapter: dict,
        recent_issue_counts: list[tuple[str, int]],
        current_attempt: int,
        thresholds: Optional[dict] = None,
    ):
        config = get_quality_config()
        self.chapter = chapter
        self.recent_issue_counts = recent_issue_counts
        self.current_attempt = current_attempt
        self.thresholds = thresholds if thresholds is not None else config["recommendation"]
        self.publishable_threshold = config["publishable_final_review_score"]

    def recommend(self, accept_with_warn: bool = False) -> Recommendation:
        rec_cfg = self.thresholds
        rationale: list[str] = []
        score = self.chapter.get("final_review_score")
        status = self.chapter.get("quality_status", "unchecked")
        breakdown = self.chapter.get("score_breakdown") or {}
        critical_dims = [
            d for d in ("plot_tension", "hook_strength", "humanity")
            if (breakdown.get(d) or {}).get("score") is not None
        ]
        low_critical = [
            d for d in critical_dims
            if (breakdown.get(d) or {}).get("score", 100) < 75
        ]

        # Rule 1: forced stop
        if self.current_attempt >= rec_cfg["stop_after_attempts"]:
            rationale.append(
                f"current_attempt={self.current_attempt} >= stop_after_attempts={rec_cfg['stop_after_attempts']}"
            )
            return self._build(RecommendationType.STOP_AND_INSPECT, 1.0, rationale)

        # Rule 2: pattern failure
        pattern_threshold = rec_cfg["pattern_issue_threshold"]
        for code, count in self.recent_issue_counts:
            if count >= pattern_threshold:
                rationale.append(f"{code} 在最近 {count} 章连续出现, 模式性故障")
                return self._build(RecommendationType.STOP_AND_INSPECT, 1.0, rationale)

        # Rule 3: block
        if status == "block":
            rationale.append("gate_status=block")
            return self._build(RecommendationType.STOP_AND_INSPECT, 1.0, rationale)

        # Rule 4: pass
        if status == "pass":
            return self._build(RecommendationType.ACCEPT, 1.0, ["gate_status=pass"])

        # Rule 5: warn with high score
        publishable = (score or 0) >= self.publishable_threshold
        if status == "warn" and publishable and not low_critical:
            if accept_with_warn:
                return self._build(
                    RecommendationType.ACCEPT, 1.0,
                    [f"score={score} >= publishable, warn acceptable"],
                )
            rationale.append(f"score={score} >= publishable, 但未开启 accept_with_warn")
            return self._build(
                RecommendationType.MINOR_REPAIR, 0.6, rationale,
                [SuggestedAction(type="accept_with_warn", reason="warn acceptable")],
            )

        # Rule 6: minor_repair
        minor_min = rec_cfg["minor_repair_min_score"]
        minor_crit = rec_cfg["minor_repair_min_critical"]
        if (score or 0) >= minor_min and all(
            (breakdown.get(d) or {}).get("score", 100) >= minor_crit
            for d in critical_dims
        ):
            rationale.append(f"score={score} 在 minor_repair 区间")
            return self._build(
                RecommendationType.MINOR_REPAIR, 0.7, rationale,
                [SuggestedAction(type="targeted_repair", scope=low_critical)],
            )

        # Rule 7: major_repair
        if (score or 0) >= rec_cfg["major_repair_min_score"]:
            rationale.append(f"score={score} 在 major_repair 区间")
            return self._build(
                RecommendationType.MAJOR_REPAIR, 0.7, rationale,
                [
                    SuggestedAction(type="targeted_repair", scope=low_critical),
                    SuggestedAction(type="manual_review", reason="需评估 outline"),
                ],
            )

        # Rule 8: fallback major_repair
        rationale.append(
            f"score={score} 低于 major_repair 阈值 {rec_cfg['major_repair_min_score']}"
        )
        return self._build(
            RecommendationType.MAJOR_REPAIR, 0.5, rationale,
            [SuggestedAction(type="manual_review", reason="分数过低, 需人工决策")],
        )

    def _build(self, rec_type, confidence, rationale, actions=None):
        return Recommendation(
            chapter_id=self.chapter.get("id"),
            recommendation=rec_type,
            confidence=confidence,
            rationale=rationale,
            suggested_actions=actions or [],
        )