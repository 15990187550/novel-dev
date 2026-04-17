import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.spaceline_repo import SpacelineRepository


@pytest.mark.asyncio
async def test_spaceline_repo_get_by_id(async_session):
    repo = SpacelineRepository(async_session)
    await repo.create("loc_1", "Qingyun City")
    result = await repo.get_by_id("loc_1")
    assert result is not None
    assert result.name == "Qingyun City"
    assert await repo.get_by_id("nonexistent") is None


@pytest.mark.asyncio
async def test_create_spaceline_with_novel_id(async_session: AsyncSession):
    repo = SpacelineRepository(async_session)
    loc = await repo.create(location_id="loc_1", name="Qingyun", novel_id="n1")
    assert loc.novel_id == "n1"


@pytest.mark.asyncio
async def test_list_spacelines_by_novel(async_session: AsyncSession):
    repo = SpacelineRepository(async_session)
    await repo.create("loc_1", "A", novel_id="n1")
    await repo.create("loc_2", "B", novel_id="n2")
    await async_session.commit()

    items = await repo.list_by_novel("n1")
    assert len(items) == 1
    assert items[0].name == "A"
