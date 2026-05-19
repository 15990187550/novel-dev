from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import PendingExtraction, SettingReviewBatch


@dataclass(frozen=True)
class SettingReadiness:
    ready: bool
    blockers: list[str]
    message: str


class SettingReadinessService:
    """Checks whether setting review work is settled before outline generation."""

    BLOCKING_PENDING_STATUSES = {"processing", "pending"}
    BLOCKING_PENDING_TYPES = {"processing", "setting"}
    BLOCKING_REVIEW_STATUSES = {"pending", "ready_for_review", "partially_approved"}

    def __init__(self, session: AsyncSession):
        self.session = session

    async def evaluate_for_outline_generation(self, novel_id: str) -> SettingReadiness:
        blockers: list[str] = []

        pending_result = await self.session.execute(
            select(PendingExtraction)
            .where(PendingExtraction.novel_id == novel_id)
            .where(PendingExtraction.status.in_(self.BLOCKING_PENDING_STATUSES))
            .where(PendingExtraction.extraction_type.in_(self.BLOCKING_PENDING_TYPES))
            .order_by(PendingExtraction.created_at.asc())
        )
        for item in pending_result.scalars().all():
            blockers.append(
                f"pending_extraction:{item.id}:status={item.status}:type={item.extraction_type}"
            )

        batch_result = await self.session.execute(
            select(SettingReviewBatch)
            .where(SettingReviewBatch.novel_id == novel_id)
            .where(SettingReviewBatch.status.in_(self.BLOCKING_REVIEW_STATUSES))
            .order_by(SettingReviewBatch.created_at.asc())
        )
        for batch in batch_result.scalars().all():
            blockers.append(
                f"setting_review_batch:{batch.id}:status={batch.status}:source_type={batch.source_type}"
            )

        if not blockers:
            return SettingReadiness(
                ready=True,
                blockers=[],
                message="Setting review is complete for outline generation",
            )
        return SettingReadiness(
            ready=False,
            blockers=blockers,
            message="Setting review is not complete: " + "; ".join(blockers),
        )
