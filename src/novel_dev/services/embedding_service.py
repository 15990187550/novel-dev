import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.llm.embedder import BaseEmbedder
from novel_dev.repositories.document_repo import DocumentRepository
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
        doc.vector_embedding = vector
        await self.session.flush()

    async def search_similar(
        self,
        novel_id: str,
        query_text: str,
        limit: int = 5,
        doc_type_filter: Optional[str] = None,
    ) -> list[SimilarDocument]:
        query_vector = await self.generate_embedding(query_text)
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
        repo = DocumentRepository(self.session)
        return await repo.similarity_search(
            novel_id, query_vector, limit, doc_type_filter
        )
