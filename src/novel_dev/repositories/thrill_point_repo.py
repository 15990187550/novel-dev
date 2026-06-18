from __future__ import annotations
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from novel_dev.db.models import ThrillPoint


class ThrillPointRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        novel_id: str,
        chapter_id: str,
        thrill_type: str,
        intensity: str,
        beat_idx: Optional[int] = None,
        evidence_quote: Optional[str] = None,
        planner_predicted: bool = False,
    ) -> ThrillPoint:
        tp = ThrillPoint(
            novel_id=novel_id,
            chapter_id=chapter_id,
            beat_idx=beat_idx,
            thrill_type=thrill_type,
            intensity=intensity,
            evidence_quote=evidence_quote,
            planner_predicted=planner_predicted,
            fast_review_verified=False,
        )
        self.session.add(tp)
        await self.session.flush()
        return tp

    async def list_all(
        self,
        novel_id: str,
        *,
        chapter_id: Optional[str] = None,
    ) -> list[ThrillPoint]:
        """Return all thrill point rows for a novel (or single chapter).

        Used by cross-metric aggregations that need to compute planned-vs-verified
        ratios. Unlike :meth:`list_unverified`, this method does not filter on
        ``planner_predicted`` / ``fast_review_verified`` — callers decide which
        subset to count.
        """
        stmt = select(ThrillPoint).where(ThrillPoint.novel_id == novel_id)
        if chapter_id is not None:
            stmt = stmt.where(ThrillPoint.chapter_id == chapter_id)
        stmt = stmt.order_by(
            ThrillPoint.chapter_id.asc(),
            ThrillPoint.beat_idx.asc(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_unverified(
        self,
        novel_id: str,
        *,
        chapter_id: Optional[str] = None,
    ) -> list[ThrillPoint]:
        """Return planner-predicted thrill points that have not yet been
        verified by FastReviewAgent.

        When ``chapter_id`` is provided, results are scoped to that single
        chapter; otherwise predictions across the entire novel are returned.
        Only rows with ``planner_predicted=True`` and
        ``fast_review_verified=False`` are included.
        """
        stmt = (
            select(ThrillPoint)
            .where(ThrillPoint.novel_id == novel_id)
            .where(ThrillPoint.planner_predicted == True)  # noqa: E712
            .where(ThrillPoint.fast_review_verified == False)  # noqa: E712
        )
        if chapter_id is not None:
            stmt = stmt.where(ThrillPoint.chapter_id == chapter_id)
        stmt = stmt.order_by(ThrillPoint.chapter_id.asc(), ThrillPoint.beat_idx.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_verified(
        self,
        thrill_point_id: str,
        *,
        evidence_quote: Optional[str] = None,
    ) -> None:
        """Mark a planner-predicted thrill point as verified by FastReview.

        ``evidence_quote`` stores a short substring from the polished text
        that triggered the verification (best effort, may be None when the
        reviewer only confirmed the thrill qualitatively).
        """
        result = await self.session.execute(
            select(ThrillPoint).where(ThrillPoint.id == thrill_point_id)
        )
        tp = result.scalar_one_or_none()
        if tp:
            tp.fast_review_verified = True
            if evidence_quote is not None:
                tp.evidence_quote = evidence_quote
            await self.session.flush()
