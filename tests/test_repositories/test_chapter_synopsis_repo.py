import pytest
from novel_dev.repositories.chapter_synopsis_repo import ChapterSynopsisRepository


@pytest.mark.asyncio
async def test_create_and_get_latest(async_session):
    repo = ChapterSynopsisRepository(async_session)
    syn = await repo.create(
        novel_id="n_1", chapter_range_start=1, chapter_range_end=5,
        narrative_prose="...", structured_json={"plot_points": []},
        trigger_event={"type": "block", "chapter_id": "ch_5"},
    )
    latest = await repo.get_latest("n_1")
    assert latest.id == syn.id
    assert latest.chapter_range_end == 5


@pytest.mark.asyncio
async def test_list_all_returns_all_in_ascending_range_order(async_session):
    """list_all must return every snapshot for the novel ordered by start chapter."""
    repo = ChapterSynopsisRepository(async_session)
    await repo.create(
        "n_1", 6, 10, "second", {"plot_points": []},
        {"type": "block", "chapter_id": "ch_10"},
    )
    await repo.create(
        "n_1", 1, 5, "first", {"plot_points": []},
        {"type": "block", "chapter_id": "ch_5"},
    )
    await repo.create(
        "n_1", 11, 15, "third", {"plot_points": []},
        {"type": "block", "chapter_id": "ch_15"},
    )

    syns = await repo.list_all("n_1")
    assert [s.chapter_range_start for s in syns] == [1, 6, 11]
    assert syns[0].narrative_prose == "first"
    assert syns[-1].narrative_prose == "third"


@pytest.mark.asyncio
async def test_list_all_returns_empty_when_no_snapshots(async_session):
    """list_all must return [] (not raise) for a novel with no snapshots."""
    repo = ChapterSynopsisRepository(async_session)
    assert await repo.list_all("n_unknown") == []


@pytest.mark.asyncio
async def test_get_latest_returns_none_when_no_snapshots(async_session):
    """get_latest must return None (not raise) when the novel has no snapshots."""
    repo = ChapterSynopsisRepository(async_session)
    assert await repo.get_latest("n_unknown") is None
