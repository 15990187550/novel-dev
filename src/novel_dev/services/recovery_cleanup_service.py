from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import GenerationJob, NovelState
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.services.log_service import log_service


CHAPTER_AUTO_RUN_JOB = "chapter_auto_run"
ACTIVE_JOB_STATUSES = {"queued", "running"}


class RecoveryCleanupOptions(BaseModel):
    stale_running_minutes: int = Field(default=120, ge=1)
    stale_queued_minutes: int = Field(default=30, ge=1)
    stale_flow_stop_hours: int = Field(default=24, ge=1)
    dry_run: bool = False


class RecoveryCleanupResult(BaseModel):
    cleaned_jobs: list[str] = Field(default_factory=list)
    released_locks: list[str] = Field(default_factory=list)
    cleared_flow_stops: list[str] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)


class RecoveryCleanupService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.job_repo = GenerationJobRepository(session)
        self.state_repo = NovelStateRepository(session)

    async def run_cleanup(self, options: RecoveryCleanupOptions | None = None) -> RecoveryCleanupResult:
        options = options or RecoveryCleanupOptions()
        result = RecoveryCleanupResult()
        pending_logs: list[dict[str, Any]] = []
        now = datetime.utcnow()

        await self._clean_stale_jobs(options, result, pending_logs, now)
        await self._release_stale_locks(options, result, pending_logs)
        await self._clear_expired_flow_stops(options, result, pending_logs, now)

        if not options.dry_run:
            await self.session.commit()
            for entry in pending_logs:
                self._emit_log(entry)
            await log_service.flush_pending()

        return result

    async def _clean_stale_jobs(
        self,
        options: RecoveryCleanupOptions,
        result: RecoveryCleanupResult,
        pending_logs: list[dict[str, Any]],
        now: datetime,
    ) -> None:
        stale_jobs = await self.job_repo.list_stale_active(
            stale_queued_before=now - timedelta(minutes=options.stale_queued_minutes),
            stale_running_before=now - timedelta(minutes=options.stale_running_minutes),
        )
        for job in stale_jobs:
            result.cleaned_jobs.append(job.id)
            if options.dry_run:
                continue

            await self.job_repo.mark_recovered_failed(
                job.id,
                f"Recovered by cleanup after stale {job.status} generation job",
            )
            pending_logs.append(
                self._log_entry(
                    job.novel_id,
                    "cleaned_job",
                    f"Recovered stale generation job {job.id}",
                    {"job_id": job.id, "job_type": job.job_type, "status": "failed"},
                )
            )

    async def _release_stale_locks(
        self,
        options: RecoveryCleanupOptions,
        result: RecoveryCleanupResult,
        pending_logs: list[dict[str, Any]],
    ) -> None:
        states = await self._states_with_checkpoint_key("auto_run_lock")
        for state in states:
            checkpoint = dict(state.checkpoint_data or {})
            lock = checkpoint.get("auto_run_lock")
            if not isinstance(lock, dict) or not lock.get("active"):
                continue

            active_job = await self.job_repo.get_active(state.novel_id, CHAPTER_AUTO_RUN_JOB)
            if active_job is not None:
                result.skipped.append({"novel_id": state.novel_id, "reason": "fresh_active_job"})
                continue

            checkpoint.pop("auto_run_lock", None)
            checkpoint.setdefault(
                "auto_run_last_result",
                {
                    "novel_id": state.novel_id,
                    "current_phase": state.current_phase,
                    "current_chapter_id": state.current_chapter_id,
                    "completed_chapters": [],
                    "stopped_reason": "recovered",
                },
            )
            result.released_locks.append(state.novel_id)
            if options.dry_run:
                continue

            await self._save_state_checkpoint(state, checkpoint)
            pending_logs.append(
                self._log_entry(
                    state.novel_id,
                    "released_lock",
                    "Released stale auto-run lock",
                    {"lock": lock},
                )
            )

    async def _clear_expired_flow_stops(
        self,
        options: RecoveryCleanupOptions,
        result: RecoveryCleanupResult,
        pending_logs: list[dict[str, Any]],
        now: datetime,
    ) -> None:
        expires_before = now - timedelta(hours=options.stale_flow_stop_hours)
        states = await self._states_with_checkpoint_key("flow_control")
        for state in states:
            checkpoint = dict(state.checkpoint_data or {})
            flow_control = checkpoint.get("flow_control")
            if not isinstance(flow_control, dict) or not flow_control.get("cancel_requested"):
                continue

            requested_at = self._parse_requested_at(flow_control.get("requested_at"))
            if requested_at is not None and requested_at >= expires_before:
                continue

            if requested_at is None and await self._has_active_generation_job(state.novel_id):
                result.skipped.append({"novel_id": state.novel_id, "reason": "active_job_with_unvalidated_flow_stop"})
                continue

            result.cleared_flow_stops.append(state.novel_id)
            if options.dry_run:
                continue

            checkpoint.pop("flow_control", None)
            await self._save_state_checkpoint(state, checkpoint)
            pending_logs.append(
                self._log_entry(
                    state.novel_id,
                    "cleared_flow_stop",
                    "Cleared stale flow stop marker",
                    {"flow_control": flow_control},
                )
            )

    async def _states_with_checkpoint_key(self, key: str) -> list[NovelState]:
        result = await self.session.execute(
            select(NovelState).where(NovelState.checkpoint_data[key].is_not(None))
        )
        return list(result.scalars().all())

    async def _has_active_generation_job(self, novel_id: str) -> bool:
        result = await self.session.execute(
            select(GenerationJob.id)
            .where(
                GenerationJob.novel_id == novel_id,
                GenerationJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _save_state_checkpoint(self, state: NovelState, checkpoint: dict[str, Any]) -> None:
        await self.state_repo.save_checkpoint(
            state.novel_id,
            current_phase=state.current_phase,
            checkpoint_data=checkpoint,
            current_volume_id=state.current_volume_id,
            current_chapter_id=state.current_chapter_id,
        )

    def _log_entry(
        self,
        novel_id: str,
        status: str,
        message: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "novel_id": novel_id,
            "status": status,
            "message": message,
            "metadata": metadata,
        }

    def _emit_log(self, entry: dict[str, Any]) -> None:
        log_service.add_log(
            entry["novel_id"],
            "RecoveryCleanup",
            entry["message"],
            event="recovery.cleanup",
            status=entry["status"],
            node="recovery",
            task="cleanup",
            metadata=entry["metadata"],
        )

    def _parse_requested_at(self, value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            normalized = value.removesuffix("Z")
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
