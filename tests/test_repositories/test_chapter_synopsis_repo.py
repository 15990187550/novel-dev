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
