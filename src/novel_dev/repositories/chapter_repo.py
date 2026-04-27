import math
from typing import Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from novel_dev.db.models import Chapter
from novel_dev.schemas.similar_document import SimilarDocument


class ChapterRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    async def create(
        self,
        chapter_id: str,
        volume_id: str,
        chapter_number: int,
        title: Optional[str] = None,
        novel_id: Optional[str] = None,
    ) -> Chapter:
        ch = Chapter(
            id=chapter_id,
            novel_id=novel_id,
            volume_id=volume_id,
            chapter_number=chapter_number,
            title=title,
        )
        self.session.add(ch)
        await self.session.flush()
        return ch

    async def ensure_from_plan(self, novel_id: str, volume_id: str, chapter_plan: Any) -> Chapter:
        if hasattr(chapter_plan, "model_dump"):
            plan = chapter_plan.model_dump()
        else:
            plan = dict(chapter_plan or {})

        chapter_id = plan.get("chapter_id")
        if not chapter_id:
            raise ValueError("chapter_plan missing chapter_id")

        existing = await self.get_by_id(chapter_id)
        if existing:
            changed = False
            if novel_id and existing.novel_id != novel_id:
                existing.novel_id = novel_id
                changed = True
            if volume_id and existing.volume_id != volume_id:
                existing.volume_id = volume_id
                changed = True
            chapter_number = int(plan.get("chapter_number") or existing.chapter_number or 1)
            if existing.chapter_number != chapter_number:
                existing.chapter_number = chapter_number
                changed = True
            title = plan.get("title")
            if title and existing.title != title:
                existing.title = title
                changed = True
            if changed:
                await self.session.flush()
            return existing

        return await self.create(
            chapter_id=chapter_id,
            volume_id=volume_id,
            chapter_number=int(plan.get("chapter_number") or 1),
            title=plan.get("title"),
            novel_id=novel_id,
        )

    async def get_by_id(self, chapter_id: str) -> Optional[Chapter]:
        result = await self.session.execute(select(Chapter).where(Chapter.id == chapter_id))
        return result.scalar_one_or_none()

    async def list_by_volume(self, volume_id: str) -> List[Chapter]:
        result = await self.session.execute(
            select(Chapter).where(Chapter.volume_id == volume_id).order_by(Chapter.chapter_number)
        )
        return result.scalars().all()

    async def update_text(self, chapter_id: str, raw_draft: Optional[str] = None, polished_text: Optional[str] = None) -> None:
        ch = await self.get_by_id(chapter_id)
        if ch:
            if raw_draft is not None:
                ch.raw_draft = raw_draft
            if polished_text is not None:
                ch.polished_text = polished_text
            await self.session.flush()

    async def update_scores(self, chapter_id: str, overall: int, breakdown: dict, feedback: dict) -> None:
        ch = await self.get_by_id(chapter_id)
        if ch:
            ch.score_overall = overall
            ch.score_breakdown = breakdown
            ch.review_feedback = feedback
            await self.session.flush()

    async def update_fast_review(self, chapter_id: str, score: int, feedback: dict) -> None:
        ch = await self.get_by_id(chapter_id)
        if ch:
            ch.fast_review_score = score
            ch.fast_review_feedback = feedback
            await self.session.flush()

    async def update_status(self, chapter_id: str, status: str) -> None:
        ch = await self.get_by_id(chapter_id)
        if ch:
            ch.status = status
            await self.session.flush()

    async def reset_generation(self, chapter_id: str) -> None:
        ch = await self.get_by_id(chapter_id)
        if ch:
            ch.status = "pending"
            ch.raw_draft = None
            ch.polished_text = None
            ch.score_overall = None
            ch.score_breakdown = None
            ch.review_feedback = None
            ch.fast_review_score = None
            ch.fast_review_feedback = None
            ch.vector_embedding = None
            await self.session.flush()

    async def get_previous_chapter(self, volume_id: str, chapter_number: int) -> Optional[Chapter]:
        result = await self.session.execute(
            select(Chapter)
            .where(Chapter.volume_id == volume_id, Chapter.chapter_number < chapter_number)
            .order_by(Chapter.chapter_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def similarity_search(
        self,
        novel_id: str,
        query_vector: List[float],
        limit: int = 5,
    ) -> List[SimilarDocument]:
        dialect_name = self.session.bind.dialect.name if self.session.bind else "sqlite"

        if dialect_name == "postgresql":
            vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"
            sql = """
                SELECT id, chapter_number, title, polished_text, raw_draft,
                       1 - (vector_embedding <=> :query_vector) AS similarity
                FROM chapters
                WHERE novel_id = :novel_id
                  AND vector_embedding IS NOT NULL
                ORDER BY similarity DESC LIMIT :limit
            """
            result = await self.session.execute(
                text(sql),
                {"novel_id": novel_id, "query_vector": vector_str, "limit": limit},
            )
            rows = result.all()
            return [
                SimilarDocument(
                    doc_id=row.id,
                    doc_type="chapter",
                    title=row.title or f"第{row.chapter_number}章",
                    content_preview=(row.polished_text or row.raw_draft or "")[:600],
                    similarity_score=float(row.similarity),
                )
                for row in rows
            ]

        # SQLite fallback: load vectors and compute in Python
        stmt = select(Chapter).where(
            Chapter.novel_id == novel_id,
            Chapter.vector_embedding.is_not(None),
        )
        result = await self.session.execute(stmt)
        chapters = result.scalars().all()

        scored = []
        for ch in chapters:
            emb = ch.vector_embedding
            if not emb:
                continue
            score = self._cosine_similarity(query_vector, emb)
            scored.append((score, ch))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SimilarDocument(
                doc_id=ch.id,
                doc_type="chapter",
                title=ch.title or f"第{ch.chapter_number}章",
                content_preview=(ch.polished_text or ch.raw_draft or "")[:600],
                similarity_score=score,
            )
            for score, ch in scored[:limit]
        ]
