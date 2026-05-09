from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from novel_dev.agents._llm_helpers import coerce_to_str_list, coerce_to_text
from novel_dev.schemas.context import BeatWritingCard, ChapterPlan
from novel_dev.schemas.outline import SynopsisData, VolumeBeat


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


class StoryQualityService:
    """Deterministic preflight checks that keep weak inputs out of prose generation."""

    CONFLICT_TERMS = ("冲突", "对抗", "vs", "VS", "敌", "仇", "阻", "追", "逼", "威胁", "争", "夺", "杀", "发现", "暴露")
    CHOICE_TERMS = ("选择", "决定", "必须", "宁可", "只得", "被迫", "代价", "赌注", "否则")
    HOOK_TERMS = ("悬念", "反转", "追兵", "逼近", "发现", "暴露", "异动", "裂开", "传来", "出现", "留下")
    ABSTRACT_CONFLICTS = ("正邪对立", "善恶之争", "命运", "成长", "人性", "宿命")

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

        structure_score = 85 if len(synopsis.milestones) >= 4 else 60
        if structure_score < 75:
            warnings.append("总纲里程碑不足 4 个，长线节奏容易松散。")

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

        last_summary = chapter.beats[-1].summary
        if not cls._has_hook(last_summary):
            warnings.append("最后一个 beat 缺少章末钩子。")
            suggestions.append("在最后一个 beat 增加悬念、反转、追兵逼近、秘密暴露或赌注升级。")

        if weak_beats:
            suggestions.append("将弱 beat 改写为：角色目标 + 具体阻力 + 当场选择 + 失败代价 + 停点。")

        return ChapterWritableCheck(
            passed=not blocking,
            blocking_issues=blocking,
            warning_issues=warnings,
            repair_suggestions=suggestions,
            weak_beats=weak_beats,
        )

    @classmethod
    def build_writing_cards(cls, chapter_plan: ChapterPlan) -> list[BeatWritingCard]:
        total = max(1, len(chapter_plan.beats))
        default_words = max(1, round((chapter_plan.target_word_count or 0) / total)) if chapter_plan.target_word_count else 800
        cards: list[BeatWritingCard] = []
        for index, beat in enumerate(chapter_plan.beats):
            next_summary = chapter_plan.beats[index + 1].summary if index + 1 < len(chapter_plan.beats) else ""
            next_forbidden = cls._first_clause(next_summary) if next_summary else ""
            cards.append(BeatWritingCard(
                beat_index=index,
                objective=cls._first_clause(beat.summary),
                conflict=cls._extract_conflict(beat.summary),
                turning_point=cls._extract_turning_point(beat.summary),
                required_entities=list(beat.key_entities),
                required_facts=[beat.summary],
                forbidden_future_events=[next_forbidden] if next_forbidden else [],
                ending_hook=cls._extract_hook(beat.summary, is_last=index == len(chapter_plan.beats) - 1),
                target_word_count=beat.target_word_count or default_words,
            ))
        return cards

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
        clauses = cls._split_clauses(text)
        return next((clause for clause in clauses if cls._has_conflict(clause)), "")

    @classmethod
    def _extract_turning_point(cls, text: str) -> str:
        clauses = cls._split_clauses(text)
        return next((clause for clause in clauses if cls._has_choice_or_cost(clause)), clauses[-1] if clauses else "")

    @classmethod
    def _extract_hook(cls, text: str, *, is_last: bool) -> str:
        clauses = cls._split_clauses(text)
        hook = next((clause for clause in reversed(clauses) if cls._has_hook(clause)), "")
        if hook:
            return hook
        return clauses[-1] if is_last and clauses else ""

    @staticmethod
    def _split_clauses(text: str) -> list[str]:
        return [part.strip() for part in re.split(r"[；;。]", coerce_to_text(text)) if part.strip()]
