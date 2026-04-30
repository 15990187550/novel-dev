from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import Timeline


class TimelineRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, tick: int, narrative: str, anchor_chapter_id: Optional[str] = None, anchor_event_id: Optional[str] = None, novel_id: Optional[str] = None) -> Timeline:
        entry = Timeline(
            tick=tick,
            narrative=narrative,
            anchor_chapter_id=anchor_chapter_id,
            anchor_event_id=anchor_event_id,
            novel_id=novel_id,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def get_by_tick(self, tick: int, novel_id: Optional[str] = None) -> Optional[Timeline]:
        stmt = select(Timeline).where(Timeline.tick == tick)
        if novel_id is not None:
            stmt = stmt.where(Timeline.novel_id == novel_id)
        result = await self.session.execute(stmt.order_by(Timeline.id.asc()).limit(1))
        return result.scalars().first()

    async def create_or_merge(
        self,
        tick: int,
        narrative: str,
        anchor_chapter_id: Optional[str] = None,
        anchor_event_id: Optional[str] = None,
        novel_id: Optional[str] = None,
    ) -> tuple[Timeline, bool]:
        existing = await self.get_by_tick(tick, novel_id=novel_id)
        if not existing:
            return await self.create(tick, narrative, anchor_chapter_id, anchor_event_id, novel_id), True

        if narrative and narrative not in (existing.narrative or ""):
            existing.narrative = "\n".join(part for part in [existing.narrative, narrative] if part)
        if anchor_chapter_id and not existing.anchor_chapter_id:
            existing.anchor_chapter_id = anchor_chapter_id
        if anchor_event_id and not existing.anchor_event_id:
            existing.anchor_event_id = anchor_event_id
        await self.session.flush()
        return existing, False

    async def get_current_tick(self, novel_id: Optional[str] = None) -> Optional[int]:
        stmt = select(Timeline.tick).order_by(Timeline.tick.desc())
        if novel_id is not None:
            stmt = stmt.where(Timeline.novel_id == novel_id)
        result = await self.session.execute(stmt.limit(1))
        return result.scalars().first()

    async def get_adjacent(self, tick: int):
        prev_result = await self.session.execute(
            select(Timeline).where(Timeline.tick < tick).order_by(Timeline.tick.desc())
        )
        next_result = await self.session.execute(
            select(Timeline).where(Timeline.tick > tick).order_by(Timeline.tick.asc())
        )
        return prev_result.scalars().first(), next_result.scalars().first()

    async def get_around_tick(self, tick: int, radius: int = 3, novel_id: Optional[str] = None) -> List[Timeline]:
        prev_stmt = (
            select(Timeline)
            .where(Timeline.tick < tick)
            .order_by(Timeline.tick.desc())
            .limit(radius)
        )
        next_stmt = (
            select(Timeline)
            .where(Timeline.tick >= tick)
            .order_by(Timeline.tick.asc())
            .limit(radius)
        )
        if novel_id is not None:
            prev_stmt = prev_stmt.where(Timeline.novel_id == novel_id)
            next_stmt = next_stmt.where(Timeline.novel_id == novel_id)
        prev_result = await self.session.execute(prev_stmt)
        next_result = await self.session.execute(next_stmt)
        prev_items = list(prev_result.scalars().all())
        prev_items.reverse()
        next_items = list(next_result.scalars().all())
        return prev_items + next_items

    async def list_by_novel(self, novel_id: str) -> List[Timeline]:
        result = await self.session.execute(
            select(Timeline)
            .where(Timeline.novel_id == novel_id)
            .order_by(Timeline.tick.asc())
        )
        return list(result.scalars().all())

    async def list_between(
        self, start: int, end: int, novel_id: Optional[str] = None
    ) -> List[Timeline]:
        stmt = select(Timeline).where(Timeline.tick >= start, Timeline.tick <= end)
        if novel_id is not None:
            stmt = stmt.where(Timeline.novel_id == novel_id)
        result = await self.session.execute(stmt.order_by(Timeline.tick.asc()))
        return list(result.scalars().all())
