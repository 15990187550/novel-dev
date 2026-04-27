from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator

from novel_dev.agents._llm_helpers import coerce_to_str_list, coerce_to_text


class DimensionScore(BaseModel):
    name: str
    score: int
    comment: str

    @field_validator("name", "comment", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)


class DimensionIssue(BaseModel):
    """具体的可操作问题,用于指导 Editor 定点修改。"""
    dim: str  # plot_tension / characterization / readability / consistency / humanity
    beat_idx: Optional[int] = None  # None 表示跨 beat 的整章问题
    problem: str  # 具体问题描述(不要抽象标签)
    suggestion: str  # 具体修改建议

    @field_validator("dim", "problem", "suggestion", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        return coerce_to_text(value)


class ScoreResult(BaseModel):
    overall: int
    dimensions: List[DimensionScore]
    summary_feedback: str
    per_dim_issues: List[DimensionIssue] = Field(default_factory=list)

    @field_validator("summary_feedback", mode="before")
    @classmethod
    def _coerce_summary_feedback(cls, value: Any) -> str:
        return coerce_to_text(value)


class FastReviewReport(BaseModel):
    word_count_ok: bool
    consistency_fixed: bool
    ai_flavor_reduced: bool
    beat_cohesion_ok: bool
    language_style_ok: bool = True
    notes: List[str] = Field(default_factory=list)

    @field_validator("notes", mode="before")
    @classmethod
    def _coerce_notes(cls, value: Any) -> List[str]:
        return coerce_to_str_list(value)
