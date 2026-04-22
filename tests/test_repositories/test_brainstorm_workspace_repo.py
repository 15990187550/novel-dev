from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select

from novel_dev.db.engine import async_session_maker
from novel_dev.db.models import BrainstormWorkspace
import novel_dev.repositories.brainstorm_workspace_repo as brainstorm_workspace_repo
from novel_dev.repositories.brainstorm_workspace_repo import BrainstormWorkspaceRepository


@pytest.mark.asyncio
async def test_brainstorm_workspace_get_or_create_reuses_active_workspace(async_session):
    repo = BrainstormWorkspaceRepository(async_session)

    first = await repo.get_or_create("novel_ws")
    second = await repo.get_or_create("novel_ws")

    assert first.id == second.id
    assert first.status == "active"
    assert first.outline_drafts == {}
    assert first.setting_docs_draft == []


@pytest.mark.asyncio
async def test_brainstorm_workspace_mark_submitted_clears_active_lookup(async_session):
    repo = BrainstormWorkspaceRepository(async_session)

    workspace = await repo.get_or_create("novel_ws")
    submitted = await repo.mark_submitted(workspace.id)

    assert submitted.id == workspace.id
    assert submitted.status == "submitted"
    assert submitted.submitted_at is not None
    assert await repo.get_active_by_novel("novel_ws") is None


@pytest.mark.asyncio
async def test_brainstorm_workspace_mark_submitted_preserves_existing_timestamp(async_session, monkeypatch):
    repo = BrainstormWorkspaceRepository(async_session)

    timestamps = iter(
        [
            datetime(2026, 4, 21, 10, 0, 0),
            datetime(2026, 4, 21, 10, 0, 5),
            datetime(2026, 4, 21, 10, 0, 10),
        ]
    )

    class FakeDatetime:
        @classmethod
        def utcnow(cls):
            return next(timestamps)

    monkeypatch.setattr(brainstorm_workspace_repo, "datetime", FakeDatetime)

    workspace = await repo.get_or_create("novel_submit")
    first_submit = await repo.mark_submitted(workspace.id)
    second_submit = await repo.mark_submitted(workspace.id)

    assert first_submit.submitted_at == datetime(2026, 4, 21, 10, 0, 5)
    assert second_submit.submitted_at == first_submit.submitted_at
    assert second_submit.status == "submitted"


@pytest.mark.asyncio
async def test_brainstorm_workspace_get_active_ignores_dirty_submitted_identity(async_session):
    repo = BrainstormWorkspaceRepository(async_session)

    workspace = await repo.get_or_create("novel_dirty")
    workspace.status = "submitted"

    assert await repo.get_active_by_novel("novel_dirty") is None

    replacement = await repo.get_or_create("novel_dirty")
    assert replacement.id != workspace.id
    assert replacement.status == "active"


@pytest.mark.asyncio
async def test_brainstorm_workspace_get_or_create_recovers_from_unique_conflict(async_session, monkeypatch):
    repo = BrainstormWorkspaceRepository(async_session)
    conflict_key = {"novel_id": "novel_conflict"}
    inserted_workspace = None
    original_flush = async_session.flush
    conflict_injected = False

    async def flush_with_conflict(*args, **kwargs):
        nonlocal conflict_injected, inserted_workspace
        if not conflict_injected:
            conflict_injected = True
            async with async_session_maker() as competing_session:
                competing_repo = BrainstormWorkspaceRepository(competing_session)
                inserted_workspace = await competing_repo.get_or_create(**conflict_key)
                await competing_session.commit()
            raise IntegrityError(
                "INSERT INTO brainstorm_workspaces",
                None,
                Exception("simulated unique constraint conflict"),
            )
        return await original_flush(*args, **kwargs)

    monkeypatch.setattr(async_session, "flush", flush_with_conflict)

    workspace = await repo.get_or_create(**conflict_key)

    assert inserted_workspace is not None
    assert workspace.id == inserted_workspace.id
    assert workspace.novel_id == conflict_key["novel_id"]
    assert workspace.status == "active"
    assert await repo.get_active_by_novel(conflict_key["novel_id"]) is workspace


@pytest.mark.asyncio
async def test_brainstorm_workspace_supports_repeated_submit_cycles():
    async with async_session_maker() as session1:
        repo1 = BrainstormWorkspaceRepository(session1)
        first = await repo1.get_or_create("novel_cycle")
        await repo1.mark_submitted(first.id)
        await session1.commit()

    async with async_session_maker() as session2:
        repo2 = BrainstormWorkspaceRepository(session2)
        second = await repo2.get_or_create("novel_cycle")
        await repo2.mark_submitted(second.id)
        await session2.commit()

        submitted_rows = await session2.execute(
            select(func.count()).select_from(BrainstormWorkspace).where(
                BrainstormWorkspace.novel_id == "novel_cycle",
                BrainstormWorkspace.status == "submitted",
            )
        )

        assert submitted_rows.scalar_one() == 2
