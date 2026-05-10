import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import WorldStateReview


class WorldStateReviewRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        novel_id: str,
        chapter_id: str,
        extraction_payload: dict,
        diff_result: dict,
        *,
        review_id: Optional[str] = None,
    ) -> WorldStateReview:
        review = WorldStateReview(
            id=review_id or f"wsr_{uuid.uuid4().hex[:12]}",
            novel_id=novel_id,
            chapter_id=chapter_id,
            status="pending",
            extraction_payload=dict(extraction_payload or {}),
            diff_result=dict(diff_result or {}),
        )
        self.session.add(review)
        await self.session.flush()
        return review

    async def get_by_id(self, review_id: str) -> Optional[WorldStateReview]:
        result = await self.session.execute(
            select(WorldStateReview)
            .where(WorldStateReview.id == review_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def find_pending_for_chapter(self, novel_id: str, chapter_id: str) -> Optional[WorldStateReview]:
        result = await self.session.execute(
            select(WorldStateReview)
            .where(
                WorldStateReview.novel_id == novel_id,
                WorldStateReview.chapter_id == chapter_id,
                WorldStateReview.status == "pending",
            )
            .order_by(WorldStateReview.updated_at.desc(), WorldStateReview.created_at.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def list_by_novel(self, novel_id: str, status: str | None = None) -> list[WorldStateReview]:
        stmt = select(WorldStateReview).where(WorldStateReview.novel_id == novel_id)
        if status:
            stmt = stmt.where(WorldStateReview.status == status)
        result = await self.session.execute(
            stmt.order_by(WorldStateReview.updated_at.desc(), WorldStateReview.created_at.desc())
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def mark_resolved(
        self,
        review_id: str,
        *,
        status: str,
        decision: dict,
        error_message: str | None = None,
    ) -> Optional[WorldStateReview]:
        review = await self.get_by_id(review_id)
        if not review:
            return None
        review.status = status
        review.decision = dict(decision or {})
        review.error_message = error_message
        review.updated_at = datetime.utcnow()
        await self.session.flush()
        return review
