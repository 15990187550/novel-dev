from typing import List
from pydantic import BaseModel, Field


class DimensionScore(BaseModel):
    name: str
    score: int
    comment: str


class ScoreResult(BaseModel):
    overall: int
    dimensions: List[DimensionScore]
    summary_feedback: str


class FastReviewReport(BaseModel):
    word_count_ok: bool
    consistency_fixed: bool
    ai_flavor_reduced: bool
    beat_cohesion_ok: bool
    notes: List[str] = Field(default_factory=list)
