import pytest

from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository


@pytest.mark.asyncio
async def test_timeline_crud(async_session):
    repo = TimelineRepository(async_session)
    entry = await repo.create(tick=1, narrative="Year 384", anchor_chapter_id="ch_001")
    assert entry.tick == 1
    latest = await repo.get_current_tick()
    assert latest == 1


@pytest.mark.asyncio
async def test_spaceline_chain(async_session):
    repo = SpacelineRepository(async_session)
    await repo.create("continent_1", "Tianxuan", parent_id=None)
    await repo.create("region_1", "East Wasteland", parent_id="continent_1")
    chain = await repo.get_chain("region_1")
    assert [node.id for node in chain] == ["continent_1", "region_1"]


@pytest.mark.asyncio
async def test_get_around_tick(async_session):
    repo = TimelineRepository(async_session)
    await repo.create(10, "event 10")
    await repo.create(15, "event 15")
    await repo.create(20, "event 20")
    await repo.create(25, "event 25")
    events = await repo.get_around_tick(18, radius=2)
    assert len(events) == 4
    assert [e.tick for e in events] == [10, 15, 20, 25]
