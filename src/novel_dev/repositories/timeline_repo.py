from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import Timeline


class TimelineRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, tick: int, narrative: str, anchor_chapter_id: Optional[str] = None, anchor_event_id: Optional[str] = None) -> Timeline:
        entry = Timeline(
            tick=tick,
            narrative=narrative,
            anchor_chapter_id=anchor_chapter_id,
            anchor_event_id=anchor_event_id,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def get_current_tick(self) -> Optional[int]:
        result = await self.session.execute(select(Timeline.tick).order_by(Timeline.tick.desc()))
        row = result.scalar_one_or_none()
        return row

    async def get_adjacent(self, tick: int):
        prev_result = await self.session.execute(
            select(Timeline).where(Timeline.tick < tick).order_by(Timeline.tick.desc())
        )
        next_result = await self.session.execute(
            select(Timeline).where(Timeline.tick > tick).order_by(Timeline.tick.asc())
        )
        return prev_result.scalars().first(), next_result.scalars().first()

    async def get_around_tick(self, tick: int, radius: int = 3) -> List[Timeline]:
        prev_result = await self.session.execute(
            select(Timeline)
            .where(Timeline.tick < tick)
            .order_by(Timeline.tick.desc())
            .limit(radius)
        )
        next_result = await self.session.execute(
            select(Timeline)
            .where(Timeline.tick >= tick)
            .order_by(Timeline.tick.asc())
            .limit(radius)
        )
        prev_items = list(prev_result.scalars().all())
        prev_items.reverse()
        next_items = list(next_result.scalars().all())
        return prev_items + next_items
