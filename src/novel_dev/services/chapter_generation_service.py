from datetime import datetime
import uuid

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents._log_helpers import log_agent_detail
from novel_dev.agents.context_agent import ContextAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.llm import llm_factory
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.schemas.context import ChapterContext
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.services.flow_control_service import FlowCancelledError, FlowControlService
from novel_dev.services.log_service import log_service
from novel_dev.services.volume_plan_guard_service import evaluate_volume_plan_readiness


STOP_REASONS = {
    "max_chapters_reached",
    "volume_completed",
    "novel_completed",
    "flow_cancelled",
    "quality_blocked",
    "volume_plan_not_ready",
    "failed",
}

CHAPTER_SCOPED_CHECKPOINT_KEYS = {
    "chapter_context",
    "context_debug_snapshot",
    "drafting_progress",
    "relay_history",
    "draft_metadata",
    "draft_rewrite_plan",
    "beat_scores",
    "critique_feedback",
    "per_dim_issues",
    "editor_feedback",
    "fast_review_feedback",
}


class AutoRunChaptersRequest(BaseModel):
    max_chapters: int = Field(default=1, ge=1)
    stop_at_volume_end: bool = True


class AutoRunChaptersResult(BaseModel):
    novel_id: str
    current_phase: str
    current_chapter_id: str | None = None
    completed_chapters: list[str] = Field(default_factory=list)
    stopped_reason: str
    failed_phase: str | None = None
    failed_chapter_id: str | None = None
    error: str | None = None


class AutoRunConflictError(RuntimeError):
    pass


class AutoRunFailedError(RuntimeError):
    def __init__(self, result: AutoRunChaptersResult):
        self.result = result
        super().__init__(result.error or "Auto chapter generation failed")


class QualityGateBlockedError(RuntimeError):
    def __init__(self, chapter_id: str, reasons: dict | None = None):
        self.chapter_id = chapter_id
        self.reasons = reasons or {}
        super().__init__("Chapter quality gate blocked auto-run")


class ChapterGenerationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.director = NovelDirector(session)
        self.chapter_repo = ChapterRepository(session)
        self.flow_control = FlowControlService(session)

    async def auto_run(
        self,
        novel_id: str,
        *,
        max_chapters: int = 1,
        stop_at_volume_end: bool = True,
    ) -> AutoRunChaptersResult:
        completed: list[str] = []
        stopped_reason = "max_chapters_reached"
        token = await self._acquire_lock(novel_id, max_chapters, stop_at_volume_end)

        try:
            while len(completed) < max_chapters:
                await self.flow_control.raise_if_cancelled(novel_id)
                state = await self.director.resume(novel_id)
                if not state:
                    raise ValueError(f"Novel state not found for {novel_id}")
                if state.current_phase == Phase.VOLUME_PLANNING.value:
                    stopped_reason = "volume_completed"
                    break
                if state.current_phase == Phase.COMPLETED.value and not state.current_chapter_id:
                    stopped_reason = "novel_completed"
                    break
                readiness = evaluate_volume_plan_readiness(state.checkpoint_data)
                if (
                    state.current_phase
                    in {
                        Phase.CONTEXT_PREPARATION.value,
                        Phase.DRAFTING.value,
                        Phase.REVIEWING.value,
                        Phase.EDITING.value,
                        Phase.FAST_REVIEWING.value,
                        Phase.LIBRARIAN.value,
                    }
                    and not readiness.accepted
                ):
                    result = AutoRunChaptersResult(
                        novel_id=novel_id,
                        current_phase=state.current_phase,
                        current_chapter_id=state.current_chapter_id,
                        completed_chapters=completed,
                        stopped_reason="volume_plan_not_ready",
                        error=readiness.message,
                    )
                    await self._release_lock(novel_id, token, result)
                    return result

                archived_id = await self._run_current_chapter(novel_id)
                completed.append(archived_id)
                await self.session.commit()

                state = await self.director.resume(novel_id)
                if state.current_phase == Phase.VOLUME_PLANNING.value:
                    stopped_reason = "volume_completed"
                    if stop_at_volume_end:
                        break
                else:
                    stopped_reason = "max_chapters_reached"
        except FlowCancelledError:
            state = await self.director.resume(novel_id)
            result = AutoRunChaptersResult(
                novel_id=novel_id,
                current_phase=state.current_phase if state else "",
                current_chapter_id=state.current_chapter_id if state else None,
                completed_chapters=completed,
                stopped_reason="flow_cancelled",
            )
            await self._release_lock(novel_id, token, result)
            return result
        except QualityGateBlockedError as exc:
            state = await self.director.resume(novel_id)
            result = AutoRunChaptersResult(
                novel_id=novel_id,
                current_phase=state.current_phase if state else "",
                current_chapter_id=state.current_chapter_id if state else exc.chapter_id,
                completed_chapters=completed,
                stopped_reason="quality_blocked",
                failed_phase=state.current_phase if state else None,
                failed_chapter_id=exc.chapter_id,
                error=str(exc),
            )
            await self._release_lock(novel_id, token, result)
            return result
        except Exception as exc:
            error_message = str(exc)
            await self.session.rollback()
            log_service.add_log(novel_id, "ChapterGenerationService", f"自动写章失败: {error_message}", level="error")
            state = await self.director.resume(novel_id)
            if state is not None:
                state = await self._persist_failure_diagnostics(novel_id, state, exc)
            result = AutoRunChaptersResult(
                novel_id=novel_id,
                current_phase=state.current_phase if state else "",
                current_chapter_id=state.current_chapter_id if state else None,
                completed_chapters=completed,
                stopped_reason="failed",
                failed_phase=getattr(exc, "failed_phase", None) or (state.current_phase if state else None),
                failed_chapter_id=state.current_chapter_id if state else None,
                error=error_message,
            )
            await self._release_lock(novel_id, token, result)
            raise AutoRunFailedError(result) from exc

        state = await self.director.resume(novel_id)
        result = AutoRunChaptersResult(
            novel_id=novel_id,
            current_phase=state.current_phase if state else "",
            current_chapter_id=state.current_chapter_id if state else None,
            completed_chapters=completed,
            stopped_reason=stopped_reason,
        )
        await self._release_lock(novel_id, token, result)
        return result

    async def _acquire_lock(self, novel_id: str, max_chapters: int, stop_at_volume_end: bool) -> str:
        state = await self.director.resume(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")
        checkpoint = dict(state.checkpoint_data or {})
        lock = checkpoint.get("auto_run_lock") or {}
        if lock.get("active"):
            raise AutoRunConflictError("Auto chapter generation is already running")

        token = uuid.uuid4().hex
        checkpoint["auto_run_lock"] = {
            "active": True,
            "token": token,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "max_chapters": max_chapters,
            "stop_at_volume_end": stop_at_volume_end,
        }
        await self.director.save_checkpoint(
            novel_id,
            Phase(state.current_phase),
            checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )
        await self.session.commit()
        return token

    async def _release_lock(
        self,
        novel_id: str,
        token: str,
        result: AutoRunChaptersResult | None = None,
    ) -> None:
        state = await self.director.resume(novel_id)
        if not state:
            return
        checkpoint = dict(state.checkpoint_data or {})
        lock = checkpoint.get("auto_run_lock") or {}
        if lock.get("token") == token:
            checkpoint.pop("auto_run_lock", None)
        if result is not None:
            checkpoint["auto_run_last_result"] = result.model_dump()
        await self.director.save_checkpoint(
            novel_id,
            Phase(state.current_phase),
            checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )
        await self.session.commit()

    async def _persist_failure_diagnostics(self, novel_id: str, state, exc: Exception):
        guard_evidence = getattr(exc, "chapter_structure_guard", None)
        writer_failures = getattr(exc, "writer_guard_failures", None)
        if not guard_evidence and not writer_failures:
            return state

        checkpoint = dict(state.checkpoint_data or {})
        if writer_failures:
            checkpoint["writer_guard_failures"] = list(writer_failures)
        if guard_evidence:
            checkpoint["chapter_structure_guard"] = dict(guard_evidence)

        phase_value = getattr(exc, "failed_phase", None) or state.current_phase
        try:
            phase = Phase(phase_value)
        except ValueError:
            phase = Phase(state.current_phase)
        return await self.director.save_checkpoint(
            novel_id,
            phase,
            checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )

    async def _run_current_chapter(self, novel_id: str) -> str:
        state = await self.director.resume(novel_id)
        if not state or not state.current_chapter_id:
            raise ValueError("No current chapter set")
        state = await self._sync_current_chapter_checkpoint(state)
        start_chapter_id = state.current_chapter_id
        await self._ensure_current_chapter(state)

        for _ in range(20):
            await self.flow_control.raise_if_cancelled(novel_id)
            state = await self.director.resume(novel_id)
            if not state:
                raise ValueError(f"Novel state not found for {novel_id}")

            if state.current_phase == Phase.CONTEXT_PREPARATION.value:
                embedding_service = self._embedding_service()
                await ContextAgent(self.session, embedding_service).assemble(novel_id, start_chapter_id)
            elif state.current_phase == Phase.DRAFTING.value:
                checkpoint = dict(state.checkpoint_data or {})
                context_data = checkpoint.get("chapter_context")
                if not context_data:
                    raise ValueError("chapter_context missing in checkpoint_data")
                context = ChapterContext.model_validate(context_data)
                embedding_service = self._embedding_service()
                await WriterAgent(self.session, embedding_service).write(novel_id, context, start_chapter_id)
            elif state.current_phase in {
                Phase.REVIEWING.value,
                Phase.EDITING.value,
                Phase.FAST_REVIEWING.value,
                Phase.LIBRARIAN.value,
                Phase.COMPLETED.value,
            }:
                await self.director.advance(novel_id)
            elif state.current_phase == Phase.VOLUME_PLANNING.value:
                return start_chapter_id
            else:
                raise ValueError(f"Cannot auto-run from phase {state.current_phase}")

            updated = await self.director.resume(novel_id)
            await self._raise_if_quality_blocked(start_chapter_id)
            if updated and updated.current_chapter_id != start_chapter_id:
                return start_chapter_id
            if updated and updated.current_phase == Phase.VOLUME_PLANNING.value:
                return start_chapter_id

        raise RuntimeError("Auto chapter generation exceeded phase iteration limit")

    async def _raise_if_quality_blocked(self, chapter_id: str) -> None:
        chapter = await self.chapter_repo.get_by_id(chapter_id)
        if chapter and getattr(chapter, "quality_status", "unchecked") == "block":
            raise QualityGateBlockedError(chapter_id, chapter.quality_reasons)

    async def _sync_current_chapter_checkpoint(self, state):
        checkpoint = dict(state.checkpoint_data or {})
        current_chapter_id = state.current_chapter_id
        if not current_chapter_id:
            return state

        current_plan = checkpoint.get("current_chapter_plan")
        if isinstance(current_plan, dict) and current_plan.get("chapter_id") == current_chapter_id:
            return state

        volume_plan = checkpoint.get("current_volume_plan") or {}
        chapters = volume_plan.get("chapters") or []
        matching_plan = next(
            (
                chapter
                for chapter in chapters
                if isinstance(chapter, dict) and chapter.get("chapter_id") == current_chapter_id
            ),
            None,
        )
        if not matching_plan:
            raise ValueError(f"current_chapter_plan does not match current_chapter_id {current_chapter_id}")

        previous_plan_id = current_plan.get("chapter_id") if isinstance(current_plan, dict) else None
        checkpoint["current_chapter_plan"] = matching_plan
        removed_keys = sorted(key for key in CHAPTER_SCOPED_CHECKPOINT_KEYS if key in checkpoint)
        for key in removed_keys:
            checkpoint.pop(key, None)

        next_phase = Phase.CONTEXT_PREPARATION
        log_agent_detail(
            state.novel_id,
            "ChapterGenerationService",
            f"章节状态已校正：{current_chapter_id}",
            node="chapter_state_sync",
            task="auto_run",
            status="succeeded",
            metadata={
                "current_chapter_id": current_chapter_id,
                "previous_plan_id": previous_plan_id,
                "next_plan_title": matching_plan.get("title"),
                "previous_phase": state.current_phase,
                "next_phase": next_phase.value,
                "removed_checkpoint_keys": removed_keys,
            },
        )
        return await self.director.save_checkpoint(
            state.novel_id,
            next_phase,
            checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=current_chapter_id,
        )

    async def _ensure_current_chapter(self, state) -> None:
        checkpoint = dict(state.checkpoint_data or {})
        chapter_plan = checkpoint.get("current_chapter_plan")
        if not chapter_plan:
            return
        await self.chapter_repo.ensure_from_plan(
            state.novel_id,
            state.current_volume_id,
            chapter_plan,
        )

    def _embedding_service(self):
        embedder = llm_factory.get_embedder()
        if embedder is None:
            return None
        return EmbeddingService(self.session, embedder)
