import math
from datetime import datetime
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, text

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
                  AND (doc_type, title, version, updated_at) IN (
                    SELECT doc_type, title, version, updated_at
                    FROM (
                      SELECT doc_type, title, version, updated_at,
                             ROW_NUMBER() OVER (
                               PARTITION BY doc_type, title
                               ORDER BY version DESC, updated_at DESC
                             ) AS rn
                      FROM novel_documents
                      WHERE novel_id = :novel_id
                    ) latest_docs
                    WHERE rn = 1
                  )
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
        docs = self._latest_documents_by_type_title(docs)

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

    async def archive_for_consolidation(
        self,
        doc_id: str,
        *,
        novel_id: str,
        batch_id: str,
        change_id: str,
        reason: str = "setting_consolidation",
    ) -> Optional[NovelDocument]:
        result = await self.session.execute(
            select(NovelDocument).where(
                NovelDocument.id == doc_id,
                NovelDocument.novel_id == novel_id,
            )
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            return None
        doc.archived_at = datetime.utcnow()
        doc.archive_reason = reason
        doc.archived_by_consolidation_batch_id = batch_id
        doc.archived_by_consolidation_change_id = change_id
        await self.session.flush()
        return doc

    async def get_by_type(self, novel_id: str, doc_type: str) -> List[NovelDocument]:
        result = await self.session.execute(
            select(NovelDocument)
            .where(NovelDocument.novel_id == novel_id, NovelDocument.doc_type == doc_type)
            .order_by(NovelDocument.updated_at.desc())
        )
        return result.scalars().all()

    async def get_current_by_type(self, novel_id: str, doc_type: str) -> List[NovelDocument]:
        latest_stmt = (
            select(
                NovelDocument.id.label("id"),
                NovelDocument.title.label("title"),
                NovelDocument.version.label("version"),
                NovelDocument.updated_at.label("updated_at"),
                func.row_number()
                .over(
                    partition_by=NovelDocument.title,
                    order_by=(NovelDocument.version.desc(), NovelDocument.updated_at.desc()),
                )
                .label("rn"),
            )
            .where(
                NovelDocument.novel_id == novel_id,
                NovelDocument.doc_type == doc_type,
                NovelDocument.archived_at.is_(None),
            )
            .subquery()
        )
        result = await self.session.execute(
            select(NovelDocument)
            .where(
                NovelDocument.novel_id == novel_id,
                NovelDocument.doc_type == doc_type,
                NovelDocument.archived_at.is_(None),
                NovelDocument.id.in_(select(latest_stmt.c.id).where(latest_stmt.c.rn == 1)),
            )
            .order_by(NovelDocument.updated_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    def _latest_documents_by_type_title(docs: List[NovelDocument]) -> List[NovelDocument]:
        latest_by_key: dict[tuple[str, str], NovelDocument] = {}
        for doc in docs:
            key = (doc.doc_type, doc.title)
            current = latest_by_key.get(key)
            if current is None:
                latest_by_key[key] = doc
                continue
            current_version = current.version or 0
            doc_version = doc.version or 0
            current_updated = current.updated_at
            doc_updated = doc.updated_at
            if doc_version > current_version or (
                doc_version == current_version
                and doc_updated is not None
                and (current_updated is None or doc_updated > current_updated)
            ):
                latest_by_key[key] = doc
        return list(latest_by_key.values())

    async def get_latest_by_type(self, novel_id: str, doc_type: str) -> Optional[NovelDocument]:
        """Return the document with the highest version number for the given novel and type."""
        result = await self.session.execute(
            select(NovelDocument)
            .where(NovelDocument.novel_id == novel_id, NovelDocument.doc_type == doc_type)
            .order_by(NovelDocument.version.desc())
        )
        return result.scalars().first()

    async def get_by_type_and_title(self, novel_id: str, doc_type: str, title: str) -> List[NovelDocument]:
        result = await self.session.execute(
            select(NovelDocument)
            .where(
                NovelDocument.novel_id == novel_id,
                NovelDocument.doc_type == doc_type,
                NovelDocument.title == title,
            )
            .order_by(NovelDocument.version.desc(), NovelDocument.updated_at.desc())
        )
        return result.scalars().all()

    async def get_latest_by_type_and_title(
        self,
        novel_id: str,
        doc_type: str,
        title: str,
    ) -> Optional[NovelDocument]:
        result = await self.session.execute(
            select(NovelDocument)
            .where(
                NovelDocument.novel_id == novel_id,
                NovelDocument.doc_type == doc_type,
                NovelDocument.title == title,
            )
            .order_by(NovelDocument.version.desc(), NovelDocument.updated_at.desc())
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
