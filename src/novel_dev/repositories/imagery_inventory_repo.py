from __future__ import annotations
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from novel_dev.db.models import ImageryInventory


class ImageryInventoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        novel_id: str,
        chapter_id: str,
        item: str,
        item_type: str,
        frequency_in_chapter: int = 1,
    ) -> ImageryInventory:
        ii = ImageryInventory(
            novel_id=novel_id,
            chapter_id=chapter_id,
            item=item,
            item_type=item_type,
            frequency_in_chapter=frequency_in_chapter,
        )
        self.session.add(ii)
        await self.session.flush()
        return ii

    async def get_recent(
        self, novel_id: str, limit: int = 10
    ) -> list[ImageryInventory]:
        result = await self.session.execute(
            select(ImageryInventory)
            .where(ImageryInventory.novel_id == novel_id)
            .order_by(ImageryInventory.extracted_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
