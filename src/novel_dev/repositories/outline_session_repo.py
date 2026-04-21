import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import OutlineSession


class OutlineSessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(
        self,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
        status: str = "pending",
    ) -> OutlineSession:
        outline_session = OutlineSession(
            id=uuid.uuid4().hex,
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            status=status,
        )
        self.session.add(outline_session)

        try:
            await self.session.flush()
            return outline_session
        except IntegrityError:
            await self.session.rollback()
            result = await self.session.execute(
                select(OutlineSession).where(
                    OutlineSession.novel_id == novel_id,
                    OutlineSession.outline_type == outline_type,
                    OutlineSession.outline_ref == outline_ref,
                )
            )
            existing_session = result.scalar_one()
            return existing_session

    async def get_by_id(self, session_id: str) -> Optional[OutlineSession]:
        result = await self.session.execute(select(OutlineSession).where(OutlineSession.id == session_id))
        return result.scalar_one_or_none()
