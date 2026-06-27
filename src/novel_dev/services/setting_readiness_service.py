from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import PendingExtraction, SettingReviewBatch, SettingReviewChange


@dataclass(frozen=True)
class SettingReadiness:
    ready: bool
    blockers: list[str]
    message: str


class SettingReadinessService:
    """Checks whether setting review work is settled before outline generation."""

    BLOCKING_PENDING_STATUSES = {"processing", "pending"}
    BLOCKING_PENDING_TYPES = {"processing", "setting"}
    REVIEW_STATUSES_REQUIRING_CHECK = {"pending", "ready_for_review", "partially_approved", "failed"}
    BLOCKING_REVIEW_STATUSES = {"failed"}
    BLOCKING_REVIEW_CHANGE_STATUSES = {"pending", "failed"}

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
            .order_by(SettingReviewBatch.created_at.asc())
        )
        for batch in self._active_review_batches(batch_result.scalars().all()):
            if batch.status not in self.REVIEW_STATUSES_REQUIRING_CHECK:
                continue
            if batch.status in self.BLOCKING_REVIEW_STATUSES:
                blockers.append(
                    f"setting_review_batch:{batch.id}:status={batch.status}:source_type={batch.source_type}"
                )
                continue

            change_result = await self.session.execute(
                select(SettingReviewChange)
                .where(SettingReviewChange.batch_id == batch.id)
                .order_by(SettingReviewChange.created_at.asc(), SettingReviewChange.id.asc())
            )
            changes = change_result.scalars().all()
            if not changes:
                if batch.source_type == "ai_session":
                    blockers.append(
                        f"setting_review_batch:{batch.id}:status={batch.status}:source_type={batch.source_type}"
                    )
                continue

            blocking_changes = [
                change
                for change in changes
                if change.status in self.BLOCKING_REVIEW_CHANGE_STATUSES
            ]
            if not blocking_changes:
                continue
            for change in blocking_changes:
                blockers.append(
                    "setting_review_batch:"
                    f"{batch.id}:status={batch.status}:source_type={batch.source_type}:"
                    f"change:{change.id}:target_type={change.target_type}:change_status={change.status}"
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

    @staticmethod
    def _active_review_batches(batches: list[SettingReviewBatch]) -> list[SettingReviewBatch]:
        latest_consolidation = next(
            (batch for batch in reversed(batches) if batch.source_type == "consolidation"),
            None,
        )
        if latest_consolidation is None:
            return batches
        return [
            batch
            for batch in batches
            if batch.source_type != "consolidation" or batch.id == latest_consolidation.id
        ]
