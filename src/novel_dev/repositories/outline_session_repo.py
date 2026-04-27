import uuid
from typing import Optional

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import OutlineSession


class OutlineSessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _find_cached_session(self, novel_id: str, outline_type: str, outline_ref: str) -> Optional[OutlineSession]:
        deleted_sessions = set(self.session.deleted)
        for candidate in list(self.session.new) + list(self.session.identity_map.values()):
            if candidate in deleted_sessions or inspect(candidate).deleted:
                continue
            if isinstance(candidate, OutlineSession) and (
                candidate.novel_id == novel_id
                and candidate.outline_type == outline_type
                and candidate.outline_ref == outline_ref
            ):
                return candidate
        return None

    async def get_or_create(
        self,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
        status: str = "pending",
    ) -> OutlineSession:
        existing_session = await self.get_existing(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
        )
        if existing_session is not None:
            return existing_session

        outline_session = OutlineSession(
            id=uuid.uuid4().hex,
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            status=status,
        )

        try:
            async with self.session.begin_nested():
                self.session.add(outline_session)
                await self.session.flush()
            return outline_session
        except IntegrityError:
            with self.session.no_autoflush:
                result = await self.session.execute(
                    select(OutlineSession).where(
                        OutlineSession.novel_id == novel_id,
                        OutlineSession.outline_type == outline_type,
                        OutlineSession.outline_ref == outline_ref,
                    )
                )
            existing_session = result.scalar_one()
            return existing_session

    async def get_existing(
        self,
        novel_id: str,
        outline_type: str,
        outline_ref: str,
    ) -> Optional[OutlineSession]:
        cached_session = self._find_cached_session(novel_id, outline_type, outline_ref)
        if cached_session is not None:
            return cached_session

        with self.session.no_autoflush:
            result = await self.session.execute(
                select(OutlineSession).where(
                    OutlineSession.novel_id == novel_id,
                    OutlineSession.outline_type == outline_type,
                    OutlineSession.outline_ref == outline_ref,
                )
            )
        existing_session = result.scalar_one_or_none()
        if existing_session is not None and (
            existing_session in self.session.deleted or inspect(existing_session).deleted
        ):
            return None
        return existing_session

    async def get_by_id(self, session_id: str) -> Optional[OutlineSession]:
        result = await self.session.execute(select(OutlineSession).where(OutlineSession.id == session_id))
        return result.scalar_one_or_none()
