import asyncio
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import Entity
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class EntityService:
    def __init__(self, session: AsyncSession, embedding_service: Optional[EmbeddingService] = None):
        self.entity_repo = EntityRepository(session)
        self.version_repo = EntityVersionRepository(session)
        self.embedding_service = embedding_service

    async def create_entity(self, entity_id: str, entity_type: str, name: str, chapter_id: Optional[str] = None, novel_id: Optional[str] = None) -> Entity:
        entity = await self.entity_repo.create(entity_id, entity_type, name, chapter_id, novel_id)
        await self.version_repo.create(entity_id, 1, {"name": name}, chapter_id=chapter_id, diff_summary={"created": True})
        await self.entity_repo.update_version(entity_id, 1)
        if self.embedding_service:
            try:
                asyncio.create_task(self.embedding_service.index_entity(entity_id))
            except Exception as exc:
                logger.warning("entity_index_trigger_failed", extra={"entity_id": entity_id, "error": str(exc)})
        return entity

    async def update_state(self, entity_id: str, new_state: dict, chapter_id: Optional[str] = None, diff_summary: Optional[dict] = None):
        latest = await self.version_repo.get_latest(entity_id)
        new_version = (latest.version + 1) if latest else 1
        ver = await self.version_repo.create(entity_id, new_version, new_state, chapter_id=chapter_id, diff_summary=diff_summary)
        await self.entity_repo.update_version(entity_id, new_version)
        if self.embedding_service:
            try:
                asyncio.create_task(self.embedding_service.index_entity(entity_id))
            except Exception as exc:
                logger.warning("entity_index_trigger_failed", extra={"entity_id": entity_id, "error": str(exc)})
        return ver

    async def get_latest_state(self, entity_id: str) -> Optional[dict]:
        latest = await self.version_repo.get_latest(entity_id)
        return latest.state if latest else None

    async def get_latest_states(self, entity_ids: list[str]) -> dict[str, dict]:
        from sqlalchemy import select
        from novel_dev.db.models import EntityVersion

        if not entity_ids:
            return {}

        result = await self.version_repo.session.execute(
            select(EntityVersion.entity_id, EntityVersion.state, EntityVersion.version)
            .where(EntityVersion.entity_id.in_(entity_ids))
            .order_by(EntityVersion.version.desc())
        )

        states: dict[str, dict] = {}
        for row in result.all():
            eid = row.entity_id
            if eid not in states:
                states[eid] = row.state
        return states
