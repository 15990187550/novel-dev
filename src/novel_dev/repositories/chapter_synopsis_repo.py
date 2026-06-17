from __future__ import annotations
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from novel_dev.db.models import ChapterSynopsis


class ChapterSynopsisRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, novel_id: str, chapter_range_start: int, chapter_range_end: int,
        narrative_prose: str, structured_json: dict,
        trigger_event: dict, prev_synopsis_id: Optional[str] = None,
        analyzer_version: str = "v1.0",
    ) -> ChapterSynopsis:
        cs = ChapterSynopsis(
            novel_id=novel_id,
            chapter_range_start=chapter_range_start,
            chapter_range_end=chapter_range_end,
            narrative_prose=narrative_prose,
            structured_json=structured_json,
            trigger_event=trigger_event,
            prev_synopsis_id=prev_synopsis_id,
            analyzer_version=analyzer_version,
        )
        self.session.add(cs)
        await self.session.flush()
        return cs

    async def get_latest(self, novel_id: str) -> Optional[ChapterSynopsis]:
        result = await self.session.execute(
            select(ChapterSynopsis)
            .where(ChapterSynopsis.novel_id == novel_id)
            .order_by(ChapterSynopsis.chapter_range_end.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_all(self, novel_id: str) -> list[ChapterSynopsis]:
        result = await self.session.execute(
            select(ChapterSynopsis)
            .where(ChapterSynopsis.novel_id == novel_id)
            .order_by(ChapterSynopsis.chapter_range_start.asc())
        )
        return list(result.scalars().all())
