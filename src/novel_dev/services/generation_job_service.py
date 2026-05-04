import asyncio
from contextlib import suppress

from novel_dev.db.engine import async_session_maker
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.services.chapter_generation_service import AutoRunFailedError, ChapterGenerationService
from novel_dev.services.chapter_rewrite_service import ChapterRewriteFailedError, ChapterRewriteService
from novel_dev.services.log_service import log_service
from novel_dev.services.setting_consolidation_service import SettingConsolidationService


CHAPTER_AUTO_RUN_JOB = "chapter_auto_run"
CHAPTER_REWRITE_JOB = "chapter_rewrite"
SETTING_CONSOLIDATION_JOB = "setting_consolidation"
HEARTBEAT_INTERVAL_SECONDS = 30


def schedule_generation_job(job_id: str) -> None:
    asyncio.create_task(run_generation_job(job_id))


async def run_generation_job(job_id: str) -> None:
    async with async_session_maker() as session:
        repo = GenerationJobRepository(session)
        job = await repo.get_by_id(job_id)
        if not job:
            return
        novel_id = job.novel_id
        job_type = job.job_type

        await repo.mark_running(job_id)
        await repo.touch_heartbeat(job_id)
        await session.commit()

        if job_type not in {CHAPTER_AUTO_RUN_JOB, CHAPTER_REWRITE_JOB, SETTING_CONSOLIDATION_JOB}:
            await repo.mark_failed(job_id, {}, f"Unsupported generation job type: {job_type}")
            await session.commit()
            return

        request = dict(job.request_payload or {})
        heartbeat_task = (
            asyncio.create_task(_heartbeat_active_job(job_id, novel_id))
            if _supports_periodic_heartbeat(session)
            else None
        )
        try:
            if job_type == CHAPTER_AUTO_RUN_JOB:
                service = ChapterGenerationService(session)
                await repo.touch_heartbeat(job_id)
                await session.commit()
                result = await service.auto_run(
                    novel_id,
                    max_chapters=request.get("max_chapters", 1),
                    stop_at_volume_end=request.get("stop_at_volume_end", True),
                )
            elif job_type == CHAPTER_REWRITE_JOB:
                chapter_id = request.get("chapter_id")
                if not chapter_id:
                    raise ValueError("chapter_id missing for chapter rewrite job")
                result = await ChapterRewriteService(session).rewrite(
                    novel_id,
                    chapter_id,
                    resume_from_stage=request.get("resume_from_stage"),
                    resume_checkpoint=request.get("resume_checkpoint") or request.get("rewrite_checkpoint"),
                    job_id=job.id,
                    job_repo=repo,
                )
            else:
                batch = await SettingConsolidationService(session).run_consolidation(
                    novel_id=novel_id,
                    selected_pending_ids=request.get("selected_pending_ids", []),
                    job_id=job.id,
                    input_snapshot=request.get("input_snapshot"),
                )
                result = {
                    "batch_id": batch.id,
                    "status": "ready_for_review",
                    "summary": batch.summary,
                }
        except AutoRunFailedError as exc:
            await _cancel_heartbeat_task(heartbeat_task)
            await repo.touch_heartbeat(job_id)
            await repo.mark_failed(job_id, exc.result.model_dump(), exc.result.error or str(exc))
            await session.commit()
            return
        except ChapterRewriteFailedError as exc:
            await _cancel_heartbeat_task(heartbeat_task)
            await repo.touch_heartbeat(job_id)
            await repo.mark_failed(job_id, exc.result.model_dump(), exc.result.error or str(exc))
            await session.commit()
            return
        except Exception as exc:
            await _cancel_heartbeat_task(heartbeat_task)
            error_message = str(exc)
            await session.rollback()
            log_service.add_log(novel_id, "GenerationJobService", f"后台生成任务失败: {error_message}", level="error")
            await repo.touch_heartbeat(job_id)
            await repo.mark_failed(job_id, {}, error_message)
            await session.commit()
            return
        else:
            await _cancel_heartbeat_task(heartbeat_task)

        await repo.touch_heartbeat(job_id)
        if isinstance(result, dict):
            await repo.mark_succeeded(job_id, result)
        elif getattr(result, "stopped_reason", None) == "flow_cancelled":
            await repo.mark_cancelled(job_id, result.model_dump())
        else:
            await repo.mark_succeeded(job_id, result.model_dump())
        await session.commit()


def _supports_periodic_heartbeat(session) -> bool:
    bind = session.get_bind()
    return getattr(bind.dialect, "name", "") != "sqlite"


async def _cancel_heartbeat_task(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _heartbeat_active_job(job_id: str, novel_id: str) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        try:
            async with async_session_maker() as session:
                repo = GenerationJobRepository(session)
                job = await repo.get_by_id(job_id)
                if not job or job.status not in {"queued", "running"}:
                    return
                await repo.touch_heartbeat(job_id)
                await session.commit()
        except Exception as exc:
            log_service.add_log(
                novel_id,
                "GenerationJobService",
                f"后台生成任务心跳失败: {exc}",
                level="warning",
            )
