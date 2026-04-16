import pytest

from novel_dev.repositories.spaceline_repo import SpacelineRepository


@pytest.mark.asyncio
async def test_spaceline_repo_get_by_id(async_session):
    repo = SpacelineRepository(async_session)
    await repo.create("loc_1", "Qingyun City")
    result = await repo.get_by_id("loc_1")
    assert result is not None
    assert result.name == "Qingyun City"
    assert await repo.get_by_id("nonexistent") is None
