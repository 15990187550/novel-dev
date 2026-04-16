import uuid
from enum import Enum
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.db.models import NovelState


class Phase(str, Enum):
    VOLUME_PLANNING = "volume_planning"
    CONTEXT_PREPARATION = "context_preparation"
    DRAFTING = "drafting"
    REVIEWING = "reviewing"
    EDITING = "editing"
    FAST_REVIEWING = "fast_reviewing"
    LIBRARIAN = "librarian"
    COMPLETED = "completed"


VALID_TRANSITIONS = {
    Phase.VOLUME_PLANNING: [Phase.CONTEXT_PREPARATION],
    Phase.CONTEXT_PREPARATION: [Phase.DRAFTING],
    Phase.DRAFTING: [Phase.REVIEWING],
    Phase.REVIEWING: [Phase.EDITING, Phase.DRAFTING],
    Phase.EDITING: [Phase.FAST_REVIEWING],
    Phase.FAST_REVIEWING: [Phase.LIBRARIAN, Phase.DRAFTING, Phase.EDITING],
    Phase.LIBRARIAN: [Phase.COMPLETED],
    Phase.COMPLETED: [Phase.CONTEXT_PREPARATION, Phase.VOLUME_PLANNING],
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

    async def advance(self, novel_id: str) -> NovelState:
        state = await self.resume(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")
        current = Phase(state.current_phase)

        if current == Phase.REVIEWING:
            return await self._run_critic(state)
        elif current == Phase.EDITING:
            return await self._run_editor(state)
        elif current == Phase.FAST_REVIEWING:
            return await self._run_fast_review(state)
        elif current == Phase.LIBRARIAN:
            return await self._run_librarian(state)
        else:
            raise ValueError(f"Cannot auto-advance from {current}")

    async def _run_critic(self, state: NovelState) -> NovelState:
        from novel_dev.agents.critic_agent import CriticAgent
        agent = CriticAgent(self.session)
        await agent.review(state.novel_id, state.current_chapter_id)
        return await self.resume(state.novel_id)

    async def _run_editor(self, state: NovelState) -> NovelState:
        from novel_dev.agents.editor_agent import EditorAgent
        agent = EditorAgent(self.session)
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
        from novel_dev.config import Settings
        from novel_dev.repositories.chapter_repo import ChapterRepository

        chapter_id = state.current_chapter_id
        if not chapter_id:
            raise ValueError("No current chapter set for LIBRARIAN phase")

        ch = await ChapterRepository(self.session).get_by_id(chapter_id)
        if not ch or not ch.polished_text:
            raise ValueError("Chapter polished text missing")

        agent = LibrarianAgent(self.session)
        try:
            extraction = await agent.extract(state.novel_id, chapter_id, ch.polished_text)
        except Exception as llm_error:
            try:
                extraction = agent.fallback_extract(ch.polished_text, state.checkpoint_data)
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
                raise RuntimeError(
                    f"Librarian extraction failed: LLM={llm_error}, fallback={fallback_error}"
                )

        await agent.persist(extraction, chapter_id)

        settings = Settings()
        archive_svc = ArchiveService(self.session, settings.markdown_output_dir)
        await archive_svc.archive(state.novel_id, chapter_id)

        checkpoint = dict(state.checkpoint_data)
        checkpoint["last_archived_chapter_id"] = chapter_id
        await self.save_checkpoint(
            state.novel_id,
            Phase.COMPLETED,
            checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=chapter_id,
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
                checkpoint["current_chapter_plan"] = next_plan
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

        return await self.save_checkpoint(
            novel_id,
            Phase.VOLUME_PLANNING,
            checkpoint,
            volume_id=next_volume_id,
            chapter_id=placeholder_volume["chapters"][0]["chapter_id"],
        )
