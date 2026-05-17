from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from novel_dev.agents._llm_helpers import coerce_to_str_list, coerce_to_text
from novel_dev.schemas.context import ChapterPlan


PreflightStatus = Literal["pass", "warn", "block"]
PreflightDimensionName = Literal[
    "setting_consistency",
    "readability",
    "plot_continuity",
    "writability",
    "story_contract",
]


class QualityPreflightIssue(BaseModel):
    code: str
    dimension: PreflightDimensionName
    severity: Literal["warn", "block"]
    beat_index: int | None = None
    message: str
    evidence: list[str] = Field(default_factory=list)
    suggestion: str = ""


class QualityPreflightDimension(BaseModel):
    name: PreflightDimensionName
    status: PreflightStatus = "pass"
    issues: list[QualityPreflightIssue] = Field(default_factory=list)


class QualityPreflightReport(BaseModel):
    status: PreflightStatus
    passed: bool
    dimensions: list[QualityPreflightDimension] = Field(default_factory=list)
    blocking_issues: list[QualityPreflightIssue] = Field(default_factory=list)
    warning_issues: list[QualityPreflightIssue] = Field(default_factory=list)
    canonical_constraints: list[str] = Field(default_factory=list)
    continuity_requirements: list[str] = Field(default_factory=list)
    readability_contract: list[str] = Field(default_factory=list)
    causal_links: list[str] = Field(default_factory=list)
    required_terms: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    source: str = "quality_preflight"


