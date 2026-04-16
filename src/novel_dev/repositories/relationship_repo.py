from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import EntityRelationship


class RelationshipRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        meta: Optional[dict] = None,
        chapter_id: Optional[str] = None,
    ) -> EntityRelationship:
        rel = EntityRelationship(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            meta=meta,
            created_at_chapter_id=chapter_id,
        )
        self.session.add(rel)
        await self.session.flush()
        return rel

    async def list_by_source(self, source_id: str) -> list:
        result = await self.session.execute(
            select(EntityRelationship).where(
                EntityRelationship.source_id == source_id,
                EntityRelationship.is_active == True,
            )
        )
        return result.scalars().all()
