from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select

from novel_dev.db.models import EntityVersion


class EntityVersionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        entity_id: str,
        version: int,
        state: dict,
        chapter_id: Optional[str] = None,
        diff_summary: Optional[dict] = None,
    ) -> EntityVersion:
        ver = EntityVersion(
            entity_id=entity_id,
            version=version,
            state=state,
            chapter_id=chapter_id,
            diff_summary=diff_summary,
        )
        self.session.add(ver)
        await self.session.flush()
        return ver

    async def get_latest(self, entity_id: str) -> Optional[EntityVersion]:
        result = await self.session.execute(
            select(EntityVersion)
            .where(EntityVersion.entity_id == entity_id)
            .order_by(EntityVersion.version.desc())
        )
        return result.scalars().first()

    async def get_at_chapter(self, entity_id: str, chapter_id: str) -> Optional[EntityVersion]:
        result = await self.session.execute(
            select(EntityVersion)
            .where(
                EntityVersion.entity_id == entity_id,
                EntityVersion.chapter_id <= chapter_id,
            )
            .order_by(EntityVersion.version.desc())
        )
        return result.scalars().first()

    async def delete_by_entity_id(self, entity_id: str) -> None:
        await self.session.execute(
            delete(EntityVersion).where(EntityVersion.entity_id == entity_id)
        )
        await self.session.flush()
