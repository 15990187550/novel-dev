import shutil
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import (
    BrainstormWorkspace,
    Chapter,
    Entity,
    EntityGroup,
    EntityRelationship,
    EntityVersion,
    Foreshadowing,
    NovelDocument,
    NovelState,
    OutlineMessage,
    OutlineSession,
    PendingExtraction,
    Spaceline,
    Timeline,
)


class NovelDeletionService:
    def __init__(self, session: AsyncSession, markdown_output_dir: str):
        self.session = session
        self.markdown_output_dir = Path(markdown_output_dir)

    async def delete_novel(self, novel_id: str) -> bool:
        state = await self.session.get(NovelState, novel_id)
        if state is None:
            return False

        entity_ids = select(Entity.id).where(Entity.novel_id == novel_id)
        outline_session_ids = select(OutlineSession.id).where(OutlineSession.novel_id == novel_id)

        await self.session.execute(
            delete(EntityVersion).where(EntityVersion.entity_id.in_(entity_ids))
        )
        await self.session.execute(
            delete(OutlineMessage).where(OutlineMessage.session_id.in_(outline_session_ids))
        )
        await self.session.execute(
            delete(EntityRelationship).where(EntityRelationship.novel_id == novel_id)
        )
        await self.session.execute(delete(Timeline).where(Timeline.novel_id == novel_id))
        await self.session.execute(delete(Spaceline).where(Spaceline.novel_id == novel_id))
        await self.session.execute(delete(Foreshadowing).where(Foreshadowing.novel_id == novel_id))
        await self.session.execute(delete(Chapter).where(Chapter.novel_id == novel_id))
        await self.session.execute(delete(NovelDocument).where(NovelDocument.novel_id == novel_id))
        await self.session.execute(
            delete(OutlineSession).where(OutlineSession.novel_id == novel_id)
        )
        await self.session.execute(
            delete(BrainstormWorkspace).where(BrainstormWorkspace.novel_id == novel_id)
        )
        await self.session.execute(
            delete(PendingExtraction).where(PendingExtraction.novel_id == novel_id)
        )
        await self.session.execute(delete(Entity).where(Entity.novel_id == novel_id))
        await self.session.execute(delete(EntityGroup).where(EntityGroup.novel_id == novel_id))
        await self.session.execute(delete(NovelState).where(NovelState.novel_id == novel_id))
        await self.session.commit()
        shutil.rmtree(self.markdown_output_dir / novel_id, ignore_errors=True)
        return True
