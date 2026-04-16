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

        if current == Phase.VOLUME_PLANNING:
            return await self._run_volume_planner(state)
        if current == Phase.REVIEWING:
            return await self._run_critic(state)
        elif current == Phase.EDITING:
            return await self._run_editor(state)
        elif current == Phase.FAST_REVIEWING:
            return await self._run_fast_review(state)
        else:
            raise ValueError(f"Cannot auto-advance from {current}")

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
        agent = EditorAgent(self.session)
        await agent.polish(state.novel_id, state.current_chapter_id)
        return await self.resume(state.novel_id)

    async def _run_fast_review(self, state: NovelState) -> NovelState:
        from novel_dev.agents.fast_review_agent import FastReviewAgent
        agent = FastReviewAgent(self.session)
        await agent.review(state.novel_id, state.current_chapter_id)
        return await self.resume(state.novel_id)
