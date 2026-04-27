import asyncio
import logging
from typing import Any, Optional

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
        self.session = session
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
                group_name=classification.system_group_name or classification.system_category,
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

    async def _refresh_entity_artifacts(self, entity_id: str, *, use_llm_for_classification: bool = True) -> None:
        entity = await self.entity_repo.get_by_id(entity_id)
        if not entity:
            return

        latest_state = await self.get_latest_state(entity_id) or {}
        relationships = await self.relationship_repo.list_by_source(entity_id, novel_id=entity.novel_id) if entity.novel_id else []

        try:
            classification = await self.classification_service.classify(
                novel_id=entity.novel_id or "",
                entity_type=entity.type,
                entity_name=entity.name,
                latest_state=latest_state,
                relationships=relationships,
                use_llm=use_llm_for_classification,
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

    async def classify_entities_batch(self, entity_ids: list[str]) -> dict:
        entities_by_id = {}
        payload: list[dict[str, Any]] = []
        for entity_id in entity_ids:
            entity = await self.entity_repo.get_by_id(entity_id)
            if not entity:
                continue
            latest_state = await self.get_latest_state(entity_id) or {}
            relationships = await self.relationship_repo.list_by_source(entity_id, novel_id=entity.novel_id) if entity.novel_id else []
            entities_by_id[entity_id] = entity
            payload.append({
                "entity_id": entity_id,
                "entity_type": entity.type,
                "entity_name": entity.name,
                "latest_state": latest_state,
                "relationships": relationships,
            })

        if not payload:
            return {"total": 0, "updated": 0}

        novel_id = next((entity.novel_id for entity in entities_by_id.values() if entity.novel_id), "")
        classifications = await self.classification_service.classify_batch(novel_id, payload)
        updated = 0
        for entity_payload, classification in zip(payload, classifications):
            await self._persist_classification(entity_payload["entity_id"], classification)
            updated += 1

        if self.embedding_service:
            for entity_id in entity_ids:
                try:
                    await self.embedding_service.index_entity(entity_id)
                    if hasattr(self.embedding_service, "index_entity_search"):
                        await self.embedding_service.index_entity_search(entity_id)
                except Exception as exc:
                    logger.warning("entity_index_trigger_failed", extra={"entity_id": entity_id, "error": str(exc)})

        return {"total": len(payload), "updated": updated}

    async def reclassify_entities_for_novel(self, novel_id: str) -> dict:
        entities = await self.entity_repo.list_by_novel(novel_id)
        batch_size = 25
        updated = 0
        for start in range(0, len(entities), batch_size):
            batch = entities[start:start + batch_size]
            result = await self.classify_entities_batch([entity.id for entity in batch])
            updated += int(result.get("updated") or 0)
        return {
            "novel_id": novel_id,
            "total": len(entities),
            "updated": updated,
            "batch_size": batch_size,
        }

    async def create_entity(
        self,
        entity_id: str,
        entity_type: str,
        name: str,
        chapter_id: Optional[str] = None,
        novel_id: Optional[str] = None,
        initial_state: Optional[dict] = None,
        use_llm_for_classification: bool = True,
    ) -> Entity:
        entity = await self.entity_repo.create(entity_id, entity_type, name, chapter_id, novel_id)
        state = initial_state.copy() if initial_state else {}
        if name not in state:
            state["name"] = name
        elif state.get("name") != name:
            state["name"] = name
        await self.version_repo.create(entity_id, 1, state, chapter_id=chapter_id, diff_summary={"created": True})
        await self.entity_repo.update_version(entity_id, 1)
        await self._refresh_entity_artifacts(entity_id, use_llm_for_classification=use_llm_for_classification)
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

    async def update_state_from_import(
        self,
        entity_id: str,
        new_state: dict,
        chapter_id: Optional[str] = None,
        diff_summary: Optional[dict] = None,
    ):
        latest = await self.version_repo.get_latest(entity_id)
        new_version = (latest.version + 1) if latest else 1
        ver = await self.version_repo.create(entity_id, new_version, new_state, chapter_id=chapter_id, diff_summary=diff_summary)
        await self.entity_repo.update_version(entity_id, new_version)
        await self._refresh_entity_artifacts(entity_id, use_llm_for_classification=False)
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

    async def update_entity_fields(
        self,
        entity_id: str,
        *,
        name: Optional[str] = None,
        entity_type: Optional[str] = None,
        aliases: Optional[list[str]] = None,
        state_fields: Optional[dict[str, Any]] = None,
    ) -> Entity:
        entity = await self.entity_repo.get_by_id(entity_id)
        if entity is None:
            raise ValueError("entity not found")

        latest_state = await self.get_latest_state(entity_id) or {}
        new_state = dict(latest_state)
        normalized_name = (name or entity.name or "").strip()
        normalized_type = (entity_type or entity.type or "").strip()

        if not normalized_name:
            raise ValueError("entity name is required")
        if not normalized_type:
            raise ValueError("entity type is required")

        if state_fields:
            new_state.update(state_fields)
        if aliases is not None:
            new_state["aliases"] = [alias.strip() for alias in aliases if alias and alias.strip()]
        new_state["name"] = normalized_name

        await self.entity_repo.update_basic_fields(
            entity_id,
            name=normalized_name,
            entity_type=normalized_type,
        )
        await self.update_state(
            entity_id,
            new_state,
            diff_summary={"manual_edit": True},
        )
        updated = await self.entity_repo.get_by_id(entity_id)
        if updated is None:
            raise ValueError("entity not found")
        return updated

    async def delete_entity(self, entity_id: str) -> None:
        entity = await self.entity_repo.get_by_id(entity_id)
        if entity is None:
            raise ValueError("entity not found")

        await self.relationship_repo.delete_by_entity_id(entity_id)
        await self.version_repo.delete_by_entity_id(entity_id)
        await self.entity_repo.delete(entity_id)
        await self.session.flush()
