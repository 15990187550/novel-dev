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
        diff_result: Optional[dict] = None,
        source_filename: Optional[str] = None,
        status: str = "pending",
        error_message: Optional[str] = None,
    ) -> PendingExtraction:
        pe = PendingExtraction(
            id=pe_id,
            novel_id=novel_id,
            source_filename=source_filename,
            extraction_type=extraction_type,
            status=status,
            raw_result=raw_result,
            proposed_entities=proposed_entities,
            diff_result=diff_result,
            error_message=error_message,
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

    async def update_payload(
        self,
        pe_id: str,
        *,
        extraction_type: str,
        raw_result: dict,
        proposed_entities: Optional[List[dict]] = None,
        diff_result: Optional[dict] = None,
        status: str = "pending",
        error_message: Optional[str] = None,
    ) -> None:
        pe = await self.get_by_id(pe_id)
        if pe:
            pe.extraction_type = extraction_type
            pe.raw_result = raw_result
            pe.proposed_entities = proposed_entities
            pe.diff_result = diff_result
            pe.status = status
            pe.error_message = error_message
            await self.session.flush()

    async def update_status(
        self,
        pe_id: str,
        status: str,
        resolution_result: Optional[dict] = None,
        error_message: Optional[str] = None,
    ) -> None:
        pe = await self.get_by_id(pe_id)
        if pe:
            pe.status = status
            if resolution_result is not None:
                pe.resolution_result = resolution_result
            pe.error_message = error_message
            await self.session.flush()

    async def delete(self, pe_id: str) -> bool:
        pe = await self.get_by_id(pe_id)
        if pe is None:
            return False
        await self.session.delete(pe)
        await self.session.flush()
        return True
