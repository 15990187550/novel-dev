from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from novel_dev.schemas.quality import QualityIssue
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

    _QUALITY_ISSUE_CLASSIFICATIONS = {
        "beat_cohesion": ("structure", "beat", "guided"),
        "text_integrity": ("structure", "paragraph", "auto"),
        "word_count_drift": ("prose", "chapter", "guided"),
        "ai_flavor": ("prose", "chapter", "guided"),
        "language_style": ("style", "chapter", "guided"),
        "required_payoff": ("plot", "chapter", "guided"),
        "final_review_score": ("prose", "chapter", "guided"),
        "review_note": ("structure", "chapter", "manual"),
        "consistency": ("continuity", "chapter", "guided"),
        "continuity_audit": ("continuity", "chapter", "guided"),
        "dead_entity_acted": ("continuity", "chapter", "guided"),
        "canonical_identity_drift": ("continuity", "chapter", "guided"),
        "story_contract_terms_missing": ("continuity", "chapter", "guided"),
    }

    _QUALITY_ISSUE_SUGGESTIONS = {
        "beat_cohesion": "补写节拍间的因果承接，删除重复拼接句，并让动作、反应、转折按顺序推进。",
        "text_integrity": "自动清理孤立标点或截断段落，补足未完成句读后重新检查正文结尾。",
        "word_count_drift": "按章节目标压缩或扩写关键场景，优先调整描写密度而不是新增无关情节。",
        "ai_flavor": "替换模板化总结句，增加具体动作、感官细节和角色独有表达。",
        "language_style": "统一叙述语体，移除未授权外文、现代术语和破坏世界观的表达。",
        "required_payoff": "回到章节计划补写缺失线索、钩子或回收点，确保读者能在正文中明确感知。",
        "final_review_score": "针对低分维度重修章节，优先处理情节推进、人物动机和语言完成度。",
        "review_note": "人工核查评审备注，判断是否需要结构重排、补写或删除问题段落。",
        "consistency": "对照上下文、实体状态和时间线修复冲突，再同步相关世界状态。",
        "continuity_audit": "对照连续性审计结果修正文中冲突，并同步实体、时间线或故事契约状态。",
        "dead_entity_acted": "修复已死亡或离场实体的行动描写，改为回忆、传闻、替代角色或删除冲突动作。",
        "canonical_identity_drift": "统一角色、地点或组织的标准身份称谓，避免别名与核心设定发生漂移。",
        "story_contract_terms_missing": "补回故事契约要求的关键术语、承诺或限制条件，确保章节延续既定规则。",
    }

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

    @classmethod
    def to_quality_issues(cls, gate: QualityGateResult) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for item in gate.blocking_items:
            issues.append(cls._gate_item_to_quality_issue(item, QUALITY_BLOCK))
        for item in gate.warning_items:
            issues.append(cls._gate_item_to_quality_issue(item, QUALITY_WARN))
        return issues

    @classmethod
    def _gate_item_to_quality_issue(cls, item: dict[str, Any], severity: str) -> QualityIssue:
        code = str(item.get("code") or "unknown")
        category, scope, repairability = cls._quality_issue_classification(code)
        return QualityIssue(
            code=code,
            category=category,
            severity=severity,
            scope=scope,
            repairability=repairability,
            evidence=cls._quality_issue_evidence(item),
            suggestion=cls._quality_issue_suggestion(code),
            source="quality_gate",
        )

    @classmethod
    def _quality_issue_classification(cls, code: str) -> tuple[str, str, str]:
        return cls._QUALITY_ISSUE_CLASSIFICATIONS.get(code, ("process", "chapter", "manual"))

    @staticmethod
    def _quality_issue_evidence(item: dict[str, Any]) -> list[str]:
        evidence: list[str] = []
        message = item.get("message")
        if message:
            evidence.append(str(message))

        detail = item.get("detail")
        if isinstance(detail, dict):
            for key, value in detail.items():
                evidence.append(f"{key}={value}")
        elif isinstance(detail, list):
            for value in detail[:5]:
                evidence.append(str(value))
        elif detail not in (None, "", [], {}):
            evidence.append(str(detail))

        if not evidence:
            evidence.append(f"quality gate item: {item.get('code', 'unknown')}")
        return evidence

    @classmethod
    def _quality_issue_suggestion(cls, code: str) -> str:
        return cls._QUALITY_ISSUE_SUGGESTIONS.get(code, "人工检查该质量门禁项，确认影响范围后制定修复方案。")

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
