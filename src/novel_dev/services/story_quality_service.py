from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from novel_dev.agents._llm_helpers import coerce_to_str_list, coerce_to_text
from novel_dev.schemas.context import BeatPlan, BeatWritingCard, ChapterPlan
from novel_dev.schemas.outline import SynopsisData, VolumeBeat
from novel_dev.services.quality_preflight_service import QualityPreflightService


class SettingQualityReport(BaseModel):
    passed: bool
    missing_sections: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    source_evidence_issues: list[str] = Field(default_factory=list)
    repair_suggestions: list[str] = Field(default_factory=list)


class SynopsisQualityReport(BaseModel):
    passed: bool
    structure_score: int = Field(ge=0, le=100)
    marketability_score: int = Field(ge=0, le=100)
    conflict_score: int = Field(ge=0, le=100)
    character_arc_score: int = Field(ge=0, le=100)
    writability_score: int = Field(ge=0, le=100)
    blocking_issues: list[str] = Field(default_factory=list)
    warning_issues: list[str] = Field(default_factory=list)
    repair_suggestions: list[str] = Field(default_factory=list)


class ChapterWritableCheck(BaseModel):
    passed: bool
    blocking_issues: list[str] = Field(default_factory=list)
    warning_issues: list[str] = Field(default_factory=list)
    repair_suggestions: list[str] = Field(default_factory=list)
    weak_beats: list[int] = Field(default_factory=list)


class ChapterPlanSanityReport(BaseModel):
    passed: bool
    repeated_generic_constraints: list[int] = Field(default_factory=list)
    missing_fields_by_beat: dict[int, list[str]] = Field(default_factory=dict)
    repair_suggestions: list[str] = Field(default_factory=list)


