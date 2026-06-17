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

    async def list_unverified(self, novel_id: str) -> list[ThrillPoint]:
        result = await self.session.execute(
            select(ThrillPoint)
            .where(ThrillPoint.novel_id == novel_id)
            .where(ThrillPoint.fast_review_verified == False)  # noqa: E712
            .order_by(ThrillPoint.chapter_id.asc())
        )
        return list(result.scalars().all())

    async def mark_verified(self, thrill_point_id: str) -> None:
        result = await self.session.execute(
            select(ThrillPoint).where(ThrillPoint.id == thrill_point_id)
        )
        tp = result.scalar_one_or_none()
        if tp:
            tp.fast_review_verified = True
            await self.session.flush()
