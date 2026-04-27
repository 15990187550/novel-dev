import asyncio

from novel_dev.db.engine import async_session_maker
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.services.chapter_generation_service import AutoRunFailedError, ChapterGenerationService
from novel_dev.services.chapter_rewrite_service import ChapterRewriteService
from novel_dev.services.log_service import log_service


CHAPTER_AUTO_RUN_JOB = "chapter_auto_run"
CHAPTER_REWRITE_JOB = "chapter_rewrite"


def schedule_generation_job(job_id: str) -> None:
    asyncio.create_task(run_generation_job(job_id))


async def run_generation_job(job_id: str) -> None:
    async with async_session_maker() as session:
        repo = GenerationJobRepository(session)
        job = await repo.get_by_id(job_id)
        if not job:
            return

        await repo.mark_running(job_id)
        await repo.touch_heartbeat(job_id)
        await session.commit()

        if job.job_type not in {CHAPTER_AUTO_RUN_JOB, CHAPTER_REWRITE_JOB}:
            await repo.mark_failed(job_id, {}, f"Unsupported generation job type: {job.job_type}")
            await session.commit()
            return

        request = dict(job.request_payload or {})
        try:
            if job.job_type == CHAPTER_AUTO_RUN_JOB:
                service = ChapterGenerationService(session)
                await repo.touch_heartbeat(job_id)
                await session.commit()
                result = await service.auto_run(
                    job.novel_id,
                    max_chapters=request.get("max_chapters", 1),
                    stop_at_volume_end=request.get("stop_at_volume_end", True),
                )
            else:
                chapter_id = request.get("chapter_id")
                if not chapter_id:
                    raise ValueError("chapter_id missing for chapter rewrite job")
                result = await ChapterRewriteService(session).rewrite(job.novel_id, chapter_id)
        except AutoRunFailedError as exc:
            await repo.touch_heartbeat(job_id)
            await repo.mark_failed(job_id, exc.result.model_dump(), exc.result.error or str(exc))
            await session.commit()
            return
        except Exception as exc:
            log_service.add_log(job.novel_id, "GenerationJobService", f"后台生成任务失败: {exc}", level="error")
            await repo.touch_heartbeat(job_id)
            await repo.mark_failed(job_id, {}, str(exc))
            await session.commit()
            return

        await repo.touch_heartbeat(job_id)
        if getattr(result, "stopped_reason", None) == "flow_cancelled":
            await repo.mark_cancelled(job_id, result.model_dump())
        else:
            await repo.mark_succeeded(job_id, result.model_dump())
        await session.commit()
