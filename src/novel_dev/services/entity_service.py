from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import Entity
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository


class EntityService:
    def __init__(self, session: AsyncSession):
        self.entity_repo = EntityRepository(session)
        self.version_repo = EntityVersionRepository(session)

    async def create_entity(self, entity_id: str, entity_type: str, name: str, chapter_id: Optional[str] = None) -> Entity:
        entity = await self.entity_repo.create(entity_id, entity_type, name, chapter_id)
        await self.version_repo.create(entity_id, 1, {"name": name}, chapter_id=chapter_id, diff_summary={"created": True})
        await self.entity_repo.update_version(entity_id, 1)
        return entity

    async def update_state(self, entity_id: str, new_state: dict, chapter_id: Optional[str] = None, diff_summary: Optional[dict] = None):
        latest = await self.version_repo.get_latest(entity_id)
        new_version = (latest.version + 1) if latest else 1
        ver = await self.version_repo.create(entity_id, new_version, new_state, chapter_id=chapter_id, diff_summary=diff_summary)
        await self.entity_repo.update_version(entity_id, new_version)
        return ver

    async def get_latest_state(self, entity_id: str) -> Optional[dict]:
        latest = await self.version_repo.get_latest(entity_id)
        return latest.state if latest else None
