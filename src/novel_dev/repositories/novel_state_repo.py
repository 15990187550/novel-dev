from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import NovelState


class NovelStateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_state(self, novel_id: str) -> Optional[NovelState]:
        result = await self.session.execute(select(NovelState).where(NovelState.novel_id == novel_id))
        return result.scalar_one_or_none()

    async def save_checkpoint(
        self,
        novel_id: str,
        current_phase: str,
        checkpoint_data: dict,
        current_volume_id: Optional[str] = None,
        current_chapter_id: Optional[str] = None,
    ) -> NovelState:
        state = await self.get_state(novel_id)
        if state is None:
            state = NovelState(
                novel_id=novel_id,
                current_phase=current_phase,
                current_volume_id=current_volume_id,
                current_chapter_id=current_chapter_id,
                checkpoint_data=checkpoint_data,
            )
            self.session.add(state)
        else:
            state.current_phase = current_phase
            state.current_volume_id = current_volume_id
            state.current_chapter_id = current_chapter_id
            state.checkpoint_data = checkpoint_data
        await self.session.flush()
        return state
