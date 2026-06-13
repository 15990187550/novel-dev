"""Persistence and retrieval of attempt-level chapter quality metrics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
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

    async def get_trends(
        self,
        novel_id: str,
        dimension: str = "overall",
        phase: str = "final",
        from_chapter: Optional[int] = None,
        to_chapter: Optional[int] = None,
    ) -> list[dict]:
        """Return per-chapter score points for trend analysis.

        Tries chapter_quality_metrics first; falls back to chapters.score_overall
        (or score_breakdown[dimension]) for chapters that have no metric row.
        """
        from novel_dev.db.models import Chapter

        metric_rows = await self._query_metrics(novel_id, phase, from_chapter, to_chapter)
        metric_by_chapter = {m.chapter_id: m for m in metric_rows}

        chapter_stmt = select(Chapter).where(Chapter.novel_id == novel_id)
        if from_chapter is not None:
            chapter_stmt = chapter_stmt.where(Chapter.chapter_number >= from_chapter)
        if to_chapter is not None:
            chapter_stmt = chapter_stmt.where(Chapter.chapter_number <= to_chapter)
        chapter_stmt = chapter_stmt.order_by(Chapter.chapter_number)
        chapters = (await self.session.execute(chapter_stmt)).scalars().all()

        out = []
        for ch in chapters:
            if ch.id in metric_by_chapter:
                m = metric_by_chapter[ch.id]
                value = m.overall_score if dimension == "overall" else (m.dimension_scores or {}).get(dimension)
                out.append({
                    "chapter_id": ch.id,
                    "chapter_number": ch.chapter_number,
                    "title": ch.title,
                    "value": value,
                    "gate_status": m.gate_status,
                    "issue_codes": m.issue_codes or [],
                    "source": "metrics",
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                })
            elif dimension == "overall" and ch.score_overall is not None:
                out.append({
                    "chapter_id": ch.id,
                    "chapter_number": ch.chapter_number,
                    "title": ch.title,
                    "value": ch.score_overall,
                    "gate_status": ch.quality_status or "unchecked",
                    "issue_codes": (ch.quality_reasons or {}).get("warning_items", []),
                    "source": "chapter_fallback",
                    "created_at": ch.quality_checked_at.isoformat() if ch.quality_checked_at else None,
                })
            elif dimension != "overall" and ch.score_breakdown:
                value = (ch.score_breakdown or {}).get(dimension, {}).get("score")
                if value is not None:
                    out.append({
                        "chapter_id": ch.id,
                        "chapter_number": ch.chapter_number,
                        "title": ch.title,
                        "value": value,
                        "gate_status": ch.quality_status or "unchecked",
                        "issue_codes": (ch.quality_reasons or {}).get("warning_items", []),
                        "source": "chapter_fallback",
                        "created_at": ch.quality_checked_at.isoformat() if ch.quality_checked_at else None,
                    })
        return out

    async def _query_metrics(
        self,
        novel_id: str,
        phase: str,
        from_chapter: Optional[int],
        to_chapter: Optional[int],
    ) -> list[ChapterQualityMetric]:
        stmt = select(ChapterQualityMetric).where(
            ChapterQualityMetric.novel_id == novel_id,
            ChapterQualityMetric.phase == phase,
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        if from_chapter is None and to_chapter is None:
            return rows
        from novel_dev.db.models import Chapter
        ch_stmt = select(Chapter.id, Chapter.chapter_number).where(Chapter.novel_id == novel_id)
        ch_map = dict((await self.session.execute(ch_stmt)).all())
        out = []
        for m in rows:
            n = ch_map.get(m.chapter_id)
            if n is None:
                continue
            if from_chapter is not None and n < from_chapter:
                continue
            if to_chapter is not None and n > to_chapter:
                continue
            out.append(m)
        return out