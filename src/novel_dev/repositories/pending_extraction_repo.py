from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import PendingExtraction


class PendingExtractionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        pe_id: str,
        novel_id: str,
        extraction_type: str,
        raw_result: dict,
        proposed_entities: Optional[List[dict]] = None,
    ) -> PendingExtraction:
        pe = PendingExtraction(
            id=pe_id,
            novel_id=novel_id,
            extraction_type=extraction_type,
            raw_result=raw_result,
            proposed_entities=proposed_entities,
        )
        self.session.add(pe)
        await self.session.flush()
        return pe

    async def get_by_id(self, pe_id: str) -> Optional[PendingExtraction]:
        result = await self.session.execute(select(PendingExtraction).where(PendingExtraction.id == pe_id))
        return result.scalar_one_or_none()

    async def list_by_novel(self, novel_id: str) -> List[PendingExtraction]:
        result = await self.session.execute(
            select(PendingExtraction)
            .where(PendingExtraction.novel_id == novel_id)
            .order_by(PendingExtraction.created_at.desc())
        )
        return result.scalars().all()

    async def update_status(self, pe_id: str, status: str) -> None:
        pe = await self.get_by_id(pe_id)
        if pe:
            pe.status = status
            await self.session.flush()
