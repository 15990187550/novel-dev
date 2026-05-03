from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from novel_dev.schemas.review import FastReviewReport


QUALITY_UNCHECKED = "unchecked"
QUALITY_PASS = "pass"
QUALITY_WARN = "warn"
QUALITY_BLOCK = "block"


@dataclass
class QualityGateResult:
    status: str
    blocking_items: list[dict[str, Any]] = field(default_factory=list)
    warning_items: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blocking_items": self.blocking_items,
            "warning_items": self.warning_items,
            "summary": self.summary,
        }


class QualityGateService:
    """Classify chapter quality into pass/warn/block from structured checks."""

    @classmethod
    def evaluate_fast_review(
        cls,
        report: FastReviewReport,
        *,
        target_word_count: int | None = None,
        polished_word_count: int | None = None,
        final_review_score: int | None = None,
    ) -> QualityGateResult:
        blocking: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        if not report.consistency_fixed:
            blocking.append(cls._item("consistency", "设定或上下文一致性未修复", report.notes))
        if not report.beat_cohesion_ok:
            blocking.append(cls._item("beat_cohesion", "节拍之间缺少连续承接", report.notes))

        if final_review_score is not None:
            if final_review_score < 60:
                blocking.append(cls._item("final_review_score", f"成稿评分过低: {final_review_score}"))
            elif final_review_score < 75:
                warnings.append(cls._item("final_review_score", f"成稿评分偏低: {final_review_score}"))

        if not report.word_count_ok:
            severity = cls._word_count_severity(target_word_count, polished_word_count)
            item = cls._item(
                "word_count_drift",
                "字数严重偏离目标" if severity == QUALITY_BLOCK else "字数偏离目标",
                {
                    "target_word_count": target_word_count,
                    "polished_word_count": polished_word_count,
                },
            )
            if severity == QUALITY_BLOCK:
                blocking.append(item)
            else:
                warnings.append(item)

        if not report.ai_flavor_reduced:
            warnings.append(cls._item("ai_flavor", "AI 腔或模板化表达未充分降低", report.notes))
        if not report.language_style_ok:
            warnings.append(cls._item("language_style", "存在未授权外文、现代术语或风格问题", report.notes))

        for note in report.notes:
            if cls._note_is_blocking(note):
                blocking.append(cls._item("review_note", note))

        if blocking:
            return QualityGateResult(
                status=QUALITY_BLOCK,
                blocking_items=cls._dedupe(blocking),
                warning_items=cls._dedupe(warnings),
                summary="存在阻断级质量问题，停止归档和世界状态入库。",
            )
        if warnings:
            return QualityGateResult(
                status=QUALITY_WARN,
                warning_items=cls._dedupe(warnings),
                summary="存在可接受告警，允许归档但需要展示诊断。",
            )
        return QualityGateResult(status=QUALITY_PASS, summary="质量门禁通过。")

    @staticmethod
    def _word_count_severity(target: int | None, actual: int | None) -> str:
        if not target or target <= 0 or actual is None:
            return QUALITY_WARN
        drift_ratio = abs(actual - target) / target
        return QUALITY_BLOCK if drift_ratio > 0.6 else QUALITY_WARN

    @staticmethod
    def _note_is_blocking(note: str) -> bool:
        lowered = str(note or "")
        blocking_keywords = ("设定冲突", "上下文冲突", "状态冲突", "人物关系冲突", "严重矛盾", "剧情断裂")
        return any(keyword in lowered for keyword in blocking_keywords)

    @staticmethod
    def _item(code: str, message: str, detail: Any | None = None) -> dict[str, Any]:
        item = {"code": code, "message": message}
        if detail not in (None, [], {}):
            item["detail"] = detail
        return item

    @staticmethod
    def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen = set()
        result = []
        for item in items:
            key = (item.get("code"), item.get("message"))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result
