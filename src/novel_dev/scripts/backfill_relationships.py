import argparse
import asyncio
import json
import logging
import sys
from collections import defaultdict
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.engine import async_session_maker
from novel_dev.db.models import Entity, EntityRelationship, KnowledgeDomain, NovelDocument
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.services.relationship_extraction_service import (
    RelationshipExtractionResult,
    RelationshipExtractionService,
    RelationshipExtractor,
)

logger = logging.getLogger(__name__)

BACKFILL_DOC_TYPES = ("setting", "worldview", "concept", "synopsis")


class RelationshipBackfillService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        extractor: RelationshipExtractor | None = None,
        dry_run: bool = False,
        min_confidence: float = 0.65,
        limit: int | None = None,
        batch_size: int = 25,
    ):
        self.session = session
        self.entity_repo = EntityRepository(session)
        self.relationship_repo = RelationshipRepository(session)
        self.extractor = extractor
        self.dry_run = dry_run
        self.min_confidence = min_confidence
        self.limit = limit
        self.batch_size = max(1, batch_size)

    async def backfill_documents(
        self,
        novel_id: str,
        *,
        domain_id: str | None = None,
    ) -> dict[str, Any]:
        documents = await self._load_documents(novel_id, domain_id=domain_id)
        result = self._empty_result(source="documents")
        for doc in documents:
            domain = await self._domain_for_document(novel_id, doc)
            if domain_id and (domain is None or domain.id != domain_id):
                continue
            item_result = await self._process_source(
                novel_id=novel_id,
                source_text=doc.content,
                source_ref=f"{doc.title}:{doc.id}",
                source_meta={
                    "source_doc_id": doc.id,
                    "source_doc_title": doc.title,
                    "source_doc_type": doc.doc_type,
                },
                domain=domain,
            )
            self._merge_result(result, item_result)
            result["processed"] += 1
            if self.limit is not None and result["processed"] >= self.limit:
                break
        if not self.dry_run:
            await self._collapse_existing_backfill_duplicates(novel_id)
        return result

    async def backfill_entities(
        self,
        novel_id: str,
        *,
        domain_id: str | None = None,
    ) -> dict[str, Any]:
        entities = await self.entity_repo.list_by_novel(novel_id)
        result = self._empty_result(source="entities")
        sources: list[tuple[Entity, KnowledgeDomain | None]] = []
        for entity in entities:
            domain = await self._domain_for_entity(novel_id, entity)
            if domain_id and (domain is None or domain.id != domain_id):
                continue
            if not (entity.search_document or "").strip():
                continue
            sources.append((entity, domain))
            if self.limit is not None and len(sources) >= self.limit:
                break

        pending_batch: list[tuple[Entity, KnowledgeDomain | None]] = []
        batch_index = 0
        pending_domain_key: str | None = None
        for entity, domain in sources:
            domain_key = domain.id if domain else None
            if pending_batch and (len(pending_batch) >= self.batch_size or domain_key != pending_domain_key):
                batch_index += 1
                item_result = await self._process_entity_batch(
                    novel_id=novel_id,
                    batch=pending_batch,
                    batch_index=batch_index,
                )
                self._merge_result(result, item_result)
                result["processed"] += len(pending_batch)
                pending_batch = []
            pending_batch.append((entity, domain))
            pending_domain_key = domain_key

        if pending_batch:
            batch_index += 1
            item_result = await self._process_entity_batch(
                novel_id=novel_id,
                batch=pending_batch,
                batch_index=batch_index,
            )
            self._merge_result(result, item_result)
            result["processed"] += len(pending_batch)

        if not self.dry_run:
            await self._collapse_existing_backfill_duplicates(novel_id)
        return result

    async def _process_entity_batch(
        self,
        *,
        novel_id: str,
        batch: list[tuple[Entity, KnowledgeDomain | None]],
        batch_index: int,
    ) -> dict[str, Any]:
        source_rows = [
            {
                "entity_id": entity.id,
                "name": entity.name,
                "source_text": entity.search_document or "",
            }
            for entity, _ in batch
        ]
        domain = batch[0][1]
        source_ref = f"entities_batch:{batch_index}:{len(batch)}"
        source_meta = {
            "source_entity_ids": [entity.id for entity, _ in batch],
            "source_entity_names": [entity.name for entity, _ in batch],
            "source_batch_size": len(batch),
            "source_batch_index": batch_index,
        }
        return await self._process_source(
            novel_id=novel_id,
            source_text=json.dumps(source_rows, ensure_ascii=False),
            source_ref=source_ref,
            source_meta=source_meta,
            domain=domain,
        )

    async def backfill_all(
        self,
        novel_id: str,
        *,
        domain_id: str | None = None,
    ) -> dict[str, Any]:
        documents = await self.backfill_documents(novel_id, domain_id=domain_id)
        entities = await self.backfill_entities(novel_id, domain_id=domain_id)
        result = self._empty_result(source="all")
        self._merge_result(result, documents)
        self._merge_result(result, entities)
        result["processed"] = documents["processed"] + entities["processed"]
        return result

    async def _process_source(
        self,
        *,
        novel_id: str,
        source_text: str,
        source_ref: str,
        source_meta: dict[str, Any],
        domain: KnowledgeDomain | None,
    ) -> dict[str, Any]:
        result = self._empty_result(source="source")
        domain_id = domain.id if domain else None
        domain_name = domain.name if domain else None
        entities = await self.entity_repo.list_by_novel(novel_id)
        extractor_service = RelationshipExtractionService(self.session, extractor=self.extractor)
        candidates = extractor_service._serialize_candidates(
            entities,
            domain_id=domain_id,
            domain_name=domain_name,
        )
        if len(candidates) < 2:
            result["skipped"].append({"source_ref": source_ref, "reason": "not_enough_candidates"})
            return result

        try:
            extracted = await extractor_service._extract(novel_id, source_text, source_ref, candidates)
        except Exception as exc:
            result["errors"].append(
                {
                    "source_ref": source_ref,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            return result

        result["extracted"] += len(extracted.relationships)
        for relationship in extracted.relationships:
            if relationship.confidence < self.min_confidence:
                result["skipped"].append(
                    {
                        "source_ref": source_ref,
                        "source_entity_name": relationship.source_entity_name,
                        "target_entity_name": relationship.target_entity_name,
                        "relation_type": relationship.relation_type,
                        "confidence": relationship.confidence,
                        "reason": "below_min_confidence",
                    }
                )
                continue

            source = extractor_service._resolve_entity(
                entities,
                relationship.source_entity_name,
                domain_id,
                domain_name,
            )
            target = extractor_service._resolve_entity(
                entities,
                relationship.target_entity_name,
                domain_id,
                domain_name,
            )
            if source is None or target is None or source.id == target.id:
                result["skipped"].append(
                    {
                        "source_ref": source_ref,
                        "source_entity_name": relationship.source_entity_name,
                        "target_entity_name": relationship.target_entity_name,
                        "relation_type": relationship.relation_type,
                        "reason": "entity_not_found_or_ambiguous",
                    }
                )
                continue

            result["relationships"].append(
                {
                    "source_id": source.id,
                    "source_name": source.name,
                    "target_id": target.id,
                    "target_name": target.name,
                    "relation_type": relationship.relation_type,
                    "confidence": relationship.confidence,
                    "evidence": relationship.evidence,
                    "source_ref": source_ref,
                }
            )
            result["created"] += 1
            if self.dry_run:
                continue

            await self._upsert_backfill_relationship(
                source_id=source.id,
                target_id=target.id,
                relation_type=relationship.relation_type,
                meta={
                    "source": "relationship_backfill",
                    "source_ref": source_ref,
                    "evidence": relationship.evidence,
                    "confidence": relationship.confidence,
                    "source_role": relationship.source_role,
                    "target_role": relationship.target_role,
                    "domain_id": domain_id,
                    "domain_name": domain_name,
                    "raw_relation": relationship.model_dump(),
                    **source_meta,
                },
                novel_id=novel_id,
            )

        await self.session.flush()
        return result

    async def _upsert_backfill_relationship(
        self,
        *,
        source_id: str,
        target_id: str,
        relation_type: str,
        meta: dict[str, Any],
        novel_id: str,
    ) -> EntityRelationship:
        source_ref = meta.get("source_ref")
        stmt = select(EntityRelationship).where(
            EntityRelationship.source_id == source_id,
            EntityRelationship.target_id == target_id,
            EntityRelationship.is_active == True,
        )
        if novel_id is not None:
            stmt = stmt.where(EntityRelationship.novel_id == novel_id)
        rows = list((await self.session.execute(stmt.order_by(EntityRelationship.id.desc()))).scalars().all())
        backfill_matches = [
            row
            for row in rows
            if isinstance(row.meta, dict)
            and row.meta.get("source") == "relationship_backfill"
            and row.meta.get("source_ref") == source_ref
        ]
        if backfill_matches:
            existing = backfill_matches[0]
            for duplicate in backfill_matches[1:]:
                duplicate.is_active = False
            existing.relation_type = relation_type
            existing.meta = meta
            await self.session.flush()
            return existing

        return await self.relationship_repo.upsert(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            meta=meta,
            novel_id=novel_id,
        )

    async def _collapse_existing_backfill_duplicates(self, novel_id: str) -> None:
        stmt = select(EntityRelationship).where(
            EntityRelationship.novel_id == novel_id,
            EntityRelationship.is_active == True,
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        groups: dict[tuple[str, str, Any], list[EntityRelationship]] = defaultdict(list)
        for row in rows:
            if not isinstance(row.meta, dict):
                continue
            if row.meta.get("source") != "relationship_backfill":
                continue
            groups[(row.source_id, row.target_id, row.meta.get("source_ref"))].append(row)

        for matches in groups.values():
            if len(matches) < 2:
                continue
            winner = sorted(matches, key=self._backfill_dedupe_rank, reverse=True)[0]
            for row in matches:
                if row.id != winner.id:
                    row.is_active = False
        await self.session.flush()

    @staticmethod
    def _backfill_dedupe_rank(row: EntityRelationship) -> tuple[float, int, int]:
        confidence = 0.0
        if isinstance(row.meta, dict):
            try:
                confidence = float(row.meta.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0.0
        return (confidence, -len(row.relation_type or ""), row.id or 0)

    async def _load_documents(self, novel_id: str, *, domain_id: str | None) -> list[NovelDocument]:
        stmt = (
            select(NovelDocument)
            .where(
                NovelDocument.novel_id == novel_id,
                NovelDocument.doc_type.in_(BACKFILL_DOC_TYPES),
            )
            .order_by(NovelDocument.updated_at.asc(), NovelDocument.id.asc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        if domain_id is None:
            return rows

        domains = await self._load_domains(novel_id)
        allowed_doc_ids = {
            doc_id
            for domain in domains
            if domain.id == domain_id
            for doc_id in (domain.source_doc_ids or [])
        }
        return [doc for doc in rows if doc.id in allowed_doc_ids]

    async def _load_domains(self, novel_id: str) -> list[KnowledgeDomain]:
        result = await self.session.execute(
            select(KnowledgeDomain).where(KnowledgeDomain.novel_id == novel_id)
        )
        return list(result.scalars().all())

    async def _domain_for_document(self, novel_id: str, doc: NovelDocument) -> KnowledgeDomain | None:
        domains = await self._load_domains(novel_id)
        return next((domain for domain in domains if doc.id in (domain.source_doc_ids or [])), None)

    async def _domain_for_entity(self, novel_id: str, entity: Entity) -> KnowledgeDomain | None:
        domain_key = EntityRepository._search_document_domain_key(entity.search_document or "")
        if not domain_key:
            return None
        domains = await self._load_domains(novel_id)
        prefix, _, value = domain_key.partition(":")
        if prefix == "_knowledge_domain_id":
            return next((domain for domain in domains if domain.id == value), None)
        if prefix == "_knowledge_domain_name":
            return next((domain for domain in domains if domain.name == value), None)
        return None

    def _empty_result(self, *, source: str) -> dict[str, Any]:
        return {
            "source": source,
            "dry_run": self.dry_run,
            "processed": 0,
            "extracted": 0,
            "created": 0,
            "skipped": [],
            "errors": [],
            "relationships": [],
        }

    @staticmethod
    def _merge_result(target: dict[str, Any], source: dict[str, Any]) -> None:
        target["extracted"] += source.get("extracted", 0)
        target["created"] += source.get("created", 0)
        target["skipped"].extend(source.get("skipped", []))
        target["errors"].extend(source.get("errors", []))
        target["relationships"].extend(source.get("relationships", []))


async def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill entity relationships from historical content")
    parser.add_argument("--novel-id", required=True, help="Novel id to process")
    parser.add_argument(
        "--source",
        choices=["documents", "entities", "all"],
        default="documents",
        help="Historical source to process",
    )
    parser.add_argument("--domain-id", help="Limit to one knowledge domain")
    parser.add_argument("--limit", type=int, help="Maximum source records to process")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Number of entity sources per LLM call when --source includes entities",
    )
    parser.add_argument("--dry-run", action="store_true", help="Extract and report without writing relationships")
    parser.add_argument("--min-confidence", type=float, default=0.65, help="Minimum confidence to write")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    async with async_session_maker() as session:
        service = RelationshipBackfillService(
            session,
            dry_run=args.dry_run,
            min_confidence=args.min_confidence,
            limit=args.limit,
            batch_size=args.batch_size,
        )
        if args.source == "documents":
            result = await service.backfill_documents(args.novel_id, domain_id=args.domain_id)
        elif args.source == "entities":
            result = await service.backfill_entities(args.novel_id, domain_id=args.domain_id)
        else:
            result = await service.backfill_all(args.novel_id, domain_id=args.domain_id)

        if args.dry_run:
            await session.rollback()
        else:
            await session.commit()

    logger.info("relationship_backfill_result=%s", json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
