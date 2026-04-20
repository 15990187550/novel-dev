import math
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from novel_dev.db.models import NovelDocument
from novel_dev.schemas.similar_document import SimilarDocument


class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        doc_id: str,
        novel_id: str,
        doc_type: str,
        title: str,
        content: str,
        version: int = 1,
    ) -> NovelDocument:
        doc = NovelDocument(
            id=doc_id,
            novel_id=novel_id,
            doc_type=doc_type,
            title=title,
            content=content,
            version=version,
        )
        self.session.add(doc)
        await self.session.flush()
        return doc

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    async def similarity_search(
        self,
        novel_id: str,
        query_vector: List[float],
        limit: int = 5,
        doc_type_filter: Optional[str] = None,
    ) -> List[SimilarDocument]:
        dialect_name = self.session.bind.dialect.name if self.session.bind else "sqlite"

        if dialect_name == "postgresql":
            vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"
            sql = """
                SELECT id, doc_type, title, content,
                       1 - (vector_embedding <=> :query_vector) AS similarity
                FROM novel_documents
                WHERE novel_id = :novel_id
                  AND vector_embedding IS NOT NULL
            """
            params = {"novel_id": novel_id, "query_vector": vector_str}
            if doc_type_filter:
                sql += " AND doc_type = :doc_type"
                params["doc_type"] = doc_type_filter
            sql += " ORDER BY similarity DESC LIMIT :limit"
            params["limit"] = limit

            result = await self.session.execute(text(sql), params)
            rows = result.all()
            return [
                SimilarDocument(
                    doc_id=row.id,
                    doc_type=row.doc_type,
                    title=row.title,
                    content_preview=(row.content or "")[:600],
                    similarity_score=float(row.similarity),
                )
                for row in rows
            ]

        # SQLite fallback: load vectors and compute in Python
        stmt = select(NovelDocument).where(
            NovelDocument.novel_id == novel_id,
            NovelDocument.vector_embedding.is_not(None),
        )
        if doc_type_filter:
            stmt = stmt.where(NovelDocument.doc_type == doc_type_filter)

        result = await self.session.execute(stmt)
        docs = result.scalars().all()

        scored = []
        for doc in docs:
            emb = doc.vector_embedding
            if not emb:
                continue
            score = self._cosine_similarity(query_vector, emb)
            scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SimilarDocument(
                doc_id=doc.id,
                doc_type=doc.doc_type,
                title=doc.title,
                content_preview=(doc.content or "")[:600],
                similarity_score=score,
            )
            for score, doc in scored[:limit]
        ]

    async def get_by_id(self, doc_id: str) -> Optional[NovelDocument]:
        result = await self.session.execute(select(NovelDocument).where(NovelDocument.id == doc_id))
        return result.scalar_one_or_none()

    async def get_by_type(self, novel_id: str, doc_type: str) -> List[NovelDocument]:
        result = await self.session.execute(
            select(NovelDocument)
            .where(NovelDocument.novel_id == novel_id, NovelDocument.doc_type == doc_type)
            .order_by(NovelDocument.updated_at.desc())
        )
        return result.scalars().all()

    async def get_latest_by_type(self, novel_id: str, doc_type: str) -> Optional[NovelDocument]:
        """Return the document with the highest version number for the given novel and type."""
        result = await self.session.execute(
            select(NovelDocument)
            .where(NovelDocument.novel_id == novel_id, NovelDocument.doc_type == doc_type)
            .order_by(NovelDocument.version.desc())
        )
        return result.scalars().first()

    async def get_by_type_and_version(self, novel_id: str, doc_type: str, version: int) -> Optional[NovelDocument]:
        """Return the document matching the exact version for the given novel and type."""
        result = await self.session.execute(
            select(NovelDocument)
            .where(
                NovelDocument.novel_id == novel_id,
                NovelDocument.doc_type == doc_type,
                NovelDocument.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_novel(self, novel_id: str, doc_type: Optional[str] = None) -> List[NovelDocument]:
        stmt = select(NovelDocument).where(NovelDocument.novel_id == novel_id)
        if doc_type:
            stmt = stmt.where(NovelDocument.doc_type == doc_type)
        stmt = stmt.order_by(NovelDocument.updated_at.desc(), NovelDocument.id.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_id_for_novel(self, novel_id: str, doc_id: str) -> Optional[NovelDocument]:
        result = await self.session.execute(
            select(NovelDocument).where(
                NovelDocument.novel_id == novel_id,
                NovelDocument.id == doc_id,
            )
        )
        return result.scalar_one_or_none()