class StoryQualityService:
    """Deterministic preflight checks that keep weak inputs out of prose generation."""

    CONFLICT_TERMS = ("冲突", "对抗", "vs", "VS", "敌", "仇", "阻", "追", "逼", "威胁", "争", "夺", "杀", "发现", "暴露")
    CHOICE_TERMS = ("选择", "决定", "必须", "宁可", "只得", "被迫", "代价", "赌注", "否则")
    HOOK_TERMS = ("悬念", "反转", "逼近", "发现", "暴露", "异动", "裂开", "传来", "出现", "留下")
    PAYOFF_TERMS = ("发现", "拿到", "得到", "搜查", "线索", "真相", "危险信号", "内应", "暴露", "确认")
    ABSTRACT_CONFLICTS = ("正邪对立", "善恶之争", "命运", "成长", "人性", "宿命")
    GENERIC_REPAIR_MARKERS = (
        "必须在继续行动与保全自身之间做出选择",
        "阻力当场升级",
        "失败代价是失去关键线索并暴露处境",
        "结尾留下新的危险信号",
    )
    META_PLAN_MARKERS = (
        "读者应",
        "本节拍的选择、代价或局势变化",
        "原计划受阻",
        "原定路线被迫改道",
        "对手或环境压力逼",
        "继续追查",
        "暂时避险",
        "后续追查中断",
        "线索无法收束",
        "下一步追查失去落点",
        "下一章继续处理",
        "失去处理",
        "主动权",
    )

    @classmethod
    def evaluate_setting_payload(cls, payload: dict[str, Any]) -> SettingQualityReport:
        missing: list[str] = []
        weaknesses: list[str] = []
        suggestions: list[str] = []

        for key in ("worldview", "power_system"):
            if not cls._has_content(payload.get(key)):
                missing.append(key)

        characters = payload.get("character_profiles") or payload.get("characters") or []
        if not characters:
            missing.append("character_profiles")
        elif not cls._characters_have_goal(characters):
            weaknesses.append("核心人物缺少主角目标或当前动机，后续总纲容易变成设定说明。")
            suggestions.append("补充主角目标、当前动机、阻碍和必须付出的代价。")

        conflict_text = cls._join_payload_text(
            payload.get("core_conflicts"),
            payload.get("plot_synopsis"),
            payload.get("worldview"),
            payload.get("factions"),
            payload.get("character_profiles"),
        )
        if not cls._has_conflict(conflict_text):
            weaknesses.append("缺少核心冲突或明确阻力来源。")
            suggestions.append("补充核心冲突：谁阻止主角、争夺什么、失败代价是什么。")

        passed = not missing and not weaknesses
        return SettingQualityReport(
            passed=passed,
            missing_sections=missing,
            weaknesses=weaknesses,
            repair_suggestions=suggestions,
        )

    @classmethod
    def evaluate_synopsis(cls, synopsis: SynopsisData) -> SynopsisQualityReport:
        blocking: list[str] = []
        warnings: list[str] = []
        suggestions: list[str] = []

        conflict_score = 85
        if cls._is_abstract_conflict(synopsis.core_conflict) or not cls._has_conflict(synopsis.core_conflict):
            conflict_score = 45
            blocking.append("总纲缺少具体对抗关系，需要写清谁与谁为了什么发生冲突。")
            suggestions.append("将 core_conflict 改成『主角 vs 具体阻力，为争夺具体目标』。")

        character_arc_score = 85
        if not synopsis.character_arcs or any(len(arc.key_turning_points) < 3 for arc in synopsis.character_arcs[:2]):
            character_arc_score = 60
            warnings.append("主要人物弧光转折不足，正文容易缺少人物选择。")
            suggestions.append("为主角和关键对手补齐至少 3 个会改变关系或信念的转折点。")

        structural_turn_count = cls._count_structural_turns(synopsis)
        structure_score = 85 if structural_turn_count >= 4 else 60
        if structure_score < 75:
            warnings.append(f"总纲可识别结构转折不足 4 个，当前识别到 {structural_turn_count} 个。")
            suggestions.append("补充会改变主角处境、关系、目标、风险等级或关键信息掌握状态的转折。")

        marketability_score = 85
        if not synopsis.volume_outlines:
            marketability_score = 60
            warnings.append("缺少卷级承诺，卷纲生成时容易偏题。")
            suggestions.append("补充每卷目标、主冲突、卷级高潮和卷末钩子。")

        writability_score = min(conflict_score, character_arc_score, marketability_score)
        passed = not blocking and writability_score >= 75 and structure_score >= 70
        return SynopsisQualityReport(
            passed=passed,
            structure_score=structure_score,
            marketability_score=marketability_score,
            conflict_score=conflict_score,
            character_arc_score=character_arc_score,
            writability_score=writability_score,
            blocking_issues=blocking,
            warning_issues=warnings,
            repair_suggestions=suggestions,
        )

    @classmethod
    def evaluate_chapter_writability(cls, chapter: VolumeBeat) -> ChapterWritableCheck:
        blocking: list[str] = []
        warnings: list[str] = []
        suggestions: list[str] = []
        weak_beats: list[int] = []

        if not chapter.beats:
            return ChapterWritableCheck(
                passed=False,
                blocking_issues=["章节没有 beats，无法生成正文。"],
                repair_suggestions=["至少补充 2 个 beats：冲突触发、选择/代价、章末钩子。"],
                weak_beats=[],
            )

        for index, beat in enumerate(chapter.beats):
            text = beat.summary
            lacks_conflict = not cls._has_conflict(text)
            lacks_choice = not cls._has_choice_or_cost(text)
            if lacks_conflict or lacks_choice:
                weak_beats.append(index)
                missing = []
                if lacks_conflict:
                    missing.append("阻力")
                if lacks_choice:
                    missing.append("选择/代价")
                blocking.append(f"节拍 {index + 1} 缺少{'、'.join(missing)}，当前摘要不可直接写正文。")

        repeated_generic_indexes = cls._generic_repair_clause_indexes([beat.summary for beat in chapter.beats])
        if repeated_generic_indexes:
            for index in repeated_generic_indexes:
                if index not in weak_beats:
                    weak_beats.append(index)
            blocking.append(
                "多个节拍重复使用通用硬约束，当前章节计划不可直接写正文，需拆成每个 beat 的具体目标、阻力、选择、代价和停点。"
            )

        last_summary = chapter.beats[-1].summary
        if not cls._has_hook(last_summary):
            warnings.append("最后一个 beat 缺少章末钩子。")
            suggestions.append("在最后一个 beat 增加源于当前线索的悬念、反转、风险逼近、信息暴露或赌注升级。")

        if weak_beats:
            suggestions.append("将弱 beat 改写为：角色目标 + 具体阻力 + 当场选择 + 失败代价 + 停点。")

        return ChapterWritableCheck(
            passed=not blocking,
            blocking_issues=blocking,
            warning_issues=warnings,
            repair_suggestions=suggestions,
            weak_beats=sorted(set(weak_beats)),
        )

    @classmethod
    def build_writing_cards(cls, chapter_plan: ChapterPlan) -> list[BeatWritingCard]:
        total = max(1, len(chapter_plan.beats))
        default_words = max(1, round((chapter_plan.target_word_count or 0) / total)) if chapter_plan.target_word_count else 800
        cards: list[BeatWritingCard] = []
        contract = QualityPreflightService.build_chapter_contract(chapter_plan)
        for index, beat in enumerate(chapter_plan.beats):
            next_summary = chapter_plan.beats[index + 1].summary if index + 1 < len(chapter_plan.beats) else ""
            next_forbidden = cls._first_clause(next_summary) if next_summary else ""
            cards.append(BeatWritingCard(
                beat_index=index,
                source_summary=beat.summary,
                objective=cls._first_clause(beat.summary),
                conflict=cls._extract_conflict(beat.summary),
                turning_point=cls._extract_turning_point(beat.summary),
                stake=cls._extract_stake(beat.summary),
                required_entities=list(beat.key_entities),
                required_facts=cls._extract_required_facts(beat.summary),
                required_payoffs=cls._extract_required_payoffs(beat.summary, list(beat.foreshadowings_to_embed), is_last=index == len(chapter_plan.beats) - 1),
                canonical_constraints=contract.get("canonical_constraints", []),
                continuity_requirements=contract.get("continuity_requirements", []),
                readability_contract=contract.get("readability_contract", []),
                causal_links=cls._links_for_beat(contract.get("causal_links", []), index),
                allowed_bridge_details=cls._allowed_bridge_details(beat.summary, list(beat.key_entities)),
                forbidden_future_events=[next_forbidden] if next_forbidden else [],
                ending_hook=cls._extract_hook(beat.summary, is_last=index == len(chapter_plan.beats) - 1),
                reader_takeaway=cls._reader_takeaway(beat.summary, is_last=index == len(chapter_plan.beats) - 1),
                target_word_count=beat.target_word_count or default_words,
                chapter_role=cls._chapter_role(beat.summary, is_last=index == len(chapter_plan.beats) - 1),
                chapter_purpose=cls._chapter_purpose(beat.summary, next_summary, is_last=index == len(chapter_plan.beats) - 1),
                suspense_mode=cls._suspense_mode(beat.summary),
                foreshadowing_operation=cls._foreshadowing_operation(beat),
                reveal_delta=cls._reveal_delta(beat.summary, list(beat.foreshadowings_to_embed)),
                emotional_shift=cls._emotional_shift(beat.target_mood, chapter_plan.beats[index + 1].target_mood if index + 1 < len(chapter_plan.beats) else ""),
                next_chapter_pressure=cls._first_clause(next_summary) if next_summary else "",
                scene_pressure_lenses=cls._scene_pressure_lenses(beat.summary),
                relationship_subtext_lenses=cls._relationship_subtext_lenses(beat.summary, list(beat.key_entities)),
                prose_texture_lenses=cls._prose_texture_lenses(beat.summary, beat.target_mood),
                freshness_lenses=cls._freshness_lenses(beat.summary, is_last=index == len(chapter_plan.beats) - 1),
                ending_driver_candidates=cls._ending_driver_candidates(beat, is_last=index == len(chapter_plan.beats) - 1),
                humanity_surface_candidates=cls._humanity_surface_candidates(beat.summary, beat.target_mood, list(beat.key_entities)),
                summary_risk_flags=cls._summary_risk_flags(beat.summary, is_last=index == len(chapter_plan.beats) - 1),
            ))
        return cards

    @classmethod
    def build_chapter_plan_sanity_report(cls, chapter_plan: ChapterPlan) -> ChapterPlanSanityReport:
        cards = cls.build_writing_cards(chapter_plan)
        missing_by_beat: dict[int, list[str]] = {}
        for card in cards:
            missing = []
            if not card.objective:
                missing.append("objective")
            if not card.conflict:
                missing.append("conflict")
            if not card.turning_point:
                missing.append("turning_point")
            if not card.stake:
                missing.append("stake")
            if card.beat_index == len(cards) - 1 and not card.ending_hook:
                missing.append("ending_hook")
            if missing:
                missing_by_beat[card.beat_index] = missing

        repeated = cls._generic_repair_clause_indexes([beat.summary for beat in chapter_plan.beats])
        suggestions = []
        if repeated:
            suggestions.append("删除重复通用硬约束，将其拆为各 beat 的具体目标、阻力、选择、代价和停点。")
        if missing_by_beat:
            suggestions.append("补齐写作卡缺失字段后再进入正文生成。")
        return ChapterPlanSanityReport(
            passed=not repeated and not missing_by_beat,
            repeated_generic_constraints=repeated,
            missing_fields_by_beat=missing_by_beat,
            repair_suggestions=suggestions,
        )

    @staticmethod
    def _has_content(value: Any) -> bool:
        if value in (None, "", [], {}):
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    @classmethod
    def _characters_have_goal(cls, characters: Any) -> bool:
        if not isinstance(characters, list):
            return cls._has_content(characters)
        for item in characters:
            if not isinstance(item, dict):
                continue
            if cls._has_content(item.get("goal")) or cls._has_content(item.get("conflict")):
                return True
        return False

    @classmethod
    def _join_payload_text(cls, *values: Any) -> str:
        return "\n".join(cls._stringify(value) for value in values if cls._has_content(value))

    @classmethod
    def _has_conflict(cls, text: Any) -> bool:
        text = cls._stringify(text)
        return any(term in text for term in cls.CONFLICT_TERMS)

    @classmethod
    def _has_choice_or_cost(cls, text: Any) -> bool:
        text = cls._stringify(text)
        return any(term in text for term in cls.CHOICE_TERMS)

    @classmethod
    def _has_hook(cls, text: Any) -> bool:
        text = cls._stringify(text)
        return any(term in text for term in cls.HOOK_TERMS)

    @classmethod
    def _is_abstract_conflict(cls, text: str) -> bool:
        cleaned = coerce_to_text(text)
        return any(item in cleaned for item in cls.ABSTRACT_CONFLICTS) and not re.search(r"vs|VS|对抗|争夺|阻止|追杀|逼迫", cleaned)

    STRUCTURAL_TURN_PATTERNS: dict[str, tuple[str, ...]] = {
        "loss_or_fall": ("覆灭", "失去", "沦为", "废", "重伤", "败亡", "被逐", "陷害"),
        "alliance_or_betrayal": ("结盟", "联手", "联盟", "背叛", "破裂", "拔剑指向", "护他", "押上身份"),
        "clue_or_reveal": ("发现", "得知", "确认", "揭开", "揭露", "真相", "证据", "线索", "浮出水面"),
        "threat_escalation": ("刺杀", "围杀", "追捕", "追杀", "陷阱", "被迫逃", "逃入", "逃亡", "拿下"),
        "power_shift": ("能力变化", "暴露实力", "实力变化", "获得", "关键资源", "反噬", "失控"),
        "identity_or_world_change": ("身世", "身份", "宿主", "封印", "异常物", "秩序根基", "世界边界", "崩塌"),
        "choice_or_sacrifice": ("必须选择", "选择", "放弃", "代价", "以凡人之躯", "自残", "牺牲"),
    }

    @classmethod
    def _count_structural_turns(cls, synopsis: SynopsisData) -> int:
        matched_categories: set[str] = set()
        for milestone in synopsis.milestones:
            text = cls._stringify([milestone.act, milestone.summary, milestone.climax_event])
            milestone_categories = {
                category
                for category, patterns in cls.STRUCTURAL_TURN_PATTERNS.items()
                if any(pattern in text for pattern in patterns)
            }
            if milestone_categories:
                matched_categories.update(milestone_categories)
        return len(matched_categories)

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return " ".join(StoryQualityService._stringify(item) for item in value.values())
        if isinstance(value, list):
            return " ".join(StoryQualityService._stringify(item) for item in value)
        return str(value)

    @staticmethod
    def _first_clause(text: str) -> str:
        cleaned = coerce_to_text(text).strip()
        for sep in ("；", ";", "，", ",", "。"):
            if sep in cleaned:
                return cleaned.split(sep, 1)[0].strip()
        return cleaned

    @classmethod
    def _extract_conflict(cls, text: str) -> str:
        clauses = cls._contract_clauses(text)
        return next((clause for clause in clauses if cls._has_conflict(clause)), "")

    @classmethod
    def _extract_turning_point(cls, text: str) -> str:
        clauses = cls._contract_clauses(text)
        return next((clause for clause in clauses if cls._has_choice_or_cost(clause)), clauses[-1] if clauses else "")

    @classmethod
    def _extract_stake(cls, text: str) -> str:
        clauses = cls._contract_clauses(text)
        return next(
            (
                clause for clause in clauses
                if any(term in clause for term in ("代价", "失败", "否则", "暴露", "失去", "错过", "被逐", "受罚"))
            ),
            "",
        )

    @classmethod
    def _extract_hook(cls, text: str, *, is_last: bool) -> str:
        clauses = cls._contract_clauses(text)
        hook = next((clause for clause in reversed(clauses) if cls._has_hook(clause)), "")
        if hook:
            return hook
        return clauses[-1] if is_last and clauses else ""

    @classmethod
    def _extract_required_facts(cls, text: str) -> list[str]:
        clauses = cls._contract_clauses(text)
        return cls._dedupe_text(cls._shorten_contract_clause(clause) for clause in clauses)[:4]

    @classmethod
    def _extract_required_payoffs(cls, text: str, foreshadowings: list[str], *, is_last: bool) -> list[str]:
        clauses = cls._contract_clauses(text)
        payoffs = [
            cls._shorten_contract_clause(clause)
            for clause in clauses
            if any(term in clause for term in cls.PAYOFF_TERMS)
        ]
        if is_last and clauses and not payoffs:
            hook = cls._extract_hook(text, is_last=True)
            if hook and not cls._is_generic_repair_clause(hook):
                payoffs.append(cls._shorten_contract_clause(hook))
        for item in foreshadowings:
            cleaned = coerce_to_text(item).strip()
            if cleaned:
                payoffs.append(cls._shorten_contract_clause(cleaned))
        return cls._dedupe_text(payoffs)[:5]

    @classmethod
    def _allowed_bridge_details(cls, text: str, key_entities: list[str]) -> list[str]:
        details = [
            "可使用已有人物的短动作、视线、停顿、沉默或身体反应承接当前冲突。",
            "可使用当前场景中的声音、灯火、门窗、脚步、风声等环境细节制造轻微危险信号。",
        ]
        if key_entities:
            details.append("桥接细节优先落在已列实体上: " + "、".join(key_entities[:4]))
        if cls._has_choice_or_cost(text):
            details.append("选择必须通过当场动作或一句短对话落地，不能只用旁白总结。")
        return details

    @classmethod
    def strip_generic_repair_clauses(cls, text: str) -> str:
        clauses = cls._split_clauses(text)
        kept = [clause for clause in clauses if not cls._is_generic_repair_clause(clause)]
        if not kept:
            return coerce_to_text(text).strip().rstrip("。！？!?；;")
        return "；".join(kept).strip().rstrip("。！？!?；;")

    @classmethod
    def _generic_repair_clause_indexes(cls, summaries: list[str]) -> list[int]:
        indexes = []
        for index, summary in enumerate(summaries):
            if any(cls._is_generic_repair_clause(clause) for clause in cls._split_clauses(summary)):
                indexes.append(index)
        return indexes if len(indexes) >= 2 else []

    @classmethod
    def _is_generic_repair_clause(cls, text: str) -> bool:
        normalized = coerce_to_text(text)
        marker_count = sum(1 for marker in cls.GENERIC_REPAIR_MARKERS if marker in normalized)
        return marker_count >= 1 or (
            "继续追查" in normalized
            and "保全自身" in normalized
            and ("危险信号" in normalized or "失败代价" in normalized)
        )

    @staticmethod
    def _shorten_contract_clause(text: str, limit: int = 80) -> str:
        cleaned = coerce_to_text(text).strip().strip("。！？!?；;，, ")
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[:limit].rstrip("，,；;、 ") + "..."

    @classmethod
    def _reader_takeaway(cls, text: str, *, is_last: bool) -> str:
        hook = cls._extract_hook(text, is_last=is_last)
        if is_last:
            if hook:
                return f"本章当场结果落到正文里，并以这个停点牵引后续：{hook}"
            return "本章当场冲突有明确结果，并留下新的问题或压力。"
        turning_point = cls._extract_turning_point(text)
        if turning_point:
            return f"本节拍呈现清楚的选择、代价或局势变化：{turning_point}"
        return "本节拍呈现清楚的目标、阻力和推进结果。"

    @classmethod
    def _chapter_role(cls, text: str, *, is_last: bool) -> str:
        if is_last:
            return "章末牵引"
        if cls._has_conflict(text):
            return "冲突推进"
        if cls._has_hook(text) or any(term in text for term in ("发现", "确认", "得知", "暴露")):
            return "信息揭示"
        if cls._has_choice_or_cost(text):
            return "选择转折"
        return "承接铺垫"

    @classmethod
    def _chapter_purpose(cls, text: str, next_summary: str, *, is_last: bool) -> str:
        current = cls._shorten_contract_clause(cls._first_clause(text) or text)
        if next_summary:
            nxt = cls._shorten_contract_clause(cls._first_clause(next_summary))
            return f"{current}，并压向后续：{nxt}" if nxt else current
        if is_last:
            hook = cls._extract_hook(text, is_last=True)
            return f"收束本章当场结果，并留下后续压力：{hook}" if hook else "收束本章当场结果，并保留后续压力。"
        return current

    @classmethod
    def _suspense_mode(cls, text: str) -> str:
        if any(term in text for term in ("追", "堵", "围", "逼", "迟疑", "搜身", "启动")):
            return "行动压力"
        if any(term in text for term in ("发现", "确认", "说明", "得知", "真相", "线索")):
            return "信息差"
        if any(term in text for term in ("恶化", "危险", "盯上", "暴露", "失去")):
            return "风险逼近"
        if any(term in text for term in ("不服", "怀疑", "试探", "背叛", "结盟")):
            return "关系压力"
        return "情绪余波"

    @classmethod
    def _foreshadowing_operation(cls, beat) -> str:
        foreshadowings = [item for item in getattr(beat, "foreshadowings_to_embed", []) if str(item).strip()]
        if foreshadowings:
            return "嵌入/强化: " + "；".join(cls._shorten_contract_clause(item) for item in foreshadowings[:3])
        hook = cls._extract_hook(getattr(beat, "summary", ""), is_last=True)
        if hook:
            return "沿当前停点保留后续牵引: " + cls._shorten_contract_clause(hook)
        return "不额外制造伏笔，优先兑现当前场景因果。"

    @classmethod
    def _reveal_delta(cls, text: str, foreshadowings: list[str]) -> str:
        clauses = cls._contract_clauses(text)
        reveal_clauses = [
            clause for clause in clauses
            if any(term in clause for term in ("发现", "确认", "说明", "得知", "暴露", "变亮", "启动", "线索"))
        ]
        reveal_clauses.extend(str(item).strip() for item in foreshadowings if str(item).strip())
        if reveal_clauses:
            return "；".join(cls._shorten_contract_clause(item) for item in cls._dedupe_text(reveal_clauses)[:3])
        return cls._shorten_contract_clause(cls._first_clause(text) or text)

    @staticmethod
    def _emotional_shift(current_mood: str, next_mood: str) -> str:
        current = coerce_to_text(current_mood).strip()
        nxt = coerce_to_text(next_mood).strip()
        if current and nxt and current != nxt:
            return f"{current} -> {nxt}"
        return current or nxt

    @classmethod
    def _scene_pressure_lenses(cls, text: str) -> list[str]:
        clauses = cls._contract_clauses(text)
        conflict = cls._extract_conflict(text)
        stake = cls._extract_stake(text)
        lenses = []
        if conflict:
            lenses.append(f"可选: 让压力落在当前阻力的距离、动作限制或暴露风险上：{cls._shorten_contract_clause(conflict)}。")
        if stake:
            lenses.append(f"可选: 把代价写成角色当场会失去、暴露或错过的具体后果：{cls._shorten_contract_clause(stake)}。")
        if clauses:
            lenses.append(f"优先: 用已有动作和物件推进局势，不另起新危机：{cls._shorten_contract_clause(clauses[0])}。")
        return cls._dedupe_text(lenses)[:3]

    @classmethod
    def _relationship_subtext_lenses(cls, text: str, key_entities: list[str]) -> list[str]:
        entities = [str(item).strip() for item in key_entities if str(item).strip()]
        lenses = []
        if len(entities) >= 2:
            lenses.append(f"可选: 用{entities[0]}与{entities[1]}的站位、停顿、视线、避让或未说完的反应承载试探。")
        elif entities:
            lenses.append(f"可选: 让{entities[0]}的保留、迟疑或动作变化显出关系压力。")
        if any(term in text for term in ("怀疑", "试探", "不服", "背叛", "结盟", "堵")):
            lenses.append("可选: 信息先经过误判、保留或代价再浮出；对话只是工具，不是硬指标。")
        return cls._dedupe_text(lenses)[:3]

    @classmethod
    def _prose_texture_lenses(cls, text: str, target_mood: str) -> list[str]:
        clauses = cls._contract_clauses(text)
        mood = coerce_to_text(target_mood).strip()
        lenses = []
        if mood:
            lenses.append(f"优先: 把{mood}落到身体反应、手边物件、空间阻隔或行动受限上。")
        if clauses:
            lenses.append(f"可以: 从这一句里挑一个可触摸的细节放大，而不是铺满抽象感受：{cls._shorten_contract_clause(clauses[0])}。")
        lenses.append("可选: 长句只用于承接情绪，关键动作和风险变化用短句推进。")
        return cls._dedupe_text(lenses)[:3]

    @classmethod
    def _freshness_lenses(cls, text: str, *, is_last: bool) -> list[str]:
        mode = cls._suspense_mode(text)
        lenses = [f"避免复用上一章同类停点；本段优先从{mode}里找新的表现角度。"]
        if is_last:
            lenses.append("章末可低声量收束；用信息变化、关系变化、行动压力或选择余波推进关注点，不机械加异象。")
        else:
            lenses.append("节拍结尾停在当前目标、阻力或选择的余波上，不提前展开后续核心事件。")
        return lenses

    @classmethod
    def _ending_driver_candidates(cls, beat: BeatPlan, *, is_last: bool) -> list[str]:
        if not is_last:
            return []
        clauses = cls._contract_clauses(beat.summary)
        entities = [str(item).strip() for item in beat.key_entities if str(item).strip()]
        concrete_entities = [
            item for item in entities
            if not cls._looks_like_abstract_topic(item)
        ]
        candidates: list[str] = []
        for clause in reversed(clauses):
            if cls._clause_has_concrete_driver(clause, concrete_entities):
                candidates.append(cls._driver_from_clause(clause, concrete_entities))
        for item in beat.foreshadowings_to_embed:
            cleaned = cls.sanitize_prompt_text(item)
            if cleaned and not cls._looks_like_abstract_topic(cleaned):
                candidates.append(f"已埋伏笔在章末留下可感知余波：{cls._shorten_contract_clause(cleaned)}")
        return cls._dedupe_text(candidates)[:3]

    @classmethod
    def _humanity_surface_candidates(cls, text: str, target_mood: str, key_entities: list[str]) -> list[str]:
        clauses = cls._contract_clauses(text)
        entities = [item for item in key_entities if item and not cls._looks_like_abstract_topic(item)]
        candidates: list[str] = []
        if entities:
            candidates.append(f"让{entities[0]}的动作停顿、身体反应或手边物件承载情绪变化")
        if len(entities) >= 2:
            candidates.append(f"用{entities[0]}与{entities[1]}之间的视线、距离、避让或未出口反应呈现关系压力")
        if clauses:
            candidates.append(f"从当前事实挑一个可触摸细节落地：{cls._shorten_contract_clause(clauses[0])}")
        mood = coerce_to_text(target_mood).strip()
        if mood:
            candidates.append(f"把{mood}写成场内可见后果，而不是作者替人物下判断")
        return cls._dedupe_text(candidates)[:4]

    @classmethod
    def _summary_risk_flags(cls, text: str, *, is_last: bool) -> list[str]:
        flags: list[str] = []
        raw_clauses = cls._split_clauses(text)
        if any(cls._is_meta_plan_clause(clause) or cls._looks_like_abstract_ending_driver(clause) for clause in raw_clauses):
            flags.append("计划中存在抽象或元叙述句，不可直接写成正文。")
        if is_last and not cls._ending_driver_candidates(
            BeatPlan(summary=text, target_mood="", key_entities=[], foreshadowings_to_embed=[]),
            is_last=True,
        ):
            flags.append("章末缺少可直接落地的牵引来源。")
        return cls._dedupe_text(flags)

    @classmethod
    def _clause_has_concrete_driver(cls, clause: str, entities: list[str]) -> bool:
        if cls._looks_like_abstract_ending_driver(clause):
            return False
        if cls._looks_like_static_exit_closure(clause):
            return False
        concrete_surface_markers = (
            "手", "眼", "门", "血", "纸", "脚步", "视线", "声音", "窗", "袖", "袋",
            "书", "信", "钥", "令", "牌", "灯", "火", "影", "伤", "药", "刀", "剑",
        )
        observable_change_markers = (
            "发现", "听见", "传来", "出现", "留下", "暴露", "拦", "堵", "盯", "追",
            "逼", "夺", "失去", "拿到", "换到", "交出", "经过", "提醒", "裂", "亮",
            "响", "停", "回头", "靠近", "收紧", "握", "摸", "刺痛", "变",
        )
        has_entity = bool(entities and any(entity in clause for entity in entities))
        has_surface = any(term in clause for term in concrete_surface_markers)
        has_change = any(term in clause for term in observable_change_markers)
        if has_entity and has_change:
            return True
        return has_surface and has_change

    @classmethod
    def _driver_from_clause(cls, clause: str, entities: list[str]) -> str:
        shortened = cls._shorten_contract_clause(clause)
        matched = [entity for entity in entities if entity in clause]
        if matched:
            return f"{'、'.join(matched[:2])}在章末留下可见后果：{shortened}"
        return f"章末沿已出现材料留下可见后果：{shortened}"

    @classmethod
    def _looks_like_abstract_ending_driver(cls, text: str) -> bool:
        normalized = coerce_to_text(text)
        if not normalized:
            return True
        markers = (
            "未解变化压到章末",
            "下一步继续处理",
            "下一步行动",
            "失去落点",
            "明确停点",
            "后续行动就会",
            "后续行动",
            "当场收束",
            "未解决的阻力",
            "压回眼前",
            "读者",
        )
        paired_abstract = (
            "接近" in normalized
            and any(marker in normalized for marker in ("停点", "未解", "阻力", "困境", "事件", "目标"))
        )
        return any(marker in normalized for marker in markers) or paired_abstract or cls._is_meta_plan_clause(normalized)

    @staticmethod
    def _looks_like_static_exit_closure(text: str) -> bool:
        normalized = coerce_to_text(text)
        if not normalized:
            return True
        exit_markers = (
            "离去",
            "走远",
            "快步",
            "转身",
            "低头",
            "脚步没停",
        )
        driver_markers = (
            "发现",
            "听见",
            "传来",
            "出现",
            "暴露",
            "拦",
            "堵",
            "追",
            "逼",
            "夺",
            "失去",
            "拿到",
            "换到",
            "交出",
            "提醒",
            "裂",
            "亮",
            "响",
            "刺痛",
            "变",
        )
        return any(marker in normalized for marker in exit_markers) and not any(
            marker in normalized for marker in driver_markers
        )

    @staticmethod
    def _looks_like_abstract_topic(text: str) -> bool:
        normalized = coerce_to_text(text).strip("“”")
        return any(marker in normalized for marker in ("困境", "旧案", "停点", "线索", "事件", "目标")) and len(normalized) <= 8

    @classmethod
    def _contract_clauses(cls, text: str) -> list[str]:
        clauses = []
        for clause in cls._split_clauses(text):
            cleaned = cls._clean_contract_clause(clause)
            if not cleaned:
                continue
            if (
                cls._is_generic_repair_clause(cleaned)
                or cls._is_meta_plan_clause(cleaned)
                or cls._looks_like_abstract_ending_driver(cleaned)
                or cls._looks_like_static_exit_closure(cleaned)
            ):
                continue
            clauses.append(cleaned)
        return cls._dedupe_text(clauses)

    @classmethod
    def sanitize_prompt_text(cls, text: Any) -> str:
        raw = coerce_to_text(text).strip()
        if not raw:
            return ""
        clauses = cls._contract_clauses(raw)
        if clauses:
            return "；".join(clauses)
        return cls.strip_generic_repair_clauses(raw).strip()

    @classmethod
    def sanitize_prompt_payload(cls, value: Any) -> Any:
        text_keys = {
            "summary",
            "objective",
            "conflict",
            "turning_point",
            "stake",
            "ending_hook",
            "reader_takeaway",
            "scene_state",
            "next_beat_hook",
        }
        if isinstance(value, dict):
            return {
                key: cls.sanitize_prompt_text(item) if key in text_keys else cls.sanitize_prompt_payload(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls.sanitize_prompt_payload(item) for item in value]
        return value

    @classmethod
    def _clean_contract_clause(cls, text: str) -> str:
        cleaned = coerce_to_text(text).strip().strip("。！？!?；;，, ")
        if not cleaned:
            return ""
        replacements = (
            ("失败代价是", ""),
            ("结尾听见", "听见"),
            ("结尾发现", "发现"),
            ("结尾出现", "出现"),
            ("结尾传来", "传来"),
            ("必须决定是否", "判断是否"),
            ("必须决定", "决定"),
            ("必须权衡", "权衡"),
            ("必须在", "在"),
            ("读者应明确获得", ""),
            ("读者应看清", ""),
        )
        for old, new in replacements:
            cleaned = cleaned.replace(old, new)
        return cleaned.strip("。！？!?；;，, ")

    @classmethod
    def _is_meta_plan_clause(cls, text: str) -> bool:
        normalized = coerce_to_text(text)
        if not normalized:
            return True
        if any(marker in normalized for marker in cls.META_PLAN_MARKERS):
            return True
        if "结尾留下" in normalized:
            return True
        if "线索" in normalized and any(marker in normalized for marker in ("暂时避险", "继续靠近", "继续追查")):
            return True
        return False

    @staticmethod
    def _links_for_beat(links: list[str], beat_index: int) -> list[str]:
        prefix_before = f"beat {beat_index} ->"
        prefix_after = f"beat {beat_index + 1} ->"
        return [
            link for link in links
            if link.startswith(prefix_before) or link.startswith(prefix_after)
        ][:2]

    @staticmethod
    def _dedupe_text(items) -> list[str]:
        seen = set()
        result = []
        for item in items:
            cleaned = coerce_to_text(item).strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            result.append(cleaned)
        return result

    @staticmethod
    def _split_clauses(text: str) -> list[str]:
        return [part.strip() for part in re.split(r"[；;。]", coerce_to_text(text)) if part.strip()]
