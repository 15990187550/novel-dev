from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import Foreshadowing


class ForeshadowingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        fs_id: str,
        content: str,
        埋下_chapter_id: Optional[str] = None,
        埋下_time_tick: Optional[int] = None,
        埋下_location_id: Optional[str] = None,
        相关人物_ids: Optional[List[str]] = None,
        回收条件: Optional[dict] = None,
        回收影响: Optional[dict] = None,
    ) -> Foreshadowing:
        fs = Foreshadowing(
            id=fs_id,
            content=content,
            埋下_chapter_id=埋下_chapter_id,
            埋下_time_tick=埋下_time_tick,
            埋下_location_id=埋下_location_id,
            相关人物_ids=相关人物_ids,
            回收条件=回收条件,
            回收影响=回收影响,
        )
        self.session.add(fs)
        await self.session.flush()
        return fs

    async def get_by_id(self, fs_id: str) -> Optional[Foreshadowing]:
        result = await self.session.execute(select(Foreshadowing).where(Foreshadowing.id == fs_id))
        return result.scalar_one_or_none()

    async def list_active(self) -> List[Foreshadowing]:
        result = await self.session.execute(
            select(Foreshadowing).where(Foreshadowing.回收状态 == "pending")
        )
        return result.scalars().all()

    async def mark_recovered(self, fs_id: str, chapter_id: str, event_id: Optional[str] = None) -> None:
        fs = await self.get_by_id(fs_id)
        if fs:
            fs.回收状态 = "recovered"
            fs.recovered_chapter_id = chapter_id
            fs.recovered_event_id = event_id
            await self.session.flush()
