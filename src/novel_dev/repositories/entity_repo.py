import math
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from novel_dev.db.models import Entity
from novel_dev.schemas.similar_document import SimilarDocument


class EntityRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, entity_id: str, entity_type: str, name: str, created_at_chapter_id: Optional[str] = None, novel_id: Optional[str] = None) -> Entity:
        entity = Entity(
            id=entity_id,
            type=entity_type,
            name=name,
            created_at_chapter_id=created_at_chapter_id,
            novel_id=novel_id,
        )
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def get_by_id(self, entity_id: str) -> Optional[Entity]:
        result = await self.session.execute(select(Entity).where(Entity.id == entity_id))
        return result.scalar_one_or_none()

    async def find_by_name(self, name: str, entity_type: Optional[str] = None, novel_id: Optional[str] = None) -> Optional[Entity]:
        stmt = select(Entity).where(Entity.name == name)
        if entity_type is not None:
            stmt = stmt.where(Entity.type == entity_type)
        if novel_id is not None:
            stmt = stmt.where(Entity.novel_id == novel_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_version(self, entity_id: str, new_version: int) -> None:
        entity = await self.get_by_id(entity_id)
        if entity:
            entity.current_version = new_version
            await self.session.flush()

    async def find_by_names(self, names: List[str], novel_id: Optional[str] = None) -> List[Entity]:
        if not names:
            return []
        stmt = select(Entity).where(Entity.name.in_(names))
        if novel_id is not None:
            stmt = stmt.where(Entity.novel_id == novel_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_by_novel(self, novel_id: str) -> List[Entity]:
        result = await self.session.execute(
            select(Entity).where(Entity.novel_id == novel_id)
        )
        return result.scalars().all()

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
        type_filter: Optional[str] = None,
    ) -> List[SimilarDocument]:
        dialect_name = self.session.bind.dialect.name if self.session.bind else "sqlite"

        if dialect_name == "postgresql":
            return await self._similarity_search_postgres(novel_id, query_vector, limit, type_filter)
        return await self._similarity_search_sqlite(novel_id, query_vector, limit, type_filter)

    async def _similarity_search_postgres(
        self,
        novel_id: str,
        query_vector: List[float],
        limit: int,
        type_filter: Optional[str],
    ) -> List[SimilarDocument]:
        vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"
        sql = """
            SELECT id, type, name,
                   1 - (vector_embedding <=> :query_vector) AS similarity
            FROM entities
            WHERE novel_id = :novel_id
              AND vector_embedding IS NOT NULL
        """
        params = {"novel_id": novel_id, "query_vector": vector_str}
        if type_filter:
            sql += " AND type = :type_filter"
            params["type_filter"] = type_filter
        sql += " ORDER BY similarity DESC LIMIT :limit"
        params["limit"] = limit

        result = await self.session.execute(text(sql), params)
        rows = result.all()
        return [
            SimilarDocument(
                doc_id=row.id,
                doc_type=row.type,
                title=row.name,
                content_preview=f"{row.name} ({row.type})",
                similarity_score=float(row.similarity),
            )
            for row in rows
        ]

    async def _similarity_search_sqlite(
        self,
        novel_id: str,
        query_vector: List[float],
        limit: int,
        type_filter: Optional[str],
    ) -> List[SimilarDocument]:
        stmt = select(Entity).where(
            Entity.novel_id == novel_id,
            Entity.vector_embedding.is_not(None),
        )
        if type_filter:
            stmt = stmt.where(Entity.type == type_filter)

        result = await self.session.execute(stmt)
        entities = result.scalars().all()

        scored = []
        for entity in entities:
            emb = entity.vector_embedding
            if not emb:
                continue
            score = self._cosine_similarity(query_vector, emb)
            scored.append((score, entity))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SimilarDocument(
                doc_id=entity.id,
                doc_type=entity.type,
                title=entity.name,
                content_preview=f"{entity.name} ({entity.type})",
                similarity_score=score,
            )
            for score, entity in scored[:limit]
        ]
