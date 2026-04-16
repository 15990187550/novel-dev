from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import Spaceline


class SpacelineRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, location_id: str, name: str, parent_id: Optional[str] = None, narrative: Optional[str] = None, meta: Optional[dict] = None) -> Spaceline:
        loc = Spaceline(
            id=location_id,
            name=name,
            parent_id=parent_id,
            narrative=narrative,
            meta=meta,
        )
        self.session.add(loc)
        await self.session.flush()
        return loc

    async def get_chain(self, location_id: str) -> List[Spaceline]:
        chain = []
        current_id = location_id
        while current_id:
            result = await self.session.execute(select(Spaceline).where(Spaceline.id == current_id))
            node = result.scalar_one_or_none()
            if not node:
                break
            chain.append(node)
            current_id = node.parent_id
        chain.reverse()
        return chain
