import argparse
import asyncio
import logging
import sys
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.engine import async_session_maker
from novel_dev.db.models import NovelDocument, Entity, Chapter
from novel_dev.llm import llm_factory
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class BackfillService:
    """Backfill vector embeddings for existing documents, entities, and chapters."""

    def __init__(
        self,
        session: AsyncSession,
        embedding_service: EmbeddingService,
        batch_size: int = 50,
    ):
        self.session = session
        self.embedding_service = embedding_service
        self.batch_size = batch_size

    async def backfill_all(self, novel_id: Optional[str] = None) -> dict:
        """Backfill all types. Returns counts per type."""
        counts = {}
        counts["documents"] = await self.backfill_documents(novel_id)
        counts["entities"] = await self.backfill_entities(novel_id)
        counts["chapters"] = await self.backfill_chapters(novel_id)
        return counts

    async def _fetch_unembedded_documents(self, novel_id: Optional[str] = None) -> list:
        """Fetch documents without embeddings. Works around SQLite JSON null handling."""
        stmt = select(NovelDocument)
        if novel_id:
            stmt = stmt.where(NovelDocument.novel_id == novel_id)
        result = await self.session.execute(stmt)
        return [d for d in result.scalars().all() if not d.vector_embedding]

    async def backfill_documents(self, novel_id: Optional[str] = None) -> int:
        """Backfill document embeddings. Returns number processed."""
        total = 0
        while True:
            docs = await self._fetch_unembedded_documents(novel_id)
            docs = docs[: self.batch_size]
            if not docs:
                break

            texts = []
            valid_docs = []
            for doc in docs:
                if doc.content:
                    texts.append(doc.content[: self.embedding_service.max_query_length])
                    valid_docs.append(doc)

            if texts:
                try:
                    vectors = await self.embedding_service.embedder.aembed(texts)
                    for doc, vector in zip(valid_docs, vectors):
                        doc.vector_embedding = vector
                    await self.session.flush()
                except Exception as exc:
                    logger.error(f"batch doc embedding failed: {exc}")
                    # Fallback: process one by one
                    for doc in valid_docs:
                        try:
                            await self.embedding_service.index_document(doc.id)
                        except Exception as inner_exc:
                            logger.warning(
                                "fallback doc embedding failed",
                                extra={"doc_id": doc.id, "error": str(inner_exc)},
                            )

            await self.session.commit()
            total += len(docs)
            logger.info(f"backfill_documents: {total} total processed")

        logger.info(f"backfill_documents complete: {total} documents")
        return total

    async def _fetch_unembedded_entities(self, novel_id: Optional[str] = None) -> list:
        """Fetch entities without embeddings. Works around SQLite JSON null handling."""
        stmt = select(Entity)
        if novel_id:
            stmt = stmt.where(Entity.novel_id == novel_id)
        result = await self.session.execute(stmt)
        return [e for e in result.scalars().all() if not e.vector_embedding]

    async def backfill_entities(self, novel_id: Optional[str] = None) -> int:
        """Backfill entity embeddings. Returns number processed."""
        version_repo = EntityVersionRepository(self.session)
        total = 0
        while True:
            entities = await self._fetch_unembedded_entities(novel_id)
            entities = entities[: self.batch_size]
            if not entities:
                break

            texts = []
            valid_entities = []
            for entity in entities:
                version = await version_repo.get_latest(entity.id)
                state = version.state if version else {}
                text = self.embedding_service._flatten_entity_state(
                    entity.name, entity.type, state
                )
                texts.append(text[: self.embedding_service.max_query_length])
                valid_entities.append(entity)

            if texts:
                try:
                    vectors = await self.embedding_service.embedder.aembed(texts)
                    for entity, vector in zip(valid_entities, vectors):
                        entity.vector_embedding = vector
                    await self.session.flush()
                except Exception as exc:
                    logger.error(f"batch entity embedding failed: {exc}")
                    for entity in valid_entities:
                        try:
                            await self.embedding_service.index_entity(entity.id)
                        except Exception as inner_exc:
                            logger.warning(
                                "fallback entity embedding failed",
                                extra={"entity_id": entity.id, "error": str(inner_exc)},
                            )

            await self.session.commit()
            total += len(entities)
            logger.info(f"backfill_entities: {total} total processed")

        logger.info(f"backfill_entities complete: {total} entities")
        return total

    async def _fetch_unembedded_chapters(self, novel_id: Optional[str] = None) -> list:
        """Fetch chapters without embeddings. Works around SQLite JSON null handling."""
        stmt = select(Chapter)
        if novel_id:
            stmt = stmt.where(Chapter.novel_id == novel_id)
        result = await self.session.execute(stmt)
        return [c for c in result.scalars().all() if not c.vector_embedding]

    async def backfill_chapters(self, novel_id: Optional[str] = None) -> int:
        """Backfill chapter embeddings. Returns number processed."""
        total = 0
        while True:
            chapters = await self._fetch_unembedded_chapters(novel_id)
            chapters = chapters[: self.batch_size]
            if not chapters:
                break

            texts = []
            valid_chapters = []
            for ch in chapters:
                text = (ch.polished_text or ch.raw_draft or "")[:2000]
                if text:
                    texts.append(text[: self.embedding_service.max_query_length])
                    valid_chapters.append(ch)

            if texts:
                try:
                    vectors = await self.embedding_service.embedder.aembed(texts)
                    for ch, vector in zip(valid_chapters, vectors):
                        ch.vector_embedding = vector
                    await self.session.flush()
                except Exception as exc:
                    logger.error(f"batch chapter embedding failed: {exc}")
                    for ch in valid_chapters:
                        try:
                            await self.embedding_service.index_chapter(ch.id)
                        except Exception as inner_exc:
                            logger.warning(
                                "fallback chapter embedding failed",
                                extra={"chapter_id": ch.id, "error": str(inner_exc)},
                            )

            await self.session.commit()
            total += len(chapters)
            logger.info(f"backfill_chapters: {total} total processed")

        logger.info(f"backfill_chapters complete: {total} chapters")
        return total


async def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill embeddings for existing data")
    parser.add_argument("--novel-id", help="Limit to specific novel")
    parser.add_argument(
        "--batch-size", type=int, default=50, help="Batch size for processing"
    )
    parser.add_argument(
        "--types",
        nargs="+",
        choices=["documents", "entities", "chapters", "all"],
        default=["all"],
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    embedder = llm_factory.get_embedder()

    async with async_session_maker() as session:
        embedding_service = EmbeddingService(session, embedder)
        backfill = BackfillService(
            session, embedding_service, batch_size=args.batch_size
        )

        types = set(args.types)
        if "all" in types:
            counts = await backfill.backfill_all(args.novel_id)
        else:
            counts = {}
            if "documents" in types:
                counts["documents"] = await backfill.backfill_documents(args.novel_id)
            if "entities" in types:
                counts["entities"] = await backfill.backfill_entities(args.novel_id)
            if "chapters" in types:
                counts["chapters"] = await backfill.backfill_chapters(args.novel_id)

    total = sum(counts.values())
    logger.info(f"Backfill complete. Processed: {counts} (total={total})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
