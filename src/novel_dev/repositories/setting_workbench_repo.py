import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import (
    SettingGenerationMessage,
    SettingGenerationSession,
    SettingReviewBatch,
    SettingReviewChange,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


_UNSET = object()


class SettingWorkbenchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session(
        self,
        *,
        novel_id: str,
        title: str,
        target_categories: Optional[list[str]] = None,
        status: str = "clarifying",
        conversation_summary: Optional[str] = None,
        focused_target: Optional[dict] = None,
    ) -> SettingGenerationSession:
        session = SettingGenerationSession(
            id=_new_id("sgs_"),
            novel_id=novel_id,
            title=title,
            status=status,
            target_categories=target_categories or [],
            conversation_summary=conversation_summary,
            focused_target=focused_target,
        )
        self.session.add(session)
        await self.session.flush()
        return session

    async def get_session(self, session_id: str) -> Optional[SettingGenerationSession]:
        result = await self.session.execute(
            select(SettingGenerationSession).where(SettingGenerationSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_sessions(self, novel_id: str) -> list[SettingGenerationSession]:
        result = await self.session.execute(
            select(SettingGenerationSession)
            .where(SettingGenerationSession.novel_id == novel_id)
            .order_by(SettingGenerationSession.updated_at.desc(), SettingGenerationSession.created_at.desc())
        )
        return result.scalars().all()

    async def update_session_state(
        self,
        session_id: str,
        *,
        status: Optional[str] = None,
        clarification_round: Optional[int] = None,
        conversation_summary: Optional[str] = None,
        focused_target: Optional[dict] = None,
    ) -> Optional[SettingGenerationSession]:
        session = await self.get_session(session_id)
        if session is None:
            return None
        if status is not None:
            session.status = status
        if clarification_round is not None:
            session.clarification_round = clarification_round
        if conversation_summary is not None:
            session.conversation_summary = conversation_summary
        if focused_target is not None:
            session.focused_target = focused_target
        session.updated_at = datetime.utcnow()
        await self.session.flush()
        return session

    async def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> SettingGenerationMessage:
        message = SettingGenerationMessage(
            id=_new_id("sgm_"),
            session_id=session_id,
            role=role,
            content=content,
            meta=metadata,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_messages(self, session_id: str) -> list[SettingGenerationMessage]:
        result = await self.session.execute(
            select(SettingGenerationMessage)
            .where(SettingGenerationMessage.session_id == session_id)
            .order_by(SettingGenerationMessage.created_at.asc())
        )
        return result.scalars().all()

    async def create_review_batch(
        self,
        *,
        novel_id: str,
        source_type: str,
        source_file: Optional[str] = None,
        source_session_id: Optional[str] = None,
        summary: str = "",
        status: str = "pending",
        error_message: Optional[str] = None,
    ) -> SettingReviewBatch:
        if source_session_id is not None:
            source_session = await self.get_session(source_session_id)
            if source_session is None:
                raise ValueError("Source session not found")
            if source_session.novel_id != novel_id:
                raise ValueError("source session belongs to a different novel")

        batch = SettingReviewBatch(
            id=_new_id("srb_"),
            novel_id=novel_id,
            source_type=source_type,
            source_file=source_file,
            source_session_id=source_session_id,
            status=status,
            summary=summary,
            error_message=error_message,
        )
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def get_review_batch(self, batch_id: str) -> Optional[SettingReviewBatch]:
        result = await self.session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.id == batch_id)
        )
        return result.scalar_one_or_none()

    async def list_review_batches(self, novel_id: str) -> list[SettingReviewBatch]:
        result = await self.session.execute(
            select(SettingReviewBatch)
            .where(SettingReviewBatch.novel_id == novel_id)
            .order_by(SettingReviewBatch.updated_at.desc(), SettingReviewBatch.created_at.desc())
        )
        return result.scalars().all()

    async def update_batch_status(
        self,
        batch_id: str,
        status: str,
        error_message: object = _UNSET,
    ) -> Optional[SettingReviewBatch]:
        batch = await self.get_review_batch(batch_id)
        if batch is None:
            return None
        batch.status = status
        if error_message is not _UNSET:
            batch.error_message = error_message
        batch.updated_at = datetime.utcnow()
        await self.session.flush()
        return batch

    async def add_review_change(
        self,
        *,
        batch_id: str,
        target_type: str,
        operation: str,
        target_id: Optional[str] = None,
        before_snapshot: Optional[dict] = None,
        after_snapshot: Optional[dict] = None,
        conflict_hints: Optional[list] = None,
        source_session_id: Optional[str] = None,
        status: str = "pending",
        error_message: Optional[str] = None,
    ) -> SettingReviewChange:
        batch = await self.get_review_batch(batch_id)
        if batch is None:
            raise ValueError("Review batch not found")

        if source_session_id is not None:
            source_session = await self.get_session(source_session_id)
            if source_session is None:
                raise ValueError("Source session not found")
            if source_session.novel_id != batch.novel_id:
                raise ValueError("source session belongs to a different novel")

        change = SettingReviewChange(
            id=_new_id("src_"),
            batch_id=batch_id,
            target_type=target_type,
            operation=operation,
            target_id=target_id,
            status=status,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            conflict_hints=conflict_hints or [],
            source_session_id=source_session_id,
            error_message=error_message,
        )
        self.session.add(change)
        await self.session.flush()
        return change

    async def get_review_change(self, change_id: str) -> Optional[SettingReviewChange]:
        result = await self.session.execute(
            select(SettingReviewChange).where(SettingReviewChange.id == change_id)
        )
        return result.scalar_one_or_none()

    async def list_review_changes(self, batch_id: str) -> list[SettingReviewChange]:
        result = await self.session.execute(
            select(SettingReviewChange)
            .where(SettingReviewChange.batch_id == batch_id)
            .order_by(SettingReviewChange.created_at.asc())
        )
        return result.scalars().all()

    async def update_change_status(
        self,
        change_id: str,
        status: str,
        error_message: object = _UNSET,
    ) -> Optional[SettingReviewChange]:
        change = await self.get_review_change(change_id)
        if change is None:
            return None
        change.status = status
        if error_message is not _UNSET:
            change.error_message = error_message
        change.updated_at = datetime.utcnow()
        await self.session.flush()
        return change
