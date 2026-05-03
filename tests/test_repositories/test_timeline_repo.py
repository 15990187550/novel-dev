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
async def test_get_current_tick_returns_latest_when_novel_has_multiple_events(async_session):
    repo = TimelineRepository(async_session)
    await repo.create(tick=1, narrative="event 1", novel_id="n_multi_tick")
    await repo.create(tick=3, narrative="event 3", novel_id="n_multi_tick")

    latest = await repo.get_current_tick(novel_id="n_multi_tick")

    assert latest == 3


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


@pytest.mark.asyncio
async def test_create_timeline_with_novel_id(async_session):
    repo = TimelineRepository(async_session)
    entry = await repo.create(tick=1, narrative="Year 384", novel_id="n1")
    assert entry.tick == 1
    assert entry.novel_id == "n1"


@pytest.mark.asyncio
async def test_list_timelines_by_novel(async_session):
    repo = TimelineRepository(async_session)
    await repo.create(tick=5, narrative="event 5", novel_id="n1")
    await repo.create(tick=1, narrative="event 1", novel_id="n1")
    await repo.create(tick=3, narrative="event 3", novel_id="n2")
    results = await repo.list_by_novel("n1")
    assert len(results) == 2
    assert [e.tick for e in results] == [1, 5]
    assert [e.novel_id for e in results] == ["n1", "n1"]


@pytest.mark.asyncio
async def test_list_between(async_session):
    repo = TimelineRepository(async_session)
    await repo.create(tick=1, narrative="事件1", novel_id="n_test")
    await repo.create(tick=3, narrative="事件3", novel_id="n_test")
    await repo.create(tick=5, narrative="事件5", novel_id="n_test")

    result = await repo.list_between(2, 4, novel_id="n_test")
    assert len(result) == 1
    assert result[0].tick == 3
    assert result[0].narrative == "事件3"
