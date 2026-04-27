import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import GenerationJob


ACTIVE_STATUSES = {"queued", "running"}


class GenerationJobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        novel_id: str,
        job_type: str,
        request_payload: dict,
        job_id: Optional[str] = None,
    ) -> GenerationJob:
        job = GenerationJob(
            id=job_id or f"job_{uuid.uuid4().hex[:12]}",
            novel_id=novel_id,
            job_type=job_type,
            status="queued",
            request_payload=dict(request_payload or {}),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_by_id(self, job_id: str) -> Optional[GenerationJob]:
        result = await self.session.execute(
            select(GenerationJob)
            .where(GenerationJob.id == job_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_active(self, novel_id: str, job_type: str) -> Optional[GenerationJob]:
        result = await self.session.execute(
            select(GenerationJob)
            .where(
                GenerationJob.novel_id == novel_id,
                GenerationJob.job_type == job_type,
                GenerationJob.status.in_(ACTIVE_STATUSES),
            )
            .order_by(GenerationJob.created_at.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def mark_running(self, job_id: str) -> None:
        job = await self.get_by_id(job_id)
        if not job:
            return
        now = datetime.utcnow()
        job.status = "running"
        job.started_at = now
        job.updated_at = now
        await self.session.flush()

    async def mark_succeeded(self, job_id: str, result_payload: dict) -> None:
        await self._mark_terminal(job_id, "succeeded", result_payload=result_payload)

    async def mark_failed(self, job_id: str, result_payload: dict, error_message: str) -> None:
        await self._mark_terminal(
            job_id,
            "failed",
            result_payload=result_payload,
            error_message=error_message,
        )

    async def mark_cancelled(self, job_id: str, result_payload: dict) -> None:
        await self._mark_terminal(job_id, "cancelled", result_payload=result_payload)

    async def _mark_terminal(
        self,
        job_id: str,
        status: str,
        *,
        result_payload: Optional[dict] = None,
        error_message: Optional[str] = None,
    ) -> None:
        job = await self.get_by_id(job_id)
        if not job:
            return
        now = datetime.utcnow()
        job.status = status
        job.result_payload = result_payload
        job.error_message = error_message
        job.finished_at = now
        job.updated_at = now
        await self.session.flush()
