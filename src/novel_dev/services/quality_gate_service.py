from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from novel_dev.schemas.quality import QualityIssue
from novel_dev.schemas.review import FastReviewReport

from novel_dev.config.quality_config import get_quality_config


QUALITY_UNCHECKED = "unchecked"
QUALITY_PASS = "pass"
QUALITY_WARN = "warn"
QUALITY_MANUAL_REVIEW_REQUIRED = "manual_review_required"
QUALITY_BLOCK = "block"
QUALITY_STOP_STATUSES = frozenset({QUALITY_BLOCK, QUALITY_MANUAL_REVIEW_REQUIRED})
CRITICAL_REVIEW_DIMENSIONS = frozenset({"plot_tension", "hook_strength", "humanity"})


def _publishable_score() -> float:
    return float(get_quality_config()["publishable_final_review_score"])


def _critical_min() -> float:
    return float(get_quality_config()["critical_dimension_min_score"])


def quality_gate_stops_librarian(status: str | None) -> bool:
    return str(status or QUALITY_UNCHECKED) in QUALITY_STOP_STATUSES


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

    _ABSTRACT_PAYOFF_INTENT_MARKERS = (
        "提升",
        "提高",
        "增强",
        "强化",
        "变强",
        "改善",
        "精进",
        "进步",
        "突破",
        "升级",
        "恢复",
        "稳固",
        "凝练",
        "凝炼",
        "凝实",
    )
    _PAYOFF_PROGRESS_EVIDENCE_MARKERS = _ABSTRACT_PAYOFF_INTENT_MARKERS + (
        "淬炼",
        "凝成",
        "凝为",
        "纯粹",
        "澄澈",
        "清澈",
        "远超",
        "胜过",
        "胜于",
        "压过",
        "近乎实质",
        "更强",
        "更稳",
        "更纯",
        "更清",
        "更深",
        "更高",
        "更实",
    )
    _PAYOFF_TARGET_FILLER_TERMS = frozenset({
        "品质",
        "程度",
        "状态",
        "变化",
        "效果",
        "结果",
        "能力",
        "力量",
        "层次",
        "水平",
        "质量",
        "表现",
        "新的",
        "新",
    })

    _QUALITY_ISSUE_CLASSIFICATIONS = {
        "beat_cohesion": ("structure", "beat", "guided"),
        "text_integrity": ("structure", "paragraph", "auto"),
        "word_count_drift": ("prose", "chapter", "guided"),
        "ai_flavor": ("prose", "chapter", "guided"),
        "language_style": ("style", "chapter", "guided"),
        "required_payoff": ("plot", "chapter", "guided"),
        "ending_driver": ("plot", "chapter", "guided"),
        "final_review_score": ("prose", "chapter", "guided"),
        "critical_dimension_score": ("plot", "chapter", "guided"),
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
        "ending_driver": "回到章末已出现的人物、物件、风险或选择，让其中一个产生可见后果或限制下一步行动。",
        "final_review_score": "针对低分维度重修章节，优先处理情节推进、人物动机和语言完成度。",
        "critical_dimension_score": "针对低分关键维度定点重修，优先修复章末钩子、冲突升级和人物在场反应。",
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
        final_review_feedback: dict | None = None,
        polished_text: str | None = None,
        required_payoffs: list[str] | None = None,
        ending_driver_candidates: list[str] | None = None,
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
            elif final_review_score < _publishable_score():
                warnings.append(cls._item(
                    "final_review_score",
                    f"成稿未达到自动归档质量线: {final_review_score}",
                    {
                        "score": final_review_score,
                        "required": _publishable_score(),
                    },
                ))

        critical_dimension_warnings = cls._critical_dimension_warnings(final_review_feedback)
        warnings.extend(critical_dimension_warnings)

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

        missing_ending_drivers = cls._missing_ending_drivers(polished_text, ending_driver_candidates or [])
        if missing_ending_drivers:
            warnings.append(cls._item(
                "ending_driver",
                "章末缺少可见的下一步驱动",
                {"missing": missing_ending_drivers[:5]},
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
            status = QUALITY_MANUAL_REVIEW_REQUIRED if cls._requires_manual_review(warnings) else QUALITY_WARN
            return QualityGateResult(
                status=status,
                warning_items=cls._dedupe(warnings),
                summary=(
                    "存在需要人工确认的质量问题，停止自动归档。"
                    if status == QUALITY_MANUAL_REVIEW_REQUIRED
                    else "存在可接受告警，允许归档但需要展示诊断。"
                ),
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
    def genre_type_drift_items(cls, text: str, quality_config: dict | None = None) -> list[str]:
        config = quality_config or {}
        if not (config.get("blocking_rules") or {}).get("type_drift"):
            return []
        items = []
        seen = set()
        for pattern in config.get("forbidden_drift_patterns") or []:
            normalized_pattern = str(pattern).strip() if pattern is not None else ""
            if not normalized_pattern or normalized_pattern in seen:
                continue
            seen.add(normalized_pattern)
            if normalized_pattern in text:
                items.append(f"type_drift: 命中类型漂移规则：{normalized_pattern}")
        return items

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
    def _requires_manual_review(warnings: list[dict[str, Any]]) -> bool:
        manual_review_codes = {
            "final_review_score",
            "critical_dimension_score",
            "language_style",
            "required_payoff",
            "ending_driver",
        }
        return any(str(item.get("code")) in manual_review_codes for item in warnings if isinstance(item, dict))

    @classmethod
    def _critical_dimension_warnings(cls, final_review_feedback: dict | None) -> list[dict[str, Any]]:
        if not isinstance(final_review_feedback, dict):
            return []
        breakdown = final_review_feedback.get("breakdown")
        if not isinstance(breakdown, dict):
            return []
        warnings: list[dict[str, Any]] = []
        for dim in sorted(CRITICAL_REVIEW_DIMENSIONS):
            value = breakdown.get(dim)
            score = value.get("score") if isinstance(value, dict) else value
            if not isinstance(score, (int, float)):
                continue
            if score >= _critical_min():
                continue
            comment = value.get("comment") if isinstance(value, dict) else ""
            warnings.append(cls._item(
                "critical_dimension_score",
                f"关键维度 {dim} 低于质量线: {score}",
                {
                    "dimension": dim,
                    "score": score,
                    "required": _critical_min(),
                    "comment": comment,
                },
            ))
        return warnings

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
            if cls._abstract_payoff_covered(normalized_payoff, normalized_text):
                continue
            if cls._text_overlap(normalized_payoff, normalized_text) < 0.55:
                missing.append(str(payoff))
        return missing

    @classmethod
    def _missing_ending_drivers(cls, polished_text: str | None, candidates: list[str]) -> list[str]:
        text = str(polished_text or "").strip()
        if not text or not candidates:
            return []
        ending = text[-500:]
        normalized_ending = cls._normalize_for_match(ending)
        evaluated: list[str] = []
        for candidate in candidates:
            cleaned = str(candidate or "").strip()
            if not cleaned:
                continue
            terms = cls._ending_driver_terms(cleaned)
            if not terms:
                continue
            evaluated.append(cleaned)
            if cls._ending_driver_evidence_present(normalized_ending, terms):
                return []
        return evaluated

    @classmethod
    def _ending_driver_evidence_present(cls, normalized_ending: str, terms: list[str]) -> bool:
        evidence_markers = (
            "发热", "变热", "变冷", "变亮", "亮起", "震动", "颤动", "裂开", "渗出",
            "响", "停住", "回头", "盯", "视线", "拦", "堵", "跟", "靠近", "收紧",
            "握紧", "按住", "摸到", "刺痛", "发麻", "沉", "烫", "冷", "沙沙",
        )
        for term in terms:
            start = 0
            while True:
                index = normalized_ending.find(term, start)
                if index < 0:
                    break
                window = normalized_ending[max(0, index - 30): index + len(term) + 50]
                if any(marker in window for marker in evidence_markers):
                    return True
                start = index + len(term)
        return False

    @staticmethod
    def _ending_driver_terms(candidate: str) -> list[str]:
        stop_terms = {
            "出现", "可感知", "变化", "状态", "行动", "限制", "关系", "压力",
            "章末", "下一步", "受限", "手里", "可见", "后果", "忽然", "正在",
            "留下", "人物", "物件", "风险", "选择",
        }
        terms: list[str] = []
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,12}", candidate):
            for part in re.split(r"在|被|让|使|把|将|出现|发生|留下|产生|变得|手里|身上|眼前|章末|下一步", chunk):
                part = part.strip()
                if len(part) >= 2:
                    terms.append(part[:6])
            if len(chunk) <= 4:
                terms.append(chunk)
        seen = set()
        result = []
        for term in terms:
            if term in seen or term in stop_terms or term.endswith(("变化", "压力", "后果")):
                continue
            seen.add(term)
            result.append(term)
        return result[:4]

    @classmethod
    def _abstract_payoff_covered(cls, normalized_payoff: str, normalized_text: str) -> bool:
        if not any(marker in normalized_payoff for marker in cls._ABSTRACT_PAYOFF_INTENT_MARKERS):
            return False
        target_terms = cls._payoff_target_terms(normalized_payoff)
        if not target_terms:
            return False
        for term in target_terms:
            start = 0
            while True:
                index = normalized_text.find(term, start)
                if index < 0:
                    break
                window = normalized_text[max(0, index - 40): index + len(term) + 80]
                if any(marker in window for marker in cls._PAYOFF_PROGRESS_EVIDENCE_MARKERS):
                    return True
                start = index + len(term)
        return False

    @classmethod
    def _payoff_target_terms(cls, normalized_payoff: str) -> list[str]:
        candidate = normalized_payoff
        for marker in sorted(cls._ABSTRACT_PAYOFF_INTENT_MARKERS, key=len, reverse=True):
            candidate = candidate.replace(marker, "")
        for filler in sorted(cls._PAYOFF_TARGET_FILLER_TERMS, key=len, reverse=True):
            candidate = candidate.replace(filler, "")
        terms = [term for term in re.findall(r"[\u4e00-\u9fff]{2,}", candidate) if term not in cls._PAYOFF_TARGET_FILLER_TERMS]
        if terms:
            return terms[:3]
        compact = "".join(ch for ch in candidate if "\u4e00" <= ch <= "\u9fff")
        return [compact] if len(compact) >= 2 and compact not in cls._PAYOFF_TARGET_FILLER_TERMS else []

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
