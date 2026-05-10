import shutil

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import (
    AgentLog,
    BrainstormWorkspace,
    Chapter,
    Entity,
    EntityGroup,
    EntityRelationship,
    EntityVersion,
    Foreshadowing,
    KnowledgeDomain,
    KnowledgeDomainUsage,
    NovelDocument,
    NovelState,
    OutlineMessage,
    OutlineSession,
    PendingExtraction,
    SettingGenerationMessage,
    SettingGenerationSession,
    SettingReviewBatch,
    SettingReviewChange,
    Spaceline,
    Timeline,
)
from novel_dev.storage.paths import StoragePaths


class NovelDeletionService:
    def __init__(self, session: AsyncSession, data_dir: str):
        self.session = session
        self.storage_paths = StoragePaths(data_dir)

    async def delete_novel(self, novel_id: str) -> bool:
        state = await self.session.get(NovelState, novel_id)
        if state is None:
            return False

        entity_ids = select(Entity.id).where(Entity.novel_id == novel_id)
        outline_session_ids = select(OutlineSession.id).where(OutlineSession.novel_id == novel_id)
        setting_session_ids = select(SettingGenerationSession.id).where(
            SettingGenerationSession.novel_id == novel_id
        )
        setting_review_batch_ids = select(SettingReviewBatch.id).where(
            SettingReviewBatch.novel_id == novel_id
        )

        await self.session.execute(
            delete(EntityVersion).where(EntityVersion.entity_id.in_(entity_ids))
        )
        await self.session.execute(
            delete(OutlineMessage).where(OutlineMessage.session_id.in_(outline_session_ids))
        )
        await self.session.execute(
            delete(SettingReviewChange).where(SettingReviewChange.batch_id.in_(setting_review_batch_ids))
        )
        await self.session.execute(
            delete(SettingReviewBatch).where(SettingReviewBatch.novel_id == novel_id)
        )
        await self.session.execute(
            delete(SettingGenerationMessage).where(SettingGenerationMessage.session_id.in_(setting_session_ids))
        )
        await self.session.execute(
            delete(SettingGenerationSession).where(SettingGenerationSession.novel_id == novel_id)
        )
        await self.session.execute(
            delete(EntityRelationship).where(EntityRelationship.novel_id == novel_id)
        )
        await self.session.execute(delete(Timeline).where(Timeline.novel_id == novel_id))
        await self.session.execute(delete(Spaceline).where(Spaceline.novel_id == novel_id))
        await self.session.execute(delete(Foreshadowing).where(Foreshadowing.novel_id == novel_id))
        await self.session.execute(delete(Chapter).where(Chapter.novel_id == novel_id))
        await self.session.execute(delete(NovelDocument).where(NovelDocument.novel_id == novel_id))
        await self.session.execute(delete(KnowledgeDomainUsage).where(KnowledgeDomainUsage.novel_id == novel_id))
        await self.session.execute(delete(KnowledgeDomain).where(KnowledgeDomain.novel_id == novel_id))
        await self.session.execute(
            delete(OutlineSession).where(OutlineSession.novel_id == novel_id)
        )
        await self.session.execute(
            delete(BrainstormWorkspace).where(BrainstormWorkspace.novel_id == novel_id)
        )
        await self.session.execute(
            delete(PendingExtraction).where(PendingExtraction.novel_id == novel_id)
        )
        await self.session.execute(delete(AgentLog).where(AgentLog.novel_id == novel_id))
        await self.session.execute(delete(Entity).where(Entity.novel_id == novel_id))
        await self.session.execute(delete(EntityGroup).where(EntityGroup.novel_id == novel_id))
        await self.session.execute(delete(NovelState).where(NovelState.novel_id == novel_id))
        await self.session.commit()
        shutil.rmtree(self.storage_paths.novel_dir(novel_id), ignore_errors=True)
        return True
