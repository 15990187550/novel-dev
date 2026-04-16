from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import NovelDocument


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
        vector_embedding: Optional[List[float]] = None,
    ) -> NovelDocument:
        doc = NovelDocument(
            id=doc_id,
            novel_id=novel_id,
            doc_type=doc_type,
            title=title,
            content=content,
            vector_embedding=vector_embedding,
        )
        self.session.add(doc)
        await self.session.flush()
        return doc

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
