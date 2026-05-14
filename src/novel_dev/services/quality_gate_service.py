from __future__ import annotations

from dataclasses import dataclass, field
import re
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
        polished_text: str | None = None,
        required_payoffs: list[str] | None = None,
        acceptance_scope: str | None = None,
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
            severity = cls._word_count_severity(
                target_word_count,
                polished_word_count,
                acceptance_scope=acceptance_scope,
            )
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

        integrity_issue = cls._text_integrity_issue(polished_text)
        if integrity_issue:
            blocking.append(integrity_issue)

        missing_payoffs = cls._missing_required_payoffs(polished_text, required_payoffs or [])
        if missing_payoffs:
            warnings.append(cls._item(
                "required_payoff",
                "章节计划要求的线索或章末钩子未充分兑现",
                {"missing": missing_payoffs[:5]},
            ))

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
    def _word_count_severity(
        target: int | None,
        actual: int | None,
        *,
        acceptance_scope: str | None = None,
    ) -> str:
        if acceptance_scope in {"real-contract", "real-longform-volume1"}:
            return QUALITY_WARN
        if not target or target <= 0 or actual is None:
            return QUALITY_WARN
        drift_ratio = abs(actual - target) / target
        return QUALITY_BLOCK if drift_ratio > 0.6 else QUALITY_WARN

    @staticmethod
    def _note_is_blocking(note: str) -> bool:
        lowered = str(note or "")
        blocking_keywords = ("设定冲突", "上下文冲突", "状态冲突", "人物关系冲突", "严重矛盾", "剧情断裂")
        return any(keyword in lowered for keyword in blocking_keywords)

    @classmethod
    def _text_integrity_issue(cls, polished_text: str | None) -> dict[str, Any] | None:
        text = str(polished_text or "").rstrip()
        if not text:
            return None
        for paragraph in text.splitlines():
            stripped = paragraph.strip()
            if stripped and len(stripped) <= 3 and all(char in "。，、；：！？!?…,. ;:" for char in stripped):
                return cls._item("text_integrity", "正文包含孤立标点段落，疑似节拍拼接或生成清洗异常", {"paragraph": stripped})
            truncated = cls._semantic_truncation_issue(stripped)
            if truncated:
                return truncated
        last = text[-1]
        if last in "。！？!?…」』”’）)":
            return None
        if last in "，、；：,. ;:":
            return cls._item("text_integrity", "正文末尾停在连接性标点，疑似未完成断句", {"ending": text[-20:]})
        if any("\u4e00" <= char <= "\u9fff" for char in text[-4:]):
            return cls._item("text_integrity", "正文末尾缺少完整句读，疑似生成截断", {"ending": text[-20:]})
        return None

    @classmethod
    def _semantic_truncation_issue(cls, paragraph: str) -> dict[str, Any] | None:
        if not paragraph:
            return None
        technical_endings = (
            (r"，照[。.!]$", "正文句末停在未完成动词“照”，疑似生成截断"),
            (r"，还是[。.!]$", "正文句末停在未完成选择结构，疑似生成截断"),
            (r"站不[。.!]$", "正文句末停在未完成补语“站不”，疑似生成截断"),
        )
        for pattern, message in technical_endings:
            if re.search(pattern, paragraph):
                return cls._item("text_integrity", message, {"ending": paragraph[-30:]})
        return None

    @classmethod
    def _missing_required_payoffs(cls, polished_text: str | None, required_payoffs: list[str]) -> list[str]:
        normalized_text = cls._normalize_for_match(polished_text or "")
        if not normalized_text:
            return []
        missing = []
        for payoff in required_payoffs:
            normalized_payoff = cls._normalize_for_match(str(payoff or ""))
            if not normalized_payoff:
                continue
            if normalized_payoff in normalized_text:
                continue
            if cls._text_overlap(normalized_payoff, normalized_text) < 0.55:
                missing.append(str(payoff))
        return missing

    @staticmethod
    def _normalize_for_match(text: str) -> str:
        return "".join(ch for ch in str(text or "") if not ch.isspace() and ch not in "，。！？；：、,.!?;:（）()[]【】“”\"'")

    @staticmethod
    def _text_overlap(needle: str, haystack: str) -> float:
        needle_chars = set(needle)
        if not needle_chars:
            return 0.0
        return len(needle_chars & set(haystack)) / len(needle_chars)

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
