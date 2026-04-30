from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.agents.critic_agent import CriticAgent
from novel_dev.agents.editor_agent import EditorAgent
from novel_dev.agents.fast_review_agent import MAX_EDIT_ATTEMPTS, FastReviewAgent
from novel_dev.agents.librarian import LibrarianAgent
from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.config import settings
from novel_dev.db.models import Entity, EntityRelationship, EntityVersion, Foreshadowing, Timeline
from novel_dev.llm import llm_factory
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.schemas.context import ChapterPlan
from novel_dev.services.archive_service import ArchiveService
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.services.flow_control_service import FlowControlService
from novel_dev.services.log_service import log_service
from novel_dev.services.quality_gate_service import QUALITY_BLOCK


REWRITE_STAGE_CONTEXT = "context"
REWRITE_STAGE_DRAFT = "draft"
REWRITE_STAGE_REVIEW = "review"
REWRITE_STAGE_EDIT_FAST_REVIEW = "edit_fast_review"
REWRITE_STAGE_LIBRARIAN_ARCHIVE = "librarian_archive"
REWRITE_STAGES = [
    REWRITE_STAGE_CONTEXT,
    REWRITE_STAGE_DRAFT,
    REWRITE_STAGE_REVIEW,
    REWRITE_STAGE_EDIT_FAST_REVIEW,
    REWRITE_STAGE_LIBRARIAN_ARCHIVE,
]


class ChapterRewriteResult(BaseModel):
    novel_id: str
    chapter_id: str
    status: str = "succeeded"
    raw_word_count: int = 0
    polished_word_count: int = 0
    score_overall: int | None = None
    fast_review_score: int | None = None
    archive: dict = Field(default_factory=dict)
    error: str | None = None
    completed_stages: list[str] = Field(default_factory=list)
    failed_stage: str | None = None
    resume_from_stage: str | None = None
    can_resume: bool = False
    rewrite_checkpoint: dict = Field(default_factory=dict)


class ChapterRewriteFailedError(Exception):
    def __init__(self, result: ChapterRewriteResult):
        super().__init__(result.error or "Chapter rewrite failed")
        self.result = result


