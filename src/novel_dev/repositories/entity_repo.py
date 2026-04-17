from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import Entity


class EntityRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, entity_id: str, entity_type: str, name: str, created_at_chapter_id: Optional[str] = None, novel_id: Optional[str] = None) -> Entity:
        entity = Entity(
            id=entity_id,
            type=entity_type,
            name=name,
            created_at_chapter_id=created_at_chapter_id,
            novel_id=novel_id,
        )
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def get_by_id(self, entity_id: str) -> Optional[Entity]:
        result = await self.session.execute(select(Entity).where(Entity.id == entity_id))
        return result.scalar_one_or_none()

    async def update_version(self, entity_id: str, new_version: int) -> None:
        entity = await self.get_by_id(entity_id)
        if entity:
            entity.current_version = new_version
            await self.session.flush()

    async def find_by_names(self, names: List[str], novel_id: Optional[str] = None) -> List[Entity]:
        if not names:
            return []
        stmt = select(Entity).where(Entity.name.in_(names))
        if novel_id is not None:
            stmt = stmt.where(Entity.novel_id == novel_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_by_novel(self, novel_id: str) -> List[Entity]:
        result = await self.session.execute(
            select(Entity).where(Entity.novel_id == novel_id)
        )
        return result.scalars().all()
