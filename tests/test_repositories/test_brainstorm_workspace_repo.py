import pytest

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
