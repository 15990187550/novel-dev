from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import Entity


class EntityRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, entity_id: str, entity_type: str, name: str, created_at_chapter_id: Optional[str] = None) -> Entity:
        entity = Entity(
            id=entity_id,
            type=entity_type,
            name=name,
            created_at_chapter_id=created_at_chapter_id,
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
