from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import Chapter


class ChapterRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, chapter_id: str, volume_id: str, chapter_number: int, title: Optional[str] = None) -> Chapter:
        ch = Chapter(
            id=chapter_id,
            volume_id=volume_id,
            chapter_number=chapter_number,
            title=title,
        )
        self.session.add(ch)
        await self.session.flush()
        return ch

    async def get_by_id(self, chapter_id: str) -> Optional[Chapter]:
        result = await self.session.execute(select(Chapter).where(Chapter.id == chapter_id))
        return result.scalar_one_or_none()

    async def list_by_volume(self, volume_id: str) -> List[Chapter]:
        result = await self.session.execute(
            select(Chapter).where(Chapter.volume_id == volume_id).order_by(Chapter.chapter_number)
        )
        return result.scalars().all()

    async def update_text(self, chapter_id: str, raw_draft: Optional[str] = None, polished_text: Optional[str] = None) -> None:
        ch = await self.get_by_id(chapter_id)
        if ch:
            if raw_draft is not None:
                ch.raw_draft = raw_draft
            if polished_text is not None:
                ch.polished_text = polished_text
            await self.session.flush()

    async def update_scores(self, chapter_id: str, overall: int, breakdown: dict, feedback: dict) -> None:
        ch = await self.get_by_id(chapter_id)
        if ch:
            ch.score_overall = overall
            ch.score_breakdown = breakdown
            ch.review_feedback = feedback
            await self.session.flush()

    async def update_status(self, chapter_id: str, status: str) -> None:
        ch = await self.get_by_id(chapter_id)
        if ch:
            ch.status = status
            await self.session.flush()
