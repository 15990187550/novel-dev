import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import OutlineMessage


class OutlineMessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        session_id: str,
        role: str,
        message_type: str,
        content: str,
        meta: Optional[dict] = None,
    ) -> OutlineMessage:
        message = OutlineMessage(
            id=uuid.uuid4().hex,
            session_id=session_id,
            role=role,
            message_type=message_type,
            content=content,
            meta=meta,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_recent(self, session_id: str, limit: int = 20) -> List[OutlineMessage]:
        result = await self.session.execute(
            select(OutlineMessage)
            .where(OutlineMessage.session_id == session_id)
            .order_by(OutlineMessage.created_at.desc(), OutlineMessage.id.desc())
            .limit(limit)
        )
        return result.scalars().all()
