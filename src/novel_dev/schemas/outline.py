from typing import List, Optional
from pydantic import BaseModel, Field

from novel_dev.schemas.context import BeatPlan


class CharacterArc(BaseModel):
    name: str
    arc_summary: str
    key_turning_points: List[str] = Field(default_factory=list)


class PlotMilestone(BaseModel):
    act: str
    summary: str
    climax_event: Optional[str] = None


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


class VolumePlan(BaseModel):
    volume_id: str
    volume_number: int
    title: str
    summary: str
    total_chapters: int
    estimated_total_words: int
    chapters: List[VolumeBeat] = Field(default_factory=list)


class SynopsisScoreResult(BaseModel):
    """对 Synopsis 做多维度评分,驱动 Brainstorm 的 self-revise 循环。"""
    overall: int = Field(ge=0, le=100)
    logline_specificity: int = Field(ge=0, le=100, description="logline 是否写成『角色+欲望+阻力+赌注』的具体形式")
    conflict_concreteness: int = Field(ge=0, le=100, description="core_conflict 是否为具体对抗关系而非抽象标签")
    character_arc_depth: int = Field(ge=0, le=100, description="主要角色弧光是否有内在转变与≥3 个转折点")
    structural_turns: int = Field(ge=0, le=100, description="milestones 是否含≥4 个能改变主角处境的转折点")
    hook_strength: int = Field(ge=0, le=100, description="整部结尾是否带明确开放性钩子")
    summary_feedback: str


class VolumeScoreResult(BaseModel):
    overall: int = Field(ge=0, le=100)
    outline_fidelity: int = Field(ge=0, le=100)
    character_plot_alignment: int = Field(ge=0, le=100)
    hook_distribution: int = Field(ge=0, le=100)
    foreshadowing_management: int = Field(ge=0, le=100)
    chapter_hooks: int = Field(ge=0, le=100)
    page_turning: int = Field(ge=0, le=100)
    summary_feedback: str
