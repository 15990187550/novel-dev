from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from novel_dev.agents._llm_helpers import coerce_to_str_list, coerce_to_text
from novel_dev.schemas.context import BeatPlan


class CharacterArc(BaseModel):
    name: str
    arc_summary: str
    key_turning_points: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if "name" not in normalized and "character" in normalized:
            normalized["name"] = normalized["character"]
        if "arc_summary" not in normalized:
            for legacy_key in ("arc", "summary", "description"):
                if legacy_key in normalized:
                    normalized["arc_summary"] = normalized[legacy_key]
                    break
        if "key_turning_points" not in normalized:
            for legacy_key in ("turning_points", "turning_point", "beats"):
                if legacy_key in normalized:
                    normalized["key_turning_points"] = normalized[legacy_key]
                    break
        return normalized

    @field_validator("name", "arc_summary", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("key_turning_points", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)


class PlotMilestone(BaseModel):
    act: str
    summary: str
    climax_event: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if "act" not in normalized:
            for legacy_key in ("name", "stage", "title"):
                if legacy_key in normalized:
                    normalized["act"] = normalized[legacy_key]
                    break
        if "summary" not in normalized:
            for legacy_key in ("description", "desc", "content"):
                if legacy_key in normalized:
                    normalized["summary"] = normalized[legacy_key]
                    break
        if "climax_event" not in normalized:
            for legacy_key in ("climax", "turning_event", "hook"):
                if legacy_key in normalized:
                    normalized["climax_event"] = normalized[legacy_key]
                    break
        return normalized

    @field_validator("act", "summary", "climax_event", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)


class SynopsisData(BaseModel):
    title: str
    logline: str
    core_conflict: str
    themes: List[str] = Field(default_factory=list)
    character_arcs: List[CharacterArc] = Field(default_factory=list)
    milestones: List[PlotMilestone] = Field(default_factory=list)
    estimated_volumes: int
    estimated_total_chapters: int
    estimated_total_words: int
    entity_highlights: dict[str, List[str]] = Field(default_factory=dict)
    relationship_highlights: List[str] = Field(default_factory=list)

    @field_validator("title", "logline", "core_conflict", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("themes", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)


class VolumeBeat(BaseModel):
    chapter_id: str
    chapter_number: int
    title: str
    summary: str
    target_word_count: int
    target_mood: str
    key_entities: List[str] = Field(default_factory=list)
    foreshadowings_to_embed: List[str] = Field(default_factory=list)
    foreshadowings_to_recover: List[str] = Field(default_factory=list)
    beats: List[BeatPlan] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        chapter_number = normalized.get("chapter_number") or normalized.get("number") or normalized.get("index")
        if chapter_number is not None and "chapter_number" not in normalized:
            normalized["chapter_number"] = chapter_number
        if "chapter_id" not in normalized and chapter_number is not None:
            normalized["chapter_id"] = f"ch_{chapter_number}"
        if "summary" not in normalized:
            for legacy_key in ("description", "chapter_summary", "content"):
                if legacy_key in normalized:
                    normalized["summary"] = normalized[legacy_key]
                    break
        if "target_word_count" not in normalized:
            for legacy_key in ("word_count", "estimated_words", "target_words"):
                if legacy_key in normalized:
                    normalized["target_word_count"] = normalized[legacy_key]
                    break
        if "target_word_count" not in normalized:
            normalized["target_word_count"] = 3000
        if "target_mood" not in normalized:
            for legacy_key in ("mood", "tone", "emotion"):
                if legacy_key in normalized:
                    normalized["target_mood"] = normalized[legacy_key]
                    break
        if "target_mood" not in normalized:
            normalized["target_mood"] = "tense"
        if "foreshadowings_to_recover" not in normalized:
            for legacy_key in ("planned_foreshadowings", "required_foreshadowings", "recover_foreshadowings"):
                if legacy_key in normalized:
                    normalized["foreshadowings_to_recover"] = normalized[legacy_key]
                    break
        return normalized

    @field_validator("chapter_id", "title", "summary", "target_mood", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)

    @field_validator("key_entities", "foreshadowings_to_embed", "foreshadowings_to_recover", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)


class VolumePlan(BaseModel):
    volume_id: str
    volume_number: int
    title: str
    summary: str
    total_chapters: int
    estimated_total_words: int
    chapters: List[VolumeBeat] = Field(default_factory=list)
    entity_highlights: dict[str, List[str]] = Field(default_factory=dict)
    relationship_highlights: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        volume_number = normalized.get("volume_number") or normalized.get("number") or 1
        if "volume_number" not in normalized:
            normalized["volume_number"] = volume_number
        if "volume_id" not in normalized:
            for legacy_key in ("id", "volume_ref"):
                if legacy_key in normalized:
                    normalized["volume_id"] = normalized[legacy_key]
                    break
        if "volume_id" not in normalized:
            normalized["volume_id"] = f"vol_{volume_number}"
        if "title" not in normalized:
            for legacy_key in ("volume_title", "name"):
                if legacy_key in normalized:
                    normalized["title"] = normalized[legacy_key]
                    break
        if "summary" not in normalized:
            for legacy_key in ("volume_summary", "description", "content"):
                if legacy_key in normalized:
                    normalized["summary"] = normalized[legacy_key]
                    break
        if "estimated_total_words" not in normalized:
            for legacy_key in ("total_words", "word_count", "estimated_words"):
                if legacy_key in normalized:
                    normalized["estimated_total_words"] = normalized[legacy_key]
                    break
        if "estimated_total_words" not in normalized:
            normalized["estimated_total_words"] = 3000
        if "total_chapters" not in normalized:
            for legacy_key in ("chapter_count",):
                if legacy_key in normalized:
                    normalized["total_chapters"] = normalized[legacy_key]
                    break
        if "total_chapters" not in normalized and isinstance(normalized.get("chapters"), list):
            normalized["total_chapters"] = len(normalized["chapters"])
        return normalized

    @field_validator("volume_id", "title", "summary", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)


class SynopsisScoreResult(BaseModel):
    """对 Synopsis 做多维度评分,驱动 Brainstorm 的 self-revise 循环。"""
    overall: int = Field(ge=0, le=100)
    logline_specificity: int = Field(ge=0, le=100, description="logline 是否写成『角色+欲望+阻力+赌注』的具体形式")
    conflict_concreteness: int = Field(ge=0, le=100, description="core_conflict 是否为具体对抗关系而非抽象标签")
    character_arc_depth: int = Field(ge=0, le=100, description="主要角色弧光是否有内在转变与≥3 个转折点")
    structural_turns: int = Field(ge=0, le=100, description="milestones 是否含≥4 个能改变主角处境的转折点")
    hook_strength: int = Field(ge=0, le=100, description="整部结尾是否带明确开放性钩子")
    summary_feedback: str

    @model_validator(mode="before")
    @classmethod
    def _normalize_nested_scores(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        nested_scores = normalized.get("scores")
        if isinstance(nested_scores, dict):
            for key in (
                "overall",
                "logline_specificity",
                "conflict_concreteness",
                "character_arc_depth",
                "structural_turns",
                "hook_strength",
            ):
                if key not in normalized and key in nested_scores:
                    normalized[key] = nested_scores[key]
        if "summary_feedback" not in normalized:
            for legacy_key in ("feedback", "summary", "comment", "comments"):
                if legacy_key in normalized:
                    normalized["summary_feedback"] = normalized[legacy_key]
                    break
        return normalized

    @field_validator("summary_feedback", mode="before")
    @classmethod
    def _coerce_summary_feedback(cls, value: Any) -> str:
        return coerce_to_text(value)


class VolumeScoreResult(BaseModel):
    overall: int = Field(ge=0, le=100)
    outline_fidelity: int = Field(ge=0, le=100)
    character_plot_alignment: int = Field(ge=0, le=100)
    hook_distribution: int = Field(ge=0, le=100)
    foreshadowing_management: int = Field(ge=0, le=100)
    chapter_hooks: int = Field(ge=0, le=100)
    page_turning: int = Field(ge=0, le=100)
    summary_feedback: str

    @field_validator("summary_feedback", mode="before")
    @classmethod
    def _coerce_summary_feedback(cls, value: Any) -> str:
        return coerce_to_text(value)
