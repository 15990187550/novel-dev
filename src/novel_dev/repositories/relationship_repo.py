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
        novel_id: Optional[str] = None,
    ) -> EntityRelationship:
        rel = EntityRelationship(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            meta=meta,
            created_at_chapter_id=chapter_id,
            novel_id=novel_id,
        )
        self.session.add(rel)
        await self.session.flush()
        return rel

    async def list_by_source(self, source_id: str, novel_id: Optional[str] = None) -> list:
        stmt = select(EntityRelationship).where(
            EntityRelationship.source_id == source_id,
            EntityRelationship.is_active == True,
        )
        if novel_id is not None:
            stmt = stmt.where(EntityRelationship.novel_id == novel_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_active(self, source_id: str, target_id: str, novel_id: Optional[str] = None) -> Optional[EntityRelationship]:
        stmt = select(EntityRelationship).where(
            EntityRelationship.source_id == source_id,
            EntityRelationship.target_id == target_id,
            EntityRelationship.is_active == True,
        )
        if novel_id is not None:
            stmt = stmt.where(EntityRelationship.novel_id == novel_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        meta: Optional[dict] = None,
        chapter_id: Optional[str] = None,
        novel_id: Optional[str] = None,
    ) -> EntityRelationship:
        existing = await self.get_active(source_id, target_id, novel_id=novel_id)
        if existing is None:
            return await self.create(
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
                meta=meta,
                chapter_id=chapter_id,
                novel_id=novel_id,
            )

        existing.relation_type = relation_type
        existing.meta = meta
        existing.created_at_chapter_id = chapter_id
        await self.session.flush()
        return existing