class QualityPreflightService:
    """Deterministic upstream quality checks before prose generation."""

    DIMENSIONS: tuple[PreflightDimensionName, ...] = (
        "setting_consistency",
        "readability",
        "plot_continuity",
        "writability",
        "story_contract",
    )
    CONFLICT_TERMS = ("冲突", "对抗", "阻", "追", "逼", "威胁", "发现", "暴露", "争", "夺", "杀", "拦", "困")
    CHOICE_TERMS = ("选择", "决定", "必须", "被迫", "代价", "赌注", "否则", "宁可", "只得")
    STAKE_TERMS = ("代价", "失败", "否则", "暴露", "失去", "错过", "被逐", "受罚", "中断", "盯上")
    HOOK_TERMS = ("悬念", "反转", "逼近", "发现", "暴露", "异动", "传来", "出现", "留下", "盯上")
    ABSTRACT_READABILITY_TERMS = (
        "了解世界",
        "认识环境",
        "修炼成长",
        "继续成长",
        "稳步修行",
        "推进当前目标",
        "当前目标",
        "当前事件",
        "资源限制、身份压力或对手试探",
        "现场规矩和旁人审视",
    )
    GENERIC_REPAIR_MARKERS = (
        "必须在继续行动与保全自身之间做出选择",
        "阻力当场升级",
        "失败代价是失去关键线索并暴露处境",
        "结尾留下新的危险信号",
    )
    CAUSAL_CONNECTORS = ("因此", "于是", "但", "却", "发现", "决定", "被迫", "为了", "因", "随后", "转而")

    @classmethod
    def evaluate_chapter_plan(
        cls,
        chapter_plan: ChapterPlan | dict[str, Any] | Any,
        *,
        story_contract: dict[str, Any] | None = None,
        active_entities: list[dict[str, Any]] | None = None,
    ) -> QualityPreflightReport:
        plan = cls._normalize_chapter_plan(chapter_plan)
        story_contract = story_contract if isinstance(story_contract, dict) else {}
        active_entities = active_entities or []
        issues: list[QualityPreflightIssue] = []
        plan_text = cls._chapter_text(plan)

        issues.extend(cls._writability_issues(plan))
        issues.extend(cls._readability_issues(plan))
        issues.extend(cls._plot_continuity_issues(plan))
        required_terms = cls._required_terms(story_contract)
        forbidden_terms = cls._forbidden_terms(story_contract, active_entities)
        issues.extend(cls._story_contract_issues(plan_text, required_terms, forbidden_terms))
        canonical_constraints = cls._canonical_constraints(story_contract, active_entities)
        continuity_requirements = cls._continuity_requirements(required_terms, canonical_constraints)
        readability_contract = cls._readability_contract(plan)
        causal_links = cls._causal_links(plan)

        blocking = [issue for issue in issues if issue.severity == "block"]
        warnings = [issue for issue in issues if issue.severity == "warn"]
        status: PreflightStatus = "block" if blocking else "warn" if warnings else "pass"
        return QualityPreflightReport(
            status=status,
            passed=status != "block",
            dimensions=cls._dimensions(issues),
            blocking_issues=blocking,
            warning_issues=warnings,
            canonical_constraints=canonical_constraints,
            continuity_requirements=continuity_requirements,
            readability_contract=readability_contract,
            causal_links=causal_links,
            required_terms=required_terms,
            forbidden_terms=forbidden_terms,
        )

    @classmethod
    def build_chapter_contract(
        cls,
        chapter_plan: ChapterPlan,
        *,
        story_contract: dict[str, Any] | None = None,
        active_entities: list[dict[str, Any]] | None = None,
    ) -> dict[str, list[str]]:
        report = cls.evaluate_chapter_plan(
            chapter_plan,
            story_contract=story_contract,
            active_entities=active_entities,
        )
        return {
            "canonical_constraints": report.canonical_constraints,
            "continuity_requirements": report.continuity_requirements,
            "readability_contract": report.readability_contract,
            "causal_links": report.causal_links,
        }

    @classmethod
    def summarize_volume_plan(
        cls,
        plan: Any,
        *,
        story_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chapters = getattr(plan, "chapters", []) or []
        if not chapters:
            issue = cls._issue(
                "missing_volume_chapters",
                "writability",
                "block",
                "卷纲没有章节，不能进入正文生成。",
            )
            return {
                "status": "block",
                "passed": False,
                "blocked_chapter_numbers": [],
                "warned_chapter_numbers": [],
                "chapters": [],
                "blocking_issues": [issue.model_dump()],
                "warning_issues": [],
            }
        chapter_reports = []
        blocked_numbers = []
        warned_numbers = []
        for chapter in chapters:
            report = cls.evaluate_chapter_plan(chapter, story_contract=story_contract)
            number = getattr(chapter, "chapter_number", None)
            if report.status == "block" and number is not None:
                blocked_numbers.append(number)
            elif report.status == "warn" and number is not None:
                warned_numbers.append(number)
            chapter_reports.append({
                "chapter_id": getattr(chapter, "chapter_id", ""),
                "chapter_number": number,
                "title": getattr(chapter, "title", ""),
                "report": report.model_dump(),
            })
        status: PreflightStatus = "block" if blocked_numbers else "warn" if warned_numbers else "pass"
        return {
            "status": status,
            "passed": status != "block",
            "blocked_chapter_numbers": blocked_numbers,
            "warned_chapter_numbers": warned_numbers,
            "chapters": chapter_reports,
        }

    @classmethod
    def _normalize_chapter_plan(cls, value: ChapterPlan | dict[str, Any] | Any) -> ChapterPlan:
        if isinstance(value, ChapterPlan):
            return value
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        if not isinstance(value, dict):
            value = {}
        payload = dict(value)
        payload.setdefault("chapter_number", payload.get("number") or 1)
        payload.setdefault("title", payload.get("title") or "")
        payload.setdefault("target_word_count", payload.get("target_word_count") or 800)
        payload.setdefault("beats", payload.get("beats") or [])
        return ChapterPlan.model_validate(payload)

    @classmethod
    def _writability_issues(cls, plan: ChapterPlan) -> list[QualityPreflightIssue]:
        issues: list[QualityPreflightIssue] = []
        if not plan.beats:
            return [cls._issue(
                "missing_beats",
                "writability",
                "block",
                "章节计划没有 beats，不能进入正文生成。",
                suggestion="至少补齐当前目标、阻力、选择/代价和章末停点。",
            )]
        generic_indexes = cls._generic_repair_indexes([beat.summary for beat in plan.beats])
        for index, beat in enumerate(plan.beats):
            text = beat.summary
            missing = []
            if not cls._has_any(text, cls.CONFLICT_TERMS):
                missing.append("具体阻力")
            if not cls._has_any(text, cls.CHOICE_TERMS):
                missing.append("当场选择")
            if not cls._has_any(text, cls.STAKE_TERMS):
                missing.append("失败代价")
            if missing:
                issues.append(cls._issue(
                    "beat_contract_incomplete",
                    "writability",
                    "block",
                    f"节拍 {index + 1} 缺少可执行的{'、'.join(missing)}。",
                    beat_index=index,
                    evidence=[text],
                    suggestion="改成角色目标 + 具体阻力 + 当场选择 + 失败代价 + 停点。",
                ))
        for index in generic_indexes:
            issues.append(cls._issue(
                "repeated_generic_repair_constraint",
                "writability",
                "block",
                "多个节拍重复使用通用硬约束，正文会变成同质模板。",
                beat_index=index,
                evidence=[plan.beats[index].summary],
                suggestion="删除模板句，分别写出每个 beat 独有的目标、阻力、选择和停点。",
            ))
        if plan.beats and not cls._has_any(plan.beats[-1].summary, cls.HOOK_TERMS):
            issues.append(cls._issue(
                "weak_ending_hook",
                "writability",
                "warn",
                "最后一个 beat 缺少明确章末钩子。",
                beat_index=len(plan.beats) - 1,
                evidence=[plan.beats[-1].summary],
                suggestion="补一个由本章已出现线索引发的新危险、反转或问题。",
            ))
        return issues

    @classmethod
    def _readability_issues(cls, plan: ChapterPlan) -> list[QualityPreflightIssue]:
        issues: list[QualityPreflightIssue] = []
        for index, beat in enumerate(plan.beats):
            summary = beat.summary
            if any(term in summary for term in cls.ABSTRACT_READABILITY_TERMS):
                issues.append(cls._issue(
                    "abstract_or_generic_readability_seed",
                    "readability",
                    "warn",
                    "节拍摘要偏抽象或模板化，正文容易信息倾倒或读感发虚。",
                    beat_index=index,
                    evidence=[summary],
                    suggestion="补可见动作、短对话、环境反应或具体物件承载信息。",
                ))
            if len(summary.strip()) < 18:
                issues.append(cls._issue(
                    "beat_summary_too_thin",
                    "readability",
                    "warn",
                    "节拍摘要过短，Writer 难以生成有读感的场景。",
                    beat_index=index,
                    evidence=[summary],
                    suggestion="补充场景落点、人物动作和读者可感知的信息变化。",
                ))
        return issues

    @classmethod
    def _plot_continuity_issues(cls, plan: ChapterPlan) -> list[QualityPreflightIssue]:
        issues: list[QualityPreflightIssue] = []
        previous = ""
        previous_entities: set[str] = set()
        for index, beat in enumerate(plan.beats):
            current_entities = set(beat.key_entities)
            if index > 0:
                shared_entity = bool(previous_entities & current_entities)
                has_connector = cls._has_any(beat.summary, cls.CAUSAL_CONNECTORS)
                if previous and not shared_entity and not has_connector:
                    issues.append(cls._issue(
                        "weak_beat_causal_bridge",
                        "plot_continuity",
                        "warn",
                        f"节拍 {index + 1} 与上一节拍缺少明显因果承接。",
                        beat_index=index,
                        evidence=[previous, beat.summary],
                        suggestion="用上一节拍的结果触发当前节拍目标，避免拼接感。",
                    ))
            previous = beat.summary
            previous_entities = current_entities
        return issues

    @classmethod
    def _story_contract_issues(
        cls,
        plan_text: str,
        required_terms: list[str],
        forbidden_terms: list[str],
    ) -> list[QualityPreflightIssue]:
        issues: list[QualityPreflightIssue] = []
        used_forbidden = [term for term in forbidden_terms if term and term in plan_text]
        if used_forbidden:
            issues.append(cls._issue(
                "forbidden_story_contract_term",
                "setting_consistency",
                "block",
                "章节计划使用了故事契约禁止的术语或别名。",
                evidence=used_forbidden[:8],
                suggestion="删除禁用术语，改用设定整理中的标准称谓和能力边界。",
            ))
        if required_terms and not any(term in plan_text for term in required_terms):
            issues.append(cls._issue(
                "story_contract_terms_absent_from_plan",
                "story_contract",
                "warn",
                "章节计划没有显式承接故事契约关键词。",
                evidence=required_terms[:8],
                suggestion="如果本章属于主线推进，至少承接一个长期目标、关键线索或标准术语。",
            ))
        return issues

    @classmethod
    def _canonical_constraints(cls, story_contract: dict[str, Any], active_entities: list[dict[str, Any]]) -> list[str]:
        constraints: list[str] = []
        for label, key in (
            ("主角长期目标", "protagonist_goal"),
            ("当前阶段目标", "current_stage_goal"),
            ("核心冲突", "core_conflict"),
            ("对抗压力", "antagonistic_pressure"),
        ):
            value = coerce_to_text(story_contract.get(key)).strip()
            if value:
                constraints.append(f"{label}: {value}")
        for entity in active_entities[:8]:
            name = coerce_to_text(entity.get("name")).strip()
            role = cls._canonical_identity_role(entity)
            if name and role:
                constraints.append(f"{name} 固定身份: {role}")
        return cls._dedupe(constraints)[:12]

    @classmethod
    def _continuity_requirements(cls, required_terms: list[str], canonical_constraints: list[str]) -> list[str]:
        requirements = []
        if required_terms:
            requirements.append("优先承接故事契约关键词: " + "、".join(required_terms[:8]))
        requirements.extend(canonical_constraints[:6])
        return cls._dedupe(requirements)[:10]

    @classmethod
    def _readability_contract(cls, plan: ChapterPlan) -> list[str]:
        contract = [
            "每个 beat 至少用一个可见动作、短对话或身体反应承载选择，不只用旁白总结。",
            "设定信息必须依附当前冲突、物件、环境或人物反应释放，避免整段说明。",
            "桥接细节只服务当前 beat，不新增命名角色、关键证据、能力规则或背景因果。",
        ]
        if plan.target_word_count and plan.beats:
            average = max(1, round(plan.target_word_count / len(plan.beats)))
            contract.append(f"单 beat 约 {average} 字，优先写目标-阻力-选择-停点，不靠后续事件凑字。")
        return contract

    @classmethod
    def _causal_links(cls, plan: ChapterPlan) -> list[str]:
        links = []
        for index in range(len(plan.beats) - 1):
            current = cls._first_clause(plan.beats[index].summary)
            nxt = cls._first_clause(plan.beats[index + 1].summary)
            if current and nxt:
                links.append(f"beat {index + 1} -> beat {index + 2}: {current} 触发/压向 {nxt}")
        return links

    @classmethod
    def _required_terms(cls, story_contract: dict[str, Any]) -> list[str]:
        terms: list[str] = []
        for key in ("must_carry_forward", "key_clues", "required_terms"):
            terms.extend(coerce_to_str_list(story_contract.get(key)))
        for key in ("protagonist_goal", "current_stage_goal", "first_chapter_goal", "core_conflict"):
            terms.extend(cls._salient_terms(coerce_to_text(story_contract.get(key))))
        return cls._dedupe([term for term in terms if len(term) >= 2])[:12]

    @classmethod
    def _forbidden_terms(cls, story_contract: dict[str, Any], active_entities: list[dict[str, Any]]) -> list[str]:
        terms: list[str] = []
        for key in ("forbidden_terms", "forbidden_aliases", "banned_terms"):
            terms.extend(coerce_to_str_list(story_contract.get(key)))
        for entity in active_entities:
            terms.extend(coerce_to_str_list(entity.get("forbidden_aliases")))
            memory = entity.get("memory_snapshot") if isinstance(entity.get("memory_snapshot"), dict) else {}
            canonical = memory.get("canonical_profile") if isinstance(memory.get("canonical_profile"), dict) else {}
            terms.extend(coerce_to_str_list(canonical.get("forbidden_aliases")))
        return cls._dedupe(terms)[:20]

    @classmethod
    def _dimensions(cls, issues: list[QualityPreflightIssue]) -> list[QualityPreflightDimension]:
        result = []
        for name in cls.DIMENSIONS:
            items = [issue for issue in issues if issue.dimension == name]
            status: PreflightStatus = "block" if any(issue.severity == "block" for issue in items) else "warn" if items else "pass"
            result.append(QualityPreflightDimension(name=name, status=status, issues=items))
        return result

    @classmethod
    def _chapter_text(cls, plan: ChapterPlan) -> str:
        parts = [plan.title or ""]
        parts.extend(beat.summary for beat in plan.beats)
        parts.extend(name for beat in plan.beats for name in beat.key_entities)
        parts.extend(item for beat in plan.beats for item in beat.foreshadowings_to_embed)
        return "\n".join(part for part in parts if part)

    @classmethod
    def _generic_repair_indexes(cls, summaries: list[str]) -> list[int]:
        indexes = [
            index for index, summary in enumerate(summaries)
            if any(marker in summary for marker in cls.GENERIC_REPAIR_MARKERS)
        ]
        return indexes if len(indexes) >= 2 else []

    @classmethod
    def _salient_terms(cls, text: str) -> list[str]:
        terms = []
        for token in re.findall(r"[\u4e00-\u9fff]{2,8}", text or ""):
            if token.endswith(("目标", "真相", "线索", "证据", "信物", "遗物", "秘密", "承诺")):
                terms.append(token)
        return terms

    @staticmethod
    def _canonical_identity_role(entity: dict[str, Any]) -> str:
        memory = entity.get("memory_snapshot") if isinstance(entity.get("memory_snapshot"), dict) else {}
        canonical = memory.get("canonical_profile") if isinstance(memory.get("canonical_profile"), dict) else {}
        return coerce_to_text(canonical.get("identity_role")).strip()

    @classmethod
    def _has_any(cls, text: str, terms: tuple[str, ...]) -> bool:
        return any(term in (text or "") for term in terms)

    @staticmethod
    def _first_clause(text: str) -> str:
        parts = [part.strip() for part in re.split(r"[；;。！？!?]", text or "") if part.strip()]
        return parts[0] if parts else ""

    @classmethod
    def _issue(
        cls,
        code: str,
        dimension: PreflightDimensionName,
        severity: Literal["warn", "block"],
        message: str,
        *,
        beat_index: int | None = None,
        evidence: list[str] | None = None,
        suggestion: str = "",
    ) -> QualityPreflightIssue:
        return QualityPreflightIssue(
            code=code,
            dimension=dimension,
            severity=severity,
            beat_index=beat_index,
            message=message,
            evidence=evidence or [],
            suggestion=suggestion,
        )

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen = set()
        result = []
        for value in values:
            text = coerce_to_text(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result