class ChapterRewriteService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.flow_control = FlowControlService(session)

    async def rewrite(
        self,
        novel_id: str,
        chapter_id: str,
        *,
        resume_from_stage: str | None = None,
        resume_checkpoint: dict | None = None,
        job_id: str | None = None,
        job_repo: GenerationJobRepository | None = None,
    ) -> ChapterRewriteResult:
        log_service.add_log(novel_id, "ChapterRewriteService", f"开始独立重写章节: {chapter_id}")
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")

        volume_id, chapter_plan_data = self._find_chapter_plan(state.checkpoint_data or {}, chapter_id)
        existing = await self.chapter_repo.get_by_id(chapter_id)
        start_stage = resume_from_stage or REWRITE_STAGE_CONTEXT
        if start_stage not in REWRITE_STAGES:
            raise ValueError(f"Unsupported rewrite resume stage: {start_stage}")
        if existing and existing.novel_id != novel_id:
            raise ValueError(f"Chapter not found: {chapter_id}")
        if not existing and start_stage != REWRITE_STAGE_CONTEXT:
            raise ValueError(f"Chapter not found: {chapter_id}")
        if (
            existing
            and existing.status not in {"drafted", "edited", "archived"}
            and not (resume_from_stage and start_stage == REWRITE_STAGE_CONTEXT and existing.status == "pending")
        ):
            raise ValueError("Only drafted, edited or archived chapters can be rewritten")

        start_index = REWRITE_STAGES.index(start_stage)
        completed_stages = REWRITE_STAGES[:start_index] if resume_from_stage else []
        checkpoint = dict(resume_checkpoint or {})
        embedding_service = self._embedding_service()
        chapter_plan = ChapterPlan.model_validate(chapter_plan_data)

        current_stage = start_stage
        score_overall: int | None = existing.score_overall if existing else None
        try:
            await self.flow_control.raise_if_cancelled(novel_id)
            await self.chapter_repo.ensure_from_plan(novel_id, volume_id, chapter_plan_data)
            if start_stage == REWRITE_STAGE_CONTEXT:
                await self.chapter_repo.reset_generation(chapter_id)
                existing = await self.chapter_repo.get_by_id(chapter_id)

            if self._should_run(REWRITE_STAGE_CONTEXT, start_index):
                current_stage = REWRITE_STAGE_CONTEXT
                context = await ContextAgent(self.session, embedding_service).assemble_for_chapter(
                    novel_id,
                    chapter_id,
                    chapter_plan,
                    volume_id=volume_id,
                    checkpoint=state.checkpoint_data or {},
                )
                checkpoint["chapter_context"] = context.model_dump()
                checkpoint["drafting_progress"] = {
                    "beat_index": 0,
                    "total_beats": len(chapter_plan.beats),
                    "current_word_count": 0,
                }
                completed_stages.append(REWRITE_STAGE_CONTEXT)
                await self._record_progress(job_id, job_repo, novel_id, chapter_id, completed_stages, checkpoint)

            if self._should_run(REWRITE_STAGE_DRAFT, start_index):
                current_stage = REWRITE_STAGE_DRAFT
                context_data = await self._ensure_context_data(novel_id, chapter_id, chapter_plan, volume_id, checkpoint, state)
                chapter_context = self._chapter_context_from_checkpoint(context_data)
                _metadata, checkpoint = await WriterAgent(self.session, embedding_service).write_standalone(
                    novel_id,
                    chapter_context,
                    chapter_id,
                )
                completed_stages.append(REWRITE_STAGE_DRAFT)
                await self._record_progress(job_id, job_repo, novel_id, chapter_id, completed_stages, checkpoint)

            if self._should_run(REWRITE_STAGE_REVIEW, start_index):
                current_stage = REWRITE_STAGE_REVIEW
                await self._ensure_context_data(novel_id, chapter_id, chapter_plan, volume_id, checkpoint, state)
                score_result, review_checkpoint = await CriticAgent(self.session).review_standalone(
                    novel_id,
                    chapter_id,
                    checkpoint["chapter_context"],
                )
                score_overall = score_result.overall
                checkpoint.update(review_checkpoint)
                completed_stages.append(REWRITE_STAGE_REVIEW)
                await self._record_progress(job_id, job_repo, novel_id, chapter_id, completed_stages, checkpoint)

            if self._should_run(REWRITE_STAGE_EDIT_FAST_REVIEW, start_index):
                current_stage = REWRITE_STAGE_EDIT_FAST_REVIEW
                await self._ensure_context_data(novel_id, chapter_id, chapter_plan, volume_id, checkpoint, state)
                report = None
                for attempt in range(MAX_EDIT_ATTEMPTS + 1):
                    await self.flow_control.raise_if_cancelled(novel_id)
                    checkpoint["edit_attempt_count"] = attempt + 1
                    await EditorAgent(self.session, embedding_service).polish_standalone(novel_id, chapter_id, checkpoint)

                    await self.flow_control.raise_if_cancelled(novel_id)
                    report = await FastReviewAgent(self.session).review_standalone(novel_id, chapter_id, checkpoint)
                    checkpoint["fast_review_feedback"] = report.model_dump()
                    if all([
                        report.word_count_ok,
                        report.consistency_fixed,
                        report.ai_flavor_reduced,
                        report.beat_cohesion_ok,
                        getattr(report, "language_style_ok", True),
                    ]):
                        break
                    if (checkpoint.get("quality_gate") or {}).get("status") == QUALITY_BLOCK:
                        raise RuntimeError("Chapter quality gate blocked librarian ingestion")
                checkpoint.pop("edit_attempt_count", None)
                completed_stages.append(REWRITE_STAGE_EDIT_FAST_REVIEW)
                await self._record_progress(job_id, job_repo, novel_id, chapter_id, completed_stages, checkpoint)

            current_stage = REWRITE_STAGE_LIBRARIAN_ARCHIVE
            await self.flow_control.raise_if_cancelled(novel_id)
            chapter = await self.chapter_repo.get_by_id(chapter_id)
            if not chapter or not chapter.polished_text:
                raise ValueError("Chapter has no polished text after rewrite")
            if resume_from_stage == REWRITE_STAGE_LIBRARIAN_ARCHIVE and await self._has_librarian_artifacts(novel_id, chapter_id):
                log_service.add_log(
                    novel_id,
                    "ChapterRewriteService",
                    f"检测到章节 {chapter_id} 已有资料入库记录，续跑时跳过资料重复持久化",
                )
            else:
                librarian = LibrarianAgent(self.session, embedding_service)
                extraction = await librarian.extract(novel_id, chapter_id, chapter.polished_text)
                await librarian.persist(extraction, chapter_id, novel_id)
                await self.chapter_repo.mark_world_state_ingested(chapter_id, True)

            archive_result = await ArchiveService(self.session, settings.markdown_output_dir).archive_chapter_only(
                novel_id,
                chapter_id,
            )
            completed_stages.append(REWRITE_STAGE_LIBRARIAN_ARCHIVE)
        except Exception as exc:
            checkpoint.pop("edit_attempt_count", None)
            await self.session.rollback()
            failed_chapter = await self.chapter_repo.get_by_id(chapter_id)
            result = ChapterRewriteResult(
                novel_id=novel_id,
                chapter_id=chapter_id,
                status="failed",
                raw_word_count=len(failed_chapter.raw_draft or "") if failed_chapter else 0,
                polished_word_count=len(failed_chapter.polished_text or "") if failed_chapter else 0,
                error=str(exc),
                completed_stages=completed_stages,
                failed_stage=current_stage,
                resume_from_stage=current_stage,
                can_resume=True,
                rewrite_checkpoint=checkpoint,
            )
            raise ChapterRewriteFailedError(result) from exc

        chapter = await self.chapter_repo.get_by_id(chapter_id)
        log_service.add_log(novel_id, "ChapterRewriteService", f"独立重写章节完成: {chapter_id}")
        return ChapterRewriteResult(
            novel_id=novel_id,
            chapter_id=chapter_id,
            raw_word_count=len(chapter.raw_draft or "") if chapter else 0,
            polished_word_count=len(chapter.polished_text or "") if chapter else 0,
            score_overall=score_overall,
            fast_review_score=chapter.fast_review_score if chapter else None,
            archive=archive_result,
            completed_stages=completed_stages,
        )

    @staticmethod
    def _should_run(stage: str, start_index: int) -> bool:
        return REWRITE_STAGES.index(stage) >= start_index

    async def _record_progress(
        self,
        job_id: str | None,
        job_repo: GenerationJobRepository | None,
        novel_id: str,
        chapter_id: str,
        completed_stages: list[str],
        checkpoint: dict,
    ) -> None:
        if not job_id or not job_repo:
            return
        await job_repo.update_result_payload(
            job_id,
            {
                "novel_id": novel_id,
                "chapter_id": chapter_id,
                "status": "running",
                "completed_stages": list(completed_stages),
                "rewrite_checkpoint": checkpoint,
            },
        )
        await self.session.commit()

    async def _ensure_context_data(
        self,
        novel_id: str,
        chapter_id: str,
        chapter_plan: ChapterPlan,
        volume_id: str,
        checkpoint: dict,
        state,
    ) -> dict:
        context_data = checkpoint.get("chapter_context")
        if context_data:
            return context_data
        context = await ContextAgent(self.session, self._embedding_service()).assemble_for_chapter(
            novel_id,
            chapter_id,
            chapter_plan,
            volume_id=volume_id,
            checkpoint=state.checkpoint_data or {},
        )
        checkpoint["chapter_context"] = context.model_dump()
        return checkpoint["chapter_context"]

    def _chapter_context_from_checkpoint(self, context_data: dict):
        from novel_dev.schemas.context import ChapterContext

        return ChapterContext.model_validate(context_data)

    async def _has_librarian_artifacts(self, novel_id: str, chapter_id: str) -> bool:
        checks = [
            select(func.count()).select_from(Timeline).where(
                Timeline.novel_id == novel_id,
                Timeline.anchor_chapter_id == chapter_id,
            ),
            select(func.count()).select_from(Entity).where(
                Entity.novel_id == novel_id,
                Entity.created_at_chapter_id == chapter_id,
            ),
            select(func.count()).select_from(EntityVersion).where(EntityVersion.chapter_id == chapter_id),
            select(func.count()).select_from(EntityRelationship).where(
                EntityRelationship.novel_id == novel_id,
                EntityRelationship.created_at_chapter_id == chapter_id,
            ),
            select(func.count()).select_from(Foreshadowing).where(
                Foreshadowing.novel_id == novel_id,
                or_(
                    Foreshadowing.埋下_chapter_id == chapter_id,
                    Foreshadowing.recovered_chapter_id == chapter_id,
                ),
            ),
        ]
        for stmt in checks:
            result = await self.session.execute(stmt)
            if int(result.scalar_one() or 0) > 0:
                return True
        return False

    @staticmethod
    def _find_chapter_plan(checkpoint: dict, chapter_id: str) -> tuple[str, dict]:
        volume_plan = checkpoint.get("current_volume_plan") or {}
        volume_id = volume_plan.get("volume_id") or ""
        for chapter in volume_plan.get("chapters", []) or []:
            chapter_data = chapter.model_dump() if hasattr(chapter, "model_dump") else dict(chapter or {})
            if chapter_data.get("chapter_id") == chapter_id:
                if not volume_id:
                    volume_id = chapter_data.get("volume_id") or ""
                if not volume_id:
                    raise ValueError("volume_id missing for chapter rewrite")
                return volume_id, chapter_data
        raise ValueError(f"Chapter plan not found: {chapter_id}")

    def _embedding_service(self):
        embedder = llm_factory.get_embedder()
        if embedder is None:
            return None
        return EmbeddingService(self.session, embedder)
