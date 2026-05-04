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


_UNSET = object()


class SettingWorkbenchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session(
        self,
        *,
        novel_id: str,
        title: str,
        target_categories: list[str] | None = None,
    ) -> SettingGenerationSession:
        item = SettingGenerationSession(
            id=uuid.uuid4().hex,
            novel_id=novel_id,
            title=title,
            status="clarifying",
            target_categories=target_categories or [],
            clarification_round=0,
        )
        self.session.add(item)
        await self.session.flush()
        return item

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
        return list(result.scalars().all())

    async def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> SettingGenerationMessage:
        message = SettingGenerationMessage(
            id=uuid.uuid4().hex,
            session_id=session_id,
            role=role,
            content=content,
            meta=metadata or {},
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
        return list(result.scalars().all())

    async def create_review_batch(
        self,
        *,
        novel_id: str,
        source_type: str,
        summary: str = "",
        input_snapshot: dict | None = None,
        source_file: str | None = None,
        source_session_id: str | None = None,
        job_id: str | None = None,
        status: str = "pending",
    ) -> SettingReviewBatch:
        batch = SettingReviewBatch(
            id=uuid.uuid4().hex,
            novel_id=novel_id,
            source_type=source_type,
            source_file=source_file,
            source_session_id=source_session_id,
            job_id=job_id,
            status=status,
            summary=summary,
            input_snapshot=input_snapshot or {},
        )
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def get_review_batch(self, batch_id: str) -> Optional[SettingReviewBatch]:
        result = await self.session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.id == batch_id)
        )
        return result.scalar_one_or_none()

    async def get_review_batch_by_job(self, job_id: str) -> Optional[SettingReviewBatch]:
        result = await self.session.execute(
            select(SettingReviewBatch)
            .where(SettingReviewBatch.job_id == job_id)
            .order_by(
                SettingReviewBatch.updated_at.desc(),
                SettingReviewBatch.created_at.desc(),
                SettingReviewBatch.id.desc(),
            )
            .limit(1)
        )
        return result.scalars().first()

    async def list_review_batches(self, novel_id: str) -> list[SettingReviewBatch]:
        result = await self.session.execute(
            select(SettingReviewBatch)
            .where(SettingReviewBatch.novel_id == novel_id)
            .order_by(
                SettingReviewBatch.updated_at.desc(),
                SettingReviewBatch.created_at.desc(),
                SettingReviewBatch.id.desc(),
            )
        )
        return list(result.scalars().all())

    async def add_review_change(
        self,
        *,
        batch_id: str,
        target_type: str,
        operation: str,
        target_id: str | None = None,
        before_snapshot: dict | None = None,
        after_snapshot: dict | None = None,
        conflict_hints: list | None = None,
        source_session_id: str | None = None,
        status: str = "pending",
    ) -> SettingReviewChange:
        change = SettingReviewChange(
            id=uuid.uuid4().hex,
            batch_id=batch_id,
            target_type=target_type,
            operation=operation,
            target_id=target_id,
            status=status,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            conflict_hints=conflict_hints or [],
            source_session_id=source_session_id,
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
            .order_by(SettingReviewChange.created_at.asc(), SettingReviewChange.id.asc())
        )
        return list(result.scalars().all())

    async def mark_change_status(
        self,
        change_id: str,
        status: str,
        *,
        after_snapshot: dict | None = None,
        error_message: object = _UNSET,
    ) -> Optional[SettingReviewChange]:
        change = await self.get_review_change(change_id)
        if change is None:
            return None
        change.status = status
        if after_snapshot is not None:
            change.after_snapshot = after_snapshot
        if error_message is not _UNSET:
            change.error_message = error_message
        change.updated_at = datetime.utcnow()
        await self.session.flush()
        return change

    async def update_batch_status(
        self,
        batch_id: str,
        status: str,
        *,
        summary: str | None = None,
        error_message: object = _UNSET,
    ) -> Optional[SettingReviewBatch]:
        batch = await self.get_review_batch(batch_id)
        if batch is None:
            return None
        batch.status = status
        if summary is not None:
            batch.summary = summary
        if error_message is not _UNSET:
            batch.error_message = error_message
        batch.updated_at = datetime.utcnow()
        await self.session.flush()
        return batch
