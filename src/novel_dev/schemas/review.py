from typing import List, Optional
from pydantic import BaseModel, Field


class DimensionScore(BaseModel):
    name: str
    score: int
    comment: str


class DimensionIssue(BaseModel):
    """具体的可操作问题,用于指导 Editor 定点修改。"""
    dim: str  # plot_tension / characterization / readability / consistency / humanity
    beat_idx: Optional[int] = None  # None 表示跨 beat 的整章问题
    problem: str  # 具体问题描述(不要抽象标签)
    suggestion: str  # 具体修改建议


class ScoreResult(BaseModel):
    overall: int
    dimensions: List[DimensionScore]
    summary_feedback: str
    per_dim_issues: List[DimensionIssue] = Field(default_factory=list)


class FastReviewReport(BaseModel):
    word_count_ok: bool
    consistency_fixed: bool
    ai_flavor_reduced: bool
    beat_cohesion_ok: bool
    notes: List[str] = Field(default_factory=list)
