from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator

from novel_dev.agents._llm_helpers import coerce_to_str_list, coerce_to_text
from novel_dev.schemas.context import BeatPlan


class CharacterArc(BaseModel):
    name: str
    arc_summary: str
    key_turning_points: List[str] = Field(default_factory=list)

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
