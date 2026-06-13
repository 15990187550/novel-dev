"""Persistence and retrieval of attempt-level chapter quality metrics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import ChapterQualityMetric


@dataclass
class QualityMetricInput:
    chapter_id: str
    novel_id: str
    phase: str
    gate_status: str
    attempt_index: int = 0
    overall_score: Optional[int] = None
    dimension_scores: Optional[dict] = None
    dimension_feedback: Optional[dict] = None
    blocking_items: Optional[list] = None
    warning_items: Optional[list] = None
    issue_codes: Optional[list] = None
    repairable: Optional[bool] = None
    latency_ms: Optional[int] = None
    token_usage: Optional[dict] = None
    model_version: Optional[str] = None
    prompt_version: Optional[str] = None


class QualityMetricsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def record(self, data: QualityMetricInput) -> ChapterQualityMetric:
        metric = ChapterQualityMetric(
            chapter_id=data.chapter_id,
            novel_id=data.novel_id,
            phase=data.phase,
            attempt_index=data.attempt_index,
            overall_score=data.overall_score,
            dimension_scores=data.dimension_scores,
            dimension_feedback=data.dimension_feedback,
            gate_status=data.gate_status,
            blocking_items=data.blocking_items,
            warning_items=data.warning_items,
            issue_codes=data.issue_codes,
            repairable=data.repairable,
            latency_ms=data.latency_ms,
            token_usage=data.token_usage,
            model_version=data.model_version,
            prompt_version=data.prompt_version,
        )
        self.session.add(metric)
        await self.session.flush()
        return metric