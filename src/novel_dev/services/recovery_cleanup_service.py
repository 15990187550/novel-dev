from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import GenerationJob, NovelState
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.services.flow_control_service import clear_cancel_request
from novel_dev.services.log_service import log_service


CHAPTER_AUTO_RUN_JOB = "chapter_auto_run"
ACTIVE_JOB_STATUSES = {"queued", "running"}
RECOVERED_LOCK_RESULT = {
    "stopped_reason": "failed",
    "recovered": True,
    "error": "Recovered stale auto_run_lock after process interruption",
}


class RecoveryCleanupOptions(BaseModel):
    stale_running_minutes: int = Field(default=120, ge=1)
    stale_queued_minutes: int = Field(default=30, ge=1)
    stale_flow_stop_hours: int = Field(default=24, ge=1)
    dry_run: bool = False


class RecoveryCleanupResult(BaseModel):
    cleaned_jobs: list[dict[str, Any]] = Field(default_factory=list)
    released_locks: list[dict[str, Any]] = Field(default_factory=list)
    cleared_flow_stops: list[dict[str, Any]] = Field(default_factory=list)
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
        pending_cancel_clears: set[str] = set()
        planned_recovered_job_ids: set[str] = set()
        now = datetime.utcnow()

        await self._clean_stale_jobs(options, result, pending_logs, planned_recovered_job_ids, now)
        await self._release_stale_locks(options, result, pending_logs, planned_recovered_job_ids)
        await self._clear_expired_flow_stops(
            options,
            result,
            pending_logs,
            pending_cancel_clears,
            planned_recovered_job_ids,
            now,
        )

        if not options.dry_run:
            await self.session.commit()
            for novel_id in pending_cancel_clears:
                clear_cancel_request(novel_id)
            for entry in pending_logs:
                self._emit_log(entry)
            await log_service.flush_pending()

        return result

    async def _clean_stale_jobs(
        self,
        options: RecoveryCleanupOptions,
        result: RecoveryCleanupResult,
        pending_logs: list[dict[str, Any]],
        planned_recovered_job_ids: set[str],
        now: datetime,
    ) -> None:
        stale_jobs = await self.job_repo.list_stale_active(
            stale_queued_before=now - timedelta(minutes=options.stale_queued_minutes),
            stale_running_before=now - timedelta(minutes=options.stale_running_minutes),
        )
        for job in stale_jobs:
            reason = f"Recovered stale {job.status} job after process interruption"
            cleaned_job = {
                "job_id": job.id,
                "novel_id": job.novel_id,
                "job_type": job.job_type,
                "previous_status": job.status,
                "reason": reason,
            }
            try:
                if not options.dry_run:
                    await self.job_repo.mark_recovered_failed(job.id, reason)

                result.cleaned_jobs.append(cleaned_job)
                planned_recovered_job_ids.add(job.id)
                if not options.dry_run:
                    pending_logs.append(
                        self._log_entry(
                            job.novel_id,
                            "cleaned_job",
                            f"Recovered stale generation job {job.id}",
                            {"job_id": job.id, "job_type": job.job_type, "status": "failed"},
                        )
                    )
            except Exception as exc:
                result.skipped.append(
                    {
                        "job_id": job.id,
                        "novel_id": job.novel_id,
                        "reason": "cleanup_error",
                        "error": str(exc),
                    }
                )

    async def _release_stale_locks(
        self,
        options: RecoveryCleanupOptions,
        result: RecoveryCleanupResult,
        pending_logs: list[dict[str, Any]],
        planned_recovered_job_ids: set[str],
    ) -> None:
        states = await self._states_with_checkpoint_key("auto_run_lock")
        for state in states:
            try:
                checkpoint = dict(state.checkpoint_data or {})
                lock = checkpoint.get("auto_run_lock")
                if not isinstance(lock, dict) or not lock.get("active"):
                    continue

                has_active_job = await self._has_active_generation_job(
                    state.novel_id,
                    job_type=CHAPTER_AUTO_RUN_JOB,
                    exclude_job_ids=planned_recovered_job_ids,
                )
                if has_active_job:
                    result.skipped.append({"novel_id": state.novel_id, "reason": "fresh_active_job"})
                    continue

                checkpoint.pop("auto_run_lock", None)
                checkpoint.setdefault("auto_run_last_result", dict(RECOVERED_LOCK_RESULT))
                released_lock = {
                    "novel_id": state.novel_id,
                    "chapter_id": state.current_chapter_id,
                    "volume_id": state.current_volume_id,
                    "reason": "Recovered stale auto_run_lock after process interruption",
                }
                if not options.dry_run:
                    await self._save_state_checkpoint(state, checkpoint)

                result.released_locks.append(released_lock)
                if not options.dry_run:
                    pending_logs.append(
                        self._log_entry(
                            state.novel_id,
                            "released_lock",
                            "Released stale auto-run lock",
                            {"lock": lock},
                        )
                    )
            except Exception as exc:
                result.skipped.append(
                    {
                        "novel_id": state.novel_id,
                        "reason": "cleanup_error",
                        "error": str(exc),
                    }
                )

    async def _clear_expired_flow_stops(
        self,
        options: RecoveryCleanupOptions,
        result: RecoveryCleanupResult,
        pending_logs: list[dict[str, Any]],
        pending_cancel_clears: set[str],
        planned_recovered_job_ids: set[str],
        now: datetime,
    ) -> None:
        expires_before = now - timedelta(hours=options.stale_flow_stop_hours)
        states = await self._states_with_checkpoint_key("flow_control")
        for state in states:
            try:
                checkpoint = dict(state.checkpoint_data or {})
                flow_control = checkpoint.get("flow_control")
                if not isinstance(flow_control, dict) or not flow_control.get("cancel_requested"):
                    continue

                requested_at = self._parse_requested_at(flow_control.get("requested_at"))
                if requested_at is not None and requested_at >= expires_before:
                    continue

                if requested_at is None and await self._has_active_generation_job(
                    state.novel_id,
                    exclude_job_ids=planned_recovered_job_ids,
                ):
                    result.skipped.append({"novel_id": state.novel_id, "reason": "active_job_with_unvalidated_flow_stop"})
                    continue

                cleared_flow_stop = {
                    "novel_id": state.novel_id,
                    "reason": "Cleared expired flow stop marker",
                }
                if not options.dry_run:
                    checkpoint.pop("flow_control", None)
                    await self._save_state_checkpoint(state, checkpoint)

                result.cleared_flow_stops.append(cleared_flow_stop)
                if not options.dry_run:
                    pending_cancel_clears.add(state.novel_id)
                    pending_logs.append(
                        self._log_entry(
                            state.novel_id,
                            "cleared_flow_stop",
                            "Cleared stale flow stop marker",
                            {"flow_control": flow_control},
                        )
                    )
            except Exception as exc:
                result.skipped.append(
                    {
                        "novel_id": state.novel_id,
                        "reason": "cleanup_error",
                        "error": str(exc),
                    }
                )

    async def _states_with_checkpoint_key(self, key: str) -> list[NovelState]:
        result = await self.session.execute(
            select(NovelState).where(NovelState.checkpoint_data[key].is_not(None))
        )
        return list(result.scalars().all())

    async def _has_active_generation_job(
        self,
        novel_id: str,
        *,
        job_type: str | None = None,
        exclude_job_ids: set[str] | None = None,
    ) -> bool:
        conditions = [
            GenerationJob.novel_id == novel_id,
            GenerationJob.status.in_(ACTIVE_JOB_STATUSES),
        ]
        if job_type is not None:
            conditions.append(GenerationJob.job_type == job_type)
        if exclude_job_ids:
            conditions.append(~GenerationJob.id.in_(exclude_job_ids))

        result = await self.session.execute(select(GenerationJob.id).where(*conditions).limit(1))
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
