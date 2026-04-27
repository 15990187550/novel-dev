import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from novel_dev.db.models import Chapter, Entity, NovelDocument
from novel_dev.llm.embedder import BaseEmbedder
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.schemas.similar_document import SimilarDocument

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(
        self,
        session: AsyncSession,
        embedder: BaseEmbedder,
        max_query_length: int = 8000,
    ):
        self.session = session
        self.embedder = embedder
        self.max_query_length = max_query_length

    async def generate_embedding(self, text: str) -> list[float]:
        truncated = text[: self.max_query_length]
        vectors = await self.embedder.aembed([truncated])
        return vectors[0]

    def _vector_dimensions_match(self, column, vector: list[float], label: str, record_id: str) -> bool:
        bind = self.session.get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return True
        expected = getattr(getattr(column, "type", None), "dimensions", None)
        actual = len(vector)
        if expected is None or actual == expected:
            return True
        logger.warning(
            label,
            extra={
                "record_id": record_id,
                "expected_dimensions": expected,
                "actual_dimensions": actual,
            },
        )
        return False

    async def index_document(self, doc_id: str) -> None:
        repo = DocumentRepository(self.session)
        doc = await repo.get_by_id(doc_id)
        if not doc or not doc.content:
            return
        try:
            vector = await self.generate_embedding(doc.content)
        except Exception as exc:
            logger.warning(
                "embedding_generation_failed",
                extra={"doc_id": doc_id, "error": str(exc)},
            )
            return
        if not self._vector_dimensions_match(
            NovelDocument.__table__.c.vector_embedding,
            vector,
            "document_embedding_dimension_mismatch",
            doc_id,
        ):
            return
        await self._store_vector(doc, "vector_embedding", vector, "document_embedding_store_failed", doc_id)

    async def search_similar(
        self,
        novel_id: str,
        query_text: str,
        limit: int = 5,
        doc_type_filter: Optional[str] = None,
    ) -> list[SimilarDocument]:
        query_vector = await self.generate_embedding(query_text)
        if not self._vector_dimensions_match(
            NovelDocument.__table__.c.vector_embedding,
            query_vector,
            "document_query_embedding_dimension_mismatch",
            novel_id,
        ):
            return []
        repo = DocumentRepository(self.session)
        return await repo.similarity_search(
            novel_id, query_vector, limit, doc_type_filter
        )

    async def search_similar_by_vector(
        self,
        novel_id: str,
        query_vector: list[float],
        limit: int = 5,
        doc_type_filter: Optional[str] = None,
    ) -> list[SimilarDocument]:
        if not self._vector_dimensions_match(
            NovelDocument.__table__.c.vector_embedding,
            query_vector,
            "document_query_vector_dimension_mismatch",
            novel_id,
        ):
            return []
        repo = DocumentRepository(self.session)
        return await repo.similarity_search(
            novel_id, query_vector, limit, doc_type_filter
        )

    async def index_entity(self, entity_id: str) -> None:
        entity_repo = EntityRepository(self.session)
        version_repo = EntityVersionRepository(self.session)
        entity = await entity_repo.get_by_id(entity_id)
        if not entity:
            return
        version = await version_repo.get_latest(entity_id)
        state = version.state if version else {}
        text = self._flatten_entity_state(entity.name, entity.type, state)
        try:
            vector = await self.generate_embedding(text)
        except Exception as exc:
            logger.warning("entity_embedding_failed", extra={"entity_id": entity_id, "error": str(exc)})
            return
        if not self._vector_dimensions_match(
            Entity.__table__.c.vector_embedding,
            vector,
            "entity_embedding_dimension_mismatch",
            entity_id,
        ):
            return
        await self._store_vector(entity, "vector_embedding", vector, "entity_embedding_store_failed", entity_id)

    async def index_entity_search(self, entity_id: str) -> None:
        entity_repo = EntityRepository(self.session)
        version_repo = EntityVersionRepository(self.session)
        entity = await entity_repo.get_by_id(entity_id)
        if not entity:
            return
        version = await version_repo.get_latest(entity_id)
        state = version.state if version else {}
        text = self._flatten_entity_search_document(entity, state)
        try:
            vector = await self.generate_embedding(text)
        except Exception as exc:
            logger.warning("entity_search_embedding_failed", extra={"entity_id": entity_id, "error": str(exc)})
            return
        if not self._vector_dimensions_match(
            Entity.__table__.c.search_vector_embedding,
            vector,
            "entity_search_embedding_dimension_mismatch",
            entity_id,
        ):
            return
        try:
            async with self.session.begin_nested():
                entity.search_document = text
                entity.search_vector_embedding = vector
                await self.session.flush()
        except SQLAlchemyError as exc:
            logger.warning("entity_search_embedding_store_failed", extra={"entity_id": entity_id, "error": str(exc)})

    @staticmethod
    def _flatten_entity_state(name: str, entity_type: str, state: dict) -> str:
        parts = [f"名称：{name}", f"类型：{entity_type}"]
        for key, value in state.items():
            if isinstance(value, dict):
                sub = ", ".join(f"{k}={v}" for k, v in value.items())
                parts.append(f"{key}：{sub}")
            else:
                parts.append(f"{key}：{value}")
        return "\n".join(parts)[:8000]

    @staticmethod
    def _flatten_entity_search_document(entity: Entity, state: dict) -> str:
        effective_category = entity.manual_category or entity.system_category or "其他"
        parts = [
            f"名称：{entity.name}",
            f"类型：{entity.type}",
            f"一级分类：{effective_category}",
        ]
        if entity.system_needs_review:
            parts.append("分类状态：待复核")
        for key, value in state.items():
            if isinstance(value, dict):
                sub = ", ".join(f"{k}={v}" for k, v in value.items())
                parts.append(f"{key}：{sub}")
            else:
                parts.append(f"{key}：{value}")
        return "\n".join(parts)[:8000]

    async def search_similar_entities(
        self,
        novel_id: str,
        query_text: str,
        limit: int = 5,
        type_filter: Optional[str] = None,
    ) -> list[SimilarDocument]:
        query_vector = await self.generate_embedding(query_text)
        if not self._vector_dimensions_match(
            Entity.__table__.c.vector_embedding,
            query_vector,
            "entity_query_embedding_dimension_mismatch",
            novel_id,
        ):
            return []
        repo = EntityRepository(self.session)
        return await repo.similarity_search(novel_id, query_vector, limit, type_filter)

    async def index_chapter(self, chapter_id: str) -> None:
        repo = ChapterRepository(self.session)
        ch = await repo.get_by_id(chapter_id)
        if not ch:
            return
        text = ch.polished_text or ch.raw_draft or ""
        if not text:
            return
        # Use first 2000 chars as representative sample
        text = text[:2000]
        try:
            vector = await self.generate_embedding(text)
        except Exception as exc:
            logger.warning("chapter_embedding_failed", extra={"chapter_id": chapter_id, "error": str(exc)})
            return
        if not self._vector_dimensions_match(
            Chapter.__table__.c.vector_embedding,
            vector,
            "chapter_embedding_dimension_mismatch",
            chapter_id,
        ):
            return
        await self._store_vector(ch, "vector_embedding", vector, "chapter_embedding_store_failed", chapter_id)

    async def _store_vector(self, model, attr: str, vector: list[float], label: str, record_id: str) -> None:
        try:
            async with self.session.begin_nested():
                setattr(model, attr, vector)
                await self.session.flush()
        except SQLAlchemyError as exc:
            logger.warning(label, extra={"record_id": record_id, "error": str(exc)})

    async def search_similar_chapters(
        self,
        novel_id: str,
        query_text: str,
        limit: int = 3,
    ) -> list[SimilarDocument]:
        query_vector = await self.generate_embedding(query_text)
        if not self._vector_dimensions_match(
            Chapter.__table__.c.vector_embedding,
            query_vector,
            "chapter_query_embedding_dimension_mismatch",
            novel_id,
        ):
            return []
        repo = ChapterRepository(self.session)
        return await repo.similarity_search(novel_id, query_vector, limit)
