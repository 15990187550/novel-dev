from datetime import datetime
import re
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
from novel_dev.services.global_consistency_audit_service import GlobalConsistencyAuditResult, GlobalConsistencyAuditService
from novel_dev.services.chapter_run_trace_service import ChapterRunTraceService
from novel_dev.services.chapter_run_state_service import CHAPTER_RUN_STAGES, ChapterRunStateService
from novel_dev.services.log_service import log_service
from novel_dev.services.quality_gate_service import QualityGateResult, QualityGateService
from novel_dev.services.quality_issue_service import QualityIssueService
from novel_dev.services.volume_plan_guard_service import evaluate_volume_plan_readiness
from novel_dev.services.world_state_review_service import WorldStateReviewRequiredError
from novel_dev.schemas.quality import ChapterRunTrace, QualityIssue


STOP_REASONS = {
    "max_chapters_reached",
    "volume_completed",
    "novel_completed",
    "flow_cancelled",
    "quality_blocked",
    "waiting_world_state_review",
    "global_consistency_review_required",
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
    "chapter_run",
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
    can_resume: bool = False
    resume_stage: str | None = None
    chapter_run: dict = Field(default_factory=dict)


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

    @staticmethod
    def _chapter_run_payload(state) -> dict:
        if not state:
            return {}
        checkpoint = dict(state.checkpoint_data or {})
        return ChapterRunStateService.get(checkpoint)

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
                        can_resume=bool(state.current_chapter_id),
                        resume_stage=ChapterRunStateService.stage_from_phase(state.current_phase),
                        chapter_run=self._chapter_run_payload(state),
                    )
                    await self._release_lock(novel_id, token, result)
                    return result

                archived_id = await self._run_current_chapter(novel_id)
                completed.append(archived_id)
                await self.session.commit()
                audit_result = await self._maybe_run_periodic_global_consistency_audit(novel_id, len(completed))
                if audit_result and audit_result.status == "confirm_required":
                    stopped_reason = "global_consistency_review_required"
                    break

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
                can_resume=bool(state and state.current_chapter_id),
                resume_stage=ChapterRunStateService.stage_from_phase(state.current_phase if state else None),
                chapter_run=self._chapter_run_payload(state),
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
                can_resume=True,
                resume_stage=ChapterRunStateService.stage_from_phase(state.current_phase if state else None),
                chapter_run=self._chapter_run_payload(state),
            )
            if state is not None:
                checkpoint = dict(state.checkpoint_data or {})
                quality_issues = self._quality_issues_for_block(checkpoint, exc.reasons)
                checkpoint["quality_issue_summary"] = QualityIssueService.summarize(quality_issues)
                trace = self._trace_from_checkpoint(checkpoint, novel_id, exc.chapter_id, token, state.current_phase)
                ChapterRunTraceService.mark_blocked(
                    trace,
                    state.current_phase,
                    quality_issues,
                    reason="quality_blocked",
                )
                checkpoint["chapter_run_trace"] = trace.model_dump()
                await self.director.save_checkpoint(
                    novel_id,
                    Phase(state.current_phase),
                    checkpoint,
                    volume_id=state.current_volume_id,
                    chapter_id=state.current_chapter_id,
                )
                await self.session.commit()
            await self._release_lock(novel_id, token, result)
            return result
        except WorldStateReviewRequiredError as exc:
            state = await self.director.resume(novel_id)
            result = AutoRunChaptersResult(
                novel_id=novel_id,
                current_phase=state.current_phase if state else Phase.LIBRARIAN.value,
                current_chapter_id=state.current_chapter_id if state else exc.chapter_id,
                completed_chapters=completed,
                stopped_reason="waiting_world_state_review",
                failed_phase=Phase.LIBRARIAN.value,
                failed_chapter_id=exc.chapter_id,
                error=str(exc),
                can_resume=True,
                resume_stage=ChapterRunStateService.stage_from_phase(Phase.LIBRARIAN.value),
                chapter_run=self._chapter_run_payload(state),
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
                can_resume=bool(state and state.current_chapter_id),
                resume_stage=ChapterRunStateService.stage_from_phase(state.current_phase if state else None),
                chapter_run=self._chapter_run_payload(state),
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
            can_resume=bool(state and state.current_chapter_id and stopped_reason != "novel_completed"),
            resume_stage=ChapterRunStateService.stage_from_phase(state.current_phase if state else None),
            chapter_run=self._chapter_run_payload(state),
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
        if state.current_chapter_id:
            chapter = await self.chapter_repo.get_by_id(state.current_chapter_id)
            ChapterRunStateService.ensure(
                checkpoint,
                novel_id=novel_id,
                chapter_id=state.current_chapter_id,
                phase=state.current_phase,
                run_id=token,
                chapter=chapter,
            )
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
        state = await self._ensure_chapter_run_state(state, start_chapter_id)

        for _ in range(20):
            await self.flow_control.raise_if_cancelled(novel_id)
            state = await self.director.resume(novel_id)
            if not state:
                raise ValueError(f"Novel state not found for {novel_id}")

            phase_before = state.current_phase
            await self._mark_stage_started(state, start_chapter_id)
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
            if updated:
                await self._mark_stage_after_step(
                    novel_id,
                    start_chapter_id,
                    previous_phase=phase_before,
                    updated=updated,
                )
            await self._raise_if_quality_blocked(start_chapter_id)
            if updated and updated.current_chapter_id != start_chapter_id:
                return start_chapter_id
            if updated and updated.current_phase == Phase.VOLUME_PLANNING.value:
                return start_chapter_id

        raise RuntimeError("Auto chapter generation exceeded phase iteration limit")

    async def _raise_if_quality_blocked(self, chapter_id: str) -> None:
        chapter = await self.chapter_repo.get_by_id(chapter_id)
        if chapter and getattr(chapter, "quality_status", "unchecked") == "block":
            state = await self.director.resume(chapter.novel_id or "")
            checkpoint = dict(state.checkpoint_data or {}) if state else {}
            if not ChapterRunStateService.quality_gate_matches_current_polished(checkpoint, chapter):
                return
            if self._is_stale_quality_block(state, chapter_id):
                return
            if self._is_repairable_quality_block(state, chapter_id):
                return
            raise QualityGateBlockedError(chapter_id, chapter.quality_reasons)

    @staticmethod
    def _is_stale_quality_block(state, chapter_id: str) -> bool:
        if state is None or state.current_chapter_id != chapter_id:
            return False
        return state.current_phase in {
            Phase.CONTEXT_PREPARATION.value,
            Phase.DRAFTING.value,
            Phase.REVIEWING.value,
            Phase.EDITING.value,
        }

    @staticmethod
    def _is_repairable_quality_block(state, chapter_id: str) -> bool:
        if state is None or state.current_phase != Phase.EDITING.value or state.current_chapter_id != chapter_id:
            return False
        checkpoint = dict(state.checkpoint_data or {})
        return bool(
            checkpoint.get("final_polish_issues")
            and int(checkpoint.get("quality_gate_repair_attempt_count", 0) or 0) > 0
        )

    @staticmethod
    def _quality_issues_for_block(checkpoint: dict, quality_reasons: dict | None = None) -> list[QualityIssue]:
        checkpoint_issues = ChapterGenerationService._quality_issues_from_checkpoint(checkpoint)
        if checkpoint_issues:
            return checkpoint_issues

        gate_issues = ChapterGenerationService._quality_issues_from_gate_reasons(quality_reasons)
        if gate_issues:
            return gate_issues

        return [
            QualityIssue(
                code="quality_blocked",
                category="process",
                severity="block",
                scope="chapter",
                repairability="manual",
                evidence=["质量门禁阻断，但 checkpoint 中缺少可解析的标准质量问题。"],
                suggestion="人工检查章节 quality_reasons、fast_review_feedback 和最近一次质量门禁输出。",
                source="quality_gate",
            )
        ]

    @staticmethod
    def _quality_issues_from_checkpoint(checkpoint: dict) -> list[QualityIssue]:
        raw_issues = checkpoint.get("quality_issues")
        if not isinstance(raw_issues, list):
            return []

        issues: list[QualityIssue] = []
        for raw_issue in raw_issues:
            if not isinstance(raw_issue, dict):
                continue
            try:
                issues.append(QualityIssue.model_validate(raw_issue))
            except ValueError:
                continue
        return issues

    @staticmethod
    def _quality_issues_from_gate_reasons(quality_reasons: dict | None) -> list[QualityIssue]:
        if not isinstance(quality_reasons, dict):
            return []
        gate = QualityGateResult(
            status=str(quality_reasons.get("status") or "block"),
            blocking_items=[
                item for item in quality_reasons.get("blocking_items") or []
                if isinstance(item, dict)
            ],
            warning_items=[
                item for item in quality_reasons.get("warning_items") or []
                if isinstance(item, dict)
            ],
            summary=str(quality_reasons.get("summary") or ""),
        )
        return QualityGateService.to_quality_issues(gate)

    @staticmethod
    def _trace_from_checkpoint(
        checkpoint: dict,
        novel_id: str,
        chapter_id: str,
        run_id: str,
        phase: str,
    ) -> ChapterRunTrace:
        raw_trace = checkpoint.get("chapter_run_trace")
        if isinstance(raw_trace, dict):
            try:
                trace = ChapterRunTrace.model_validate(raw_trace)
                if trace.novel_id == novel_id and trace.chapter_id == chapter_id:
                    trace.run_id = run_id
                    trace.current_phase = phase
                    return trace
            except ValueError:
                pass
        return ChapterRunTraceService.start_trace(novel_id, chapter_id, run_id, phase)

    async def _maybe_run_periodic_global_consistency_audit(
        self,
        novel_id: str,
        completed_count: int,
    ) -> GlobalConsistencyAuditResult | None:
        state = await self.director.resume(novel_id)
        if not state:
            return None
        checkpoint = dict(state.checkpoint_data or {})
        interval = int(checkpoint.get("global_audit_interval_chapters") or 20)
        if interval <= 0 or completed_count <= 0 or completed_count % interval != 0:
            return None
        result = await GlobalConsistencyAuditService(self.session).run(novel_id)
        checkpoint["global_consistency_audit"] = result.model_dump()
        await self.director.save_checkpoint(
            novel_id,
            Phase(state.current_phase),
            checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )
        await self.session.commit()
        return result

    async def _sync_current_chapter_checkpoint(self, state):
        checkpoint = dict(state.checkpoint_data or {})
        current_chapter_id = state.current_chapter_id
        if not current_chapter_id:
            return state

        current_plan = checkpoint.get("current_chapter_plan")
        if isinstance(current_plan, dict) and current_plan.get("chapter_id") == current_chapter_id:
            return state
        matching_plan = None
        compatible_current_plan = False
        if isinstance(current_plan, dict):
            current_identity = self._chapter_identity(str(current_chapter_id))
            current_plan_identity = self._chapter_identity(str(current_plan.get("chapter_id") or ""))
            current_volume_id = str(state.current_volume_id or "").strip()
            if (
                current_identity != (None, None)
                and current_plan_identity == current_identity
                and self._volume_ids_compatible(
                    current_volume_id,
                    str(current_plan.get("volume_id") or ""),
                )
            ):
                matching_plan = current_plan
                compatible_current_plan = True

        volume_plan = checkpoint.get("current_volume_plan") or {}
        chapters = volume_plan.get("chapters") or []
        if matching_plan is None:
            matching_plan = next(
                (
                    chapter
                    for chapter in chapters
                    if isinstance(chapter, dict) and chapter.get("chapter_id") == current_chapter_id
                ),
                None,
            )
        if not matching_plan:
            current_identity = self._chapter_identity(str(current_chapter_id))
            current_volume_id = str(state.current_volume_id or "").strip()
            matching_plan = next(
                (
                    chapter
                    for chapter in chapters
                    if isinstance(chapter, dict)
                    and self._chapter_identity(str(chapter.get("chapter_id") or "")) == current_identity
                    and self._volume_ids_compatible(current_volume_id, str(chapter.get("volume_id") or ""))
                ),
                None,
            )
        if not matching_plan:
            raise ValueError(f"current_chapter_plan does not match current_chapter_id {current_chapter_id}")

        if compatible_current_plan:
            normalized_plan = dict(matching_plan)
            normalized_plan["chapter_id"] = current_chapter_id
            if state.current_volume_id:
                normalized_plan["volume_id"] = state.current_volume_id
            checkpoint["current_chapter_plan"] = normalized_plan
            log_agent_detail(
                state.novel_id,
                "ChapterGenerationService",
                f"章节计划兼容当前章节：{current_chapter_id}",
                node="chapter_state_sync",
                task="auto_run",
                status="succeeded",
                metadata={
                    "current_chapter_id": current_chapter_id,
                    "current_plan_id": current_plan.get("chapter_id") if isinstance(current_plan, dict) else None,
                    "current_phase": state.current_phase,
                    "normalized_plan_id": current_chapter_id,
                    "preserved_checkpoint_keys": sorted(key for key in CHAPTER_SCOPED_CHECKPOINT_KEYS if key in checkpoint),
                },
            )
            return await self.director.save_checkpoint(
                state.novel_id,
                Phase(state.current_phase),
                checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=current_chapter_id,
            )

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

    @staticmethod
    def _chapter_identity(chapter_id: str) -> tuple[int | None, int | None]:
        match = re.search(r"vol_(\d+)_ch_(\d+)", chapter_id)
        if not match:
            return (None, None)
        return (int(match.group(1)), int(match.group(2)))

    @staticmethod
    def _volume_ids_compatible(left: str, right: str) -> bool:
        if not left or not right:
            return True
        if left == right:
            return True
        left_match = re.search(r"vol_(\d+)", left)
        right_match = re.search(r"vol_(\d+)", right)
        if not left_match or not right_match:
            return False
        return int(left_match.group(1)) == int(right_match.group(1))

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

    async def _ensure_chapter_run_state(self, state, chapter_id: str):
        checkpoint = dict(state.checkpoint_data or {})
        lock = checkpoint.get("auto_run_lock") if isinstance(checkpoint.get("auto_run_lock"), dict) else {}
        chapter = await self.chapter_repo.get_by_id(chapter_id)
        ChapterRunStateService.ensure(
            checkpoint,
            novel_id=state.novel_id,
            chapter_id=chapter_id,
            phase=state.current_phase,
            run_id=lock.get("token"),
            chapter=chapter,
        )
        return await self.director.save_checkpoint(
            state.novel_id,
            Phase(state.current_phase),
            checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=chapter_id,
        )

    async def _mark_stage_started(self, state, chapter_id: str) -> None:
        checkpoint = dict(state.checkpoint_data or {})
        chapter = await self.chapter_repo.get_by_id(chapter_id)
        run = ChapterRunStateService.ensure(
            checkpoint,
            novel_id=state.novel_id,
            chapter_id=chapter_id,
            phase=state.current_phase,
            chapter=chapter,
        )
        stage = ChapterRunStateService.stage_from_phase(state.current_phase)
        attempts = dict(run.get("attempts") or {})
        attempts[stage] = int(attempts.get(stage, 0) or 0) + 1
        run["attempts"] = attempts
        run["stage"] = stage
        checkpoint["chapter_run"] = run
        await self.director.save_checkpoint(
            state.novel_id,
            Phase(state.current_phase),
            checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=chapter_id,
        )
        await self.session.commit()

    async def _mark_stage_after_step(self, novel_id: str, chapter_id: str, *, previous_phase: str, updated) -> None:
        if updated.current_chapter_id != chapter_id:
            return
        checkpoint = dict(updated.checkpoint_data or {})
        previous_stage = ChapterRunStateService.stage_from_phase(previous_phase)
        current_stage = ChapterRunStateService.stage_from_phase(updated.current_phase)
        chapter = await self.chapter_repo.get_by_id(chapter_id)
        previous_index = self._stage_index(previous_stage)
        current_index = self._stage_index(current_stage)
        completed_current_stage = (
            current_index > previous_index
            or (previous_phase == Phase.LIBRARIAN.value and updated.current_phase == Phase.COMPLETED.value)
        )
        if completed_current_stage:
            run = ChapterRunStateService.mark_stage(
                checkpoint,
                stage=previous_stage,
                status="succeeded",
                chapter=chapter,
            )
            run["stage"] = current_stage
            checkpoint["chapter_run"] = run
        else:
            run = ChapterRunStateService.ensure(
                checkpoint,
                novel_id=novel_id,
                chapter_id=chapter_id,
                phase=updated.current_phase,
                chapter=chapter,
            )
            run["stage"] = current_stage
            checkpoint["chapter_run"] = run
        await self.director.save_checkpoint(
            novel_id,
            Phase(updated.current_phase),
            checkpoint,
            volume_id=updated.current_volume_id,
            chapter_id=updated.current_chapter_id,
        )
        await self.session.commit()

    @staticmethod
    def _stage_index(stage: str) -> int:
        try:
            return CHAPTER_RUN_STAGES.index(stage)
        except ValueError:
            return -1

    def _embedding_service(self):
        embedder = llm_factory.get_embedder()
        if embedder is None:
            return None
        return EmbeddingService(self.session, embedder)
