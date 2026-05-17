import uuid
from enum import Enum
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.db.models import NovelState
from novel_dev.agents._log_helpers import log_agent_detail
from novel_dev.config import settings
from novel_dev.services.log_service import logged_agent_step, log_service
from novel_dev.services.volume_plan_guard_service import ensure_volume_plan_accepted


class Phase(str, Enum):
    BRAINSTORMING = "brainstorming"
    VOLUME_PLANNING = "volume_planning"
    CONTEXT_PREPARATION = "context_preparation"
    DRAFTING = "drafting"
    REVIEWING = "reviewing"
    EDITING = "editing"
    FAST_REVIEWING = "fast_reviewing"
    LIBRARIAN = "librarian"
    COMPLETED = "completed"


VALID_TRANSITIONS = {
    Phase.BRAINSTORMING: [Phase.VOLUME_PLANNING],
    Phase.VOLUME_PLANNING: [Phase.BRAINSTORMING, Phase.CONTEXT_PREPARATION],
    Phase.CONTEXT_PREPARATION: [Phase.DRAFTING],
    Phase.DRAFTING: [Phase.REVIEWING],
    Phase.REVIEWING: [Phase.EDITING, Phase.DRAFTING],
    Phase.EDITING: [Phase.FAST_REVIEWING],
    Phase.FAST_REVIEWING: [Phase.LIBRARIAN, Phase.DRAFTING, Phase.EDITING],
    Phase.LIBRARIAN: [Phase.COMPLETED],
    Phase.COMPLETED: [Phase.CONTEXT_PREPARATION, Phase.VOLUME_PLANNING],
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


class NovelDirector:
    def __init__(self, session: Optional[AsyncSession] = None):
        self.session = session
        self.state_repo = NovelStateRepository(session) if session else None

    def can_transition(self, current: Phase, next_phase: Phase) -> bool:
        return next_phase in VALID_TRANSITIONS.get(current, [])

    async def save_checkpoint(
        self,
        novel_id: str,
        phase: Phase,
        checkpoint_data: dict,
        volume_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
    ) -> NovelState:
        if self.state_repo is None:
            raise RuntimeError("NovelDirector requires a session to save checkpoints")
        return await self.state_repo.save_checkpoint(
            novel_id,
            current_phase=phase.value,
            checkpoint_data=checkpoint_data,
            current_volume_id=volume_id,
            current_chapter_id=chapter_id,
        )

    async def resume(self, novel_id: str) -> Optional[NovelState]:
        if self.state_repo is None:
            raise RuntimeError("NovelDirector requires a session to resume")
        return await self.state_repo.get_state(novel_id)

    @logged_agent_step("NovelDirector", "自动推进流程", node="advance", task="advance")
    async def advance(self, novel_id: str) -> NovelState:
        state = await self.resume(novel_id)
        if not state:
            log_service.add_log(novel_id, "NovelDirector", "小说状态未找到", level="error")
            raise ValueError(f"Novel state not found for {novel_id}")
        current = Phase(state.current_phase)
        checkpoint = dict(state.checkpoint_data or {})
        log_agent_detail(
            novel_id,
            "NovelDirector",
            f"流程推进准备：当前阶段 {current.value}",
            node="advance_phase",
            task="advance",
            status="started",
            metadata={
                "current_phase": current.value,
                "current_volume_id": state.current_volume_id,
                "current_chapter_id": state.current_chapter_id,
                "checkpoint_keys": sorted(checkpoint.keys()),
            },
        )

        if current == Phase.BRAINSTORMING:
            from novel_dev.repositories.document_repo import DocumentRepository
            docs = await DocumentRepository(self.session).get_current_by_type(novel_id, "synopsis")
            if not docs:
                log_service.add_log(novel_id, "NovelDirector", "synopsis 未生成", level="error")
                raise ValueError("Synopsis not generated yet. Call POST /brainstorm first.")
            log_service.add_log(novel_id, "NovelDirector", "brainstorming → volume_planning")
            return await self.save_checkpoint(
                novel_id, Phase.VOLUME_PLANNING, checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )
        elif current == Phase.VOLUME_PLANNING:
            log_agent_detail(
                novel_id,
                "NovelDirector",
                "进入 VolumePlannerAgent",
                node="advance_agent",
                task="advance",
                status="started",
                metadata={"from_phase": current.value, "target_agent": "VolumePlannerAgent", "target_phase": Phase.CONTEXT_PREPARATION.value},
            )
            return await self._run_volume_planner(state)
        elif current == Phase.CONTEXT_PREPARATION:
            try:
                ensure_volume_plan_accepted(checkpoint)
            except ValueError as exc:
                log_service.add_log(novel_id, "NovelDirector", str(exc), level="error")
                raise
            if not checkpoint.get("chapter_context"):
                log_service.add_log(novel_id, "NovelDirector", "章节上下文未准备", level="error")
                raise ValueError("Chapter context not prepared. Call POST /chapters/{cid}/context first.")
            if not self._chapter_context_matches_current_plan(checkpoint):
                log_service.add_log(novel_id, "NovelDirector", "章节上下文与当前章节计划不匹配", level="error")
                raise ValueError("Chapter context is stale for current chapter. Call POST /chapters/{cid}/context first.")
            log_service.add_log(novel_id, "NovelDirector", "context_preparation → drafting")
            return await self.save_checkpoint(
                novel_id, Phase.DRAFTING, checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )
        elif current == Phase.DRAFTING:
            chapter_id = state.current_chapter_id
            if not chapter_id:
                log_service.add_log(novel_id, "NovelDirector", "drafting 阶段未设置当前章节", level="error")
                raise ValueError("No current chapter set for DRAFTING phase")
            from novel_dev.repositories.chapter_repo import ChapterRepository
            ch = await ChapterRepository(self.session).get_by_id(chapter_id)
            if not ch or not ch.raw_draft:
                log_service.add_log(novel_id, "NovelDirector", "章节草稿未生成", level="error")
                raise ValueError("Chapter draft not generated. Call POST /chapters/{cid}/draft first.")
            log_service.add_log(novel_id, "NovelDirector", "drafting → reviewing")
            return await self.save_checkpoint(
                novel_id, Phase.REVIEWING, checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=chapter_id,
            )
        elif current == Phase.REVIEWING:
            log_agent_detail(
                novel_id, "NovelDirector", "进入 CriticAgent",
                node="advance_agent", task="advance", status="started",
                metadata={"from_phase": current.value, "target_agent": "CriticAgent", "chapter_id": state.current_chapter_id},
            )
            return await self._run_critic(state)
        elif current == Phase.EDITING:
            log_agent_detail(
                novel_id, "NovelDirector", "进入 EditorAgent",
                node="advance_agent", task="advance", status="started",
                metadata={"from_phase": current.value, "target_agent": "EditorAgent", "chapter_id": state.current_chapter_id},
            )
            return await self._run_editor(state)
        elif current == Phase.FAST_REVIEWING:
            log_agent_detail(
                novel_id, "NovelDirector", "进入 FastReviewAgent",
                node="advance_agent", task="advance", status="started",
                metadata={"from_phase": current.value, "target_agent": "FastReviewAgent", "chapter_id": state.current_chapter_id},
            )
            return await self._run_fast_review(state)
        elif current == Phase.LIBRARIAN:
            log_agent_detail(
                novel_id, "NovelDirector", "进入 LibrarianAgent",
                node="advance_agent", task="advance", status="started",
                metadata={"from_phase": current.value, "target_agent": "LibrarianAgent", "chapter_id": state.current_chapter_id},
            )
            return await self._run_librarian(state)
        elif current == Phase.COMPLETED:
            log_service.add_log(novel_id, "NovelDirector", "completed → 继续下一章/卷")
            return await self._continue_to_next_chapter(novel_id)
        else:
            log_service.add_log(novel_id, "NovelDirector", f"无法从 {current.value} 自动推进", level="error")
            raise ValueError(f"Cannot auto-advance from {current}")

    @logged_agent_step("NovelDirector", "运行归档流程", node="librarian", task="run_librarian")
    async def run_librarian(self, novel_id: str) -> NovelState:
        state = await self.resume(novel_id)
        if not state:
            log_service.add_log(novel_id, "NovelDirector", "小说状态未找到", level="error")
            raise ValueError(f"Novel state not found for {novel_id}")
        return await self._run_librarian(state)

    async def _run_volume_planner(self, state: NovelState) -> NovelState:
        from novel_dev.agents.volume_planner import VolumePlannerAgent
        agent = VolumePlannerAgent(self.session)
        await agent.plan(state.novel_id)
        return await self.resume(state.novel_id)

    async def _run_critic(self, state: NovelState) -> NovelState:
        from novel_dev.agents.critic_agent import CriticAgent
        agent = CriticAgent(self.session)
        await agent.review(state.novel_id, state.current_chapter_id)
        return await self.resume(state.novel_id)

    async def _run_editor(self, state: NovelState) -> NovelState:
        from novel_dev.agents.editor_agent import EditorAgent
        from novel_dev.services.embedding_service import EmbeddingService
        from novel_dev.llm import llm_factory
        embedder = llm_factory.get_embedder()
        embedding_service = EmbeddingService(self.session, embedder)
        agent = EditorAgent(self.session, embedding_service)
        await agent.polish(state.novel_id, state.current_chapter_id)
        return await self.resume(state.novel_id)

    async def _run_fast_review(self, state: NovelState) -> NovelState:
        from novel_dev.agents.fast_review_agent import FastReviewAgent
        agent = FastReviewAgent(self.session)
        await agent.review(state.novel_id, state.current_chapter_id)
        return await self.resume(state.novel_id)

    async def _run_librarian(self, state: NovelState) -> NovelState:
        from novel_dev.agents.librarian import LibrarianAgent
        from novel_dev.services.archive_service import ArchiveService
        from novel_dev.repositories.chapter_repo import ChapterRepository

        chapter_id = state.current_chapter_id
        if not chapter_id:
            log_service.add_log(state.novel_id, "NovelDirector", "librarian 阶段未设置当前章节", level="error")
            raise ValueError("No current chapter set for LIBRARIAN phase")

        ch = await ChapterRepository(self.session).get_by_id(chapter_id)
        if not ch or not ch.polished_text:
            log_service.add_log(state.novel_id, "NovelDirector", "章节精修文本缺失", level="error")
            raise ValueError("Chapter polished text missing")
        if getattr(ch, "quality_status", "unchecked") == "block":
            log_service.add_log(
                state.novel_id,
                "NovelDirector",
                "章节质量门禁阻断，禁止进入 Librarian",
                level="error",
            )
            raise ValueError("Chapter quality gate blocked librarian ingestion")

        from novel_dev.services.embedding_service import EmbeddingService
        from novel_dev.llm import llm_factory
        embedder = llm_factory.get_embedder()
        embedding_service = EmbeddingService(self.session, embedder)
        agent = LibrarianAgent(self.session, embedding_service)
        try:
            extraction = await agent.extract(state.novel_id, chapter_id, ch.polished_text)
        except Exception as llm_error:
            log_service.add_log(state.novel_id, "NovelDirector", f"Librarian 提取失败: {llm_error}", level="warning")
            try:
                extraction = agent.fallback_extract(ch.polished_text, state.checkpoint_data)
                log_service.add_log(state.novel_id, "NovelDirector", "Librarian 使用 fallback 提取")
            except Exception as fallback_error:
                checkpoint = dict(state.checkpoint_data)
                checkpoint["librarian_error"] = str(llm_error)
                await self.save_checkpoint(
                    state.novel_id,
                    Phase.LIBRARIAN,
                    checkpoint,
                    volume_id=state.current_volume_id,
                    chapter_id=chapter_id,
                )
                log_service.add_log(state.novel_id, "NovelDirector", f"Librarian fallback 也失败: {fallback_error}", level="error")
                raise RuntimeError(
                    f"Librarian extraction failed: LLM={llm_error}, fallback={fallback_error}"
                )

        await agent.persist(extraction, chapter_id, state.novel_id)
        await ChapterRepository(self.session).mark_world_state_ingested(chapter_id, True)

        archive_svc = ArchiveService(self.session, settings.data_dir)
        await archive_svc.archive(state.novel_id, chapter_id)
        log_agent_detail(
            state.novel_id,
            "NovelDirector",
            "章节归档完成",
            node="archive",
            task="run_librarian",
            metadata={
                "chapter_id": chapter_id,
                "volume_id": state.current_volume_id,
                "polished_chars": len(ch.polished_text or ""),
            },
        )

        checkpoint = dict(state.checkpoint_data)
        checkpoint["last_archived_chapter_id"] = chapter_id
        await self.save_checkpoint(
            state.novel_id,
            Phase.COMPLETED,
            checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=chapter_id,
        )
        log_agent_detail(
            state.novel_id,
            "NovelDirector",
            "阶段跳转完成：进入 completed",
            node="phase_transition",
            task="run_librarian",
            metadata={"from_phase": Phase.LIBRARIAN.value, "to_phase": Phase.COMPLETED.value, "chapter_id": chapter_id},
        )

        return await self._continue_to_next_chapter(state.novel_id)

    async def _continue_to_next_chapter(self, novel_id: str) -> NovelState:
        state = await self.resume(novel_id)
        checkpoint = dict(state.checkpoint_data or {})

        volume_plan = checkpoint.get("current_volume_plan", {})
        chapters = volume_plan.get("chapters", [])
        current_chapter_id = state.current_chapter_id

        for idx, ch_plan in enumerate(chapters):
            if ch_plan.get("chapter_id") == current_chapter_id and idx + 1 < len(chapters):
                next_plan = chapters[idx + 1]
                from novel_dev.repositories.chapter_repo import ChapterRepository
                await ChapterRepository(self.session).ensure_from_plan(
                    novel_id,
                    state.current_volume_id,
                    next_plan,
                )
                for key in CHAPTER_SCOPED_CHECKPOINT_KEYS:
                    checkpoint.pop(key, None)
                checkpoint["current_chapter_plan"] = next_plan
                log_agent_detail(
                    novel_id,
                    "NovelDirector",
                    f"进入下一章：{next_plan.get('title')}",
                    node="phase_transition",
                    task="continue_chapter",
                    metadata={
                        "from_phase": Phase.COMPLETED.value,
                        "to_phase": Phase.CONTEXT_PREPARATION.value,
                        "previous_chapter_id": current_chapter_id,
                        "next_chapter_id": next_plan.get("chapter_id"),
                        "next_title": next_plan.get("title"),
                    },
                )
                return await self.save_checkpoint(
                    novel_id,
                    Phase.CONTEXT_PREPARATION,
                    checkpoint,
                    volume_id=state.current_volume_id,
                    chapter_id=next_plan.get("chapter_id"),
                )

        current_volume_number = 1
        if state.current_volume_id and state.current_volume_id.startswith("vol_"):
            try:
                current_volume_number = int(state.current_volume_id.replace("vol_", ""))
            except ValueError:
                pass

        next_volume_id = f"vol_{current_volume_number + 1}"
        avg_word_count = checkpoint.get("archive_stats", {}).get("avg_word_count", 3000)
        placeholder_volume = {
            "volume_id": next_volume_id,
            "title": "占位卷纲（待 VolumePlannerAgent 填充）",
            "chapters": [
                {
                    "chapter_id": str(uuid.uuid4()),
                    "title": "占位章节",
                    "target_word_count": avg_word_count,
                }
            ],
        }
        checkpoint["pending_volume_plans"] = checkpoint.get("pending_volume_plans", []) + [placeholder_volume]
        checkpoint["volume_completed"] = True
        checkpoint.pop("current_chapter_plan", None)
        log_agent_detail(
            novel_id,
            "NovelDirector",
            f"当前卷完成，进入第 {current_volume_number + 1} 卷规划",
            node="phase_transition",
            task="continue_chapter",
            metadata={
                "from_phase": Phase.COMPLETED.value,
                "to_phase": Phase.VOLUME_PLANNING.value,
                "completed_volume_id": state.current_volume_id,
                "next_volume_id": next_volume_id,
                "placeholder_chapter_id": placeholder_volume["chapters"][0]["chapter_id"],
            },
        )

        return await self.save_checkpoint(
            novel_id,
            Phase.VOLUME_PLANNING,
            checkpoint,
            volume_id=next_volume_id,
            chapter_id=placeholder_volume["chapters"][0]["chapter_id"],
        )

    @staticmethod
    def _chapter_context_matches_current_plan(checkpoint: dict) -> bool:
        context_data = checkpoint.get("chapter_context")
        current_plan = checkpoint.get("current_chapter_plan")
        if not isinstance(context_data, dict) or not isinstance(current_plan, dict):
            return False

        context_plan = context_data.get("chapter_plan")
        if not isinstance(context_plan, dict):
            return False

        if context_plan.get("chapter_number") != current_plan.get("chapter_number"):
            return False
        if (context_plan.get("title") or "") != (current_plan.get("title") or ""):
            return False
        if int(context_plan.get("target_word_count") or 0) != int(current_plan.get("target_word_count") or 0):
            return False

        context_beats = context_plan.get("beats") or []
        current_beats = current_plan.get("beats") or []
        return len(context_beats) == len(current_beats)
