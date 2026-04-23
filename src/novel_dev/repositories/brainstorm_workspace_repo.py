import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import BrainstormWorkspace


class BrainstormWorkspaceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _find_cached_active_workspace(self, novel_id: str) -> Optional[BrainstormWorkspace]:
        deleted_workspaces = set(self.session.deleted)
        for candidate in list(self.session.new) + list(self.session.identity_map.values()):
            if candidate in deleted_workspaces or inspect(candidate).deleted:
                continue
            if isinstance(candidate, BrainstormWorkspace) and candidate.novel_id == novel_id and candidate.status == "active":
                return candidate
        return None

    async def _query_active_workspace(self, novel_id: str) -> Optional[BrainstormWorkspace]:
        with self.session.no_autoflush:
            result = await self.session.execute(
                select(BrainstormWorkspace).where(
                    BrainstormWorkspace.novel_id == novel_id,
                    BrainstormWorkspace.status == "active",
                )
            )
        workspace = result.scalar_one_or_none()
        if workspace is None or workspace.status != "active":
            return None
        return workspace

    async def get_active_by_novel(self, novel_id: str) -> Optional[BrainstormWorkspace]:
        cached_workspace = self._find_cached_active_workspace(novel_id)
        if cached_workspace is not None:
            return cached_workspace

        return await self._query_active_workspace(novel_id)

    async def get_or_create(self, novel_id: str) -> BrainstormWorkspace:
        cached_workspace = self._find_cached_active_workspace(novel_id)
        if cached_workspace is not None:
            return cached_workspace

        existing_workspace = await self.get_active_by_novel(novel_id)
        if existing_workspace is not None:
            return existing_workspace

        workspace = BrainstormWorkspace(
            id=uuid.uuid4().hex,
            novel_id=novel_id,
            status="active",
            workspace_summary=None,
            outline_drafts={},
            setting_docs_draft=[],
            setting_suggestion_cards=[],
            last_saved_at=datetime.utcnow(),
            submitted_at=None,
        )

        try:
            async with self.session.begin_nested():
                self.session.add(workspace)
                await self.session.flush()
            return workspace
        except IntegrityError:
            existing_workspace = await self._query_active_workspace(novel_id)
            if existing_workspace is None:
                raise
            return existing_workspace

    async def get_by_id(self, workspace_id: str) -> Optional[BrainstormWorkspace]:
        result = await self.session.execute(
            select(BrainstormWorkspace).where(BrainstormWorkspace.id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def mark_submitted(self, workspace_id: str) -> Optional[BrainstormWorkspace]:
        workspace = await self.get_by_id(workspace_id)
        if workspace is None:
            return None

        workspace.status = "submitted"
        if workspace.submitted_at is None:
            workspace.submitted_at = datetime.utcnow()
        await self.session.flush()
        return workspace
