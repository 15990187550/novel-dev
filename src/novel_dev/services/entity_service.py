import asyncio
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import Entity
from novel_dev.repositories.entity_group_repo import EntityGroupRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.services.entity_classification_service import EntityClassificationResult
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.services.entity_classification_service import EntityClassificationService

logger = logging.getLogger(__name__)


class EntityService:
    def __init__(self, session: AsyncSession, embedding_service: Optional[EmbeddingService] = None):
        self.entity_repo = EntityRepository(session)
        self.group_repo = EntityGroupRepository(session)
        self.version_repo = EntityVersionRepository(session)
        self.relationship_repo = RelationshipRepository(session)
        self.classification_service = EntityClassificationService(session)
        self.embedding_service = embedding_service

    async def _persist_classification(self, entity_id: str, classification: EntityClassificationResult) -> None:
        entity = await self.entity_repo.get_by_id(entity_id)
        if not entity:
            return

        system_group_id = None
        if not classification.system_needs_review and classification.system_group_slug:
            system_group = await self.group_repo.upsert(
                novel_id=entity.novel_id or "",
                category=classification.system_category,
                group_name=classification.system_category,
                group_slug=classification.system_group_slug,
            )
            system_group_id = system_group.id

        await self.entity_repo.update_classification(
            entity_id,
            system_category=classification.system_category,
            system_group_id=system_group_id,
            classification_reason=classification.classification_reason,
            classification_confidence=classification.classification_confidence,
            system_needs_review=classification.system_needs_review,
        )

    async def _refresh_entity_artifacts(self, entity_id: str) -> None:
        entity = await self.entity_repo.get_by_id(entity_id)
        if not entity:
            return

        latest_state = await self.get_latest_state(entity_id) or {}
        relationships = await self.relationship_repo.list_by_source(entity_id, novel_id=entity.novel_id) if entity.novel_id else []

        try:
            classification = await self.classification_service.classify(
                novel_id=entity.novel_id or "",
                entity_name=entity.name,
                latest_state=latest_state,
                relationships=relationships,
            )
            await self._persist_classification(entity_id, classification)
        except Exception as exc:
            logger.warning("entity_classification_failed", extra={"entity_id": entity_id, "error": str(exc)})

        if not self.embedding_service:
            return

        try:
            await self.embedding_service.index_entity(entity_id)
        except Exception as exc:
            logger.warning("entity_index_trigger_failed", extra={"entity_id": entity_id, "error": str(exc)})

        if hasattr(self.embedding_service, "index_entity_search"):
            try:
                await self.embedding_service.index_entity_search(entity_id)
            except Exception as exc:
                logger.warning("entity_search_index_trigger_failed", extra={"entity_id": entity_id, "error": str(exc)})

    async def create_entity(
        self,
        entity_id: str,
        entity_type: str,
        name: str,
        chapter_id: Optional[str] = None,
        novel_id: Optional[str] = None,
        initial_state: Optional[dict] = None,
    ) -> Entity:
        entity = await self.entity_repo.create(entity_id, entity_type, name, chapter_id, novel_id)
        state = initial_state.copy() if initial_state else {}
        if name not in state:
            state["name"] = name
        elif state.get("name") != name:
            state["name"] = name
        await self.version_repo.create(entity_id, 1, state, chapter_id=chapter_id, diff_summary={"created": True})
        await self.entity_repo.update_version(entity_id, 1)
        await self._refresh_entity_artifacts(entity_id)
        return entity

    async def create_or_update_entity(
        self,
        entity_id: str,
        entity_type: str,
        name: str,
        chapter_id: Optional[str] = None,
        novel_id: Optional[str] = None,
        initial_state: Optional[dict] = None,
    ) -> Entity:
        existing = await self.entity_repo.find_by_name(name, entity_type=entity_type, novel_id=novel_id)
        if existing is None:
            return await self.create_entity(entity_id, entity_type, name, chapter_id, novel_id, initial_state)

        latest_state = await self.get_latest_state(existing.id)
        merged_state = dict(latest_state or {})
        if initial_state:
            merged_state.update(initial_state)
        merged_state["name"] = name
        await self.update_state(existing.id, merged_state, chapter_id=chapter_id, diff_summary={"merged": True})
        return existing

    async def update_state(self, entity_id: str, new_state: dict, chapter_id: Optional[str] = None, diff_summary: Optional[dict] = None):
        latest = await self.version_repo.get_latest(entity_id)
        new_version = (latest.version + 1) if latest else 1
        ver = await self.version_repo.create(entity_id, new_version, new_state, chapter_id=chapter_id, diff_summary=diff_summary)
        await self.entity_repo.update_version(entity_id, new_version)
        await self._refresh_entity_artifacts(entity_id)
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
