import pytest

from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository


@pytest.mark.asyncio
async def test_chapter_crud(async_session):
    repo = ChapterRepository(async_session)
    ch = await repo.create("ch_001", "vol_1", 1, title="Prologue")
    assert ch.status == "pending"
    await repo.update_text("ch_001", raw_draft="draft text", polished_text="final text")
    updated = await repo.get_by_id("ch_001")
    assert updated.polished_text == "final text"


@pytest.mark.asyncio
async def test_novel_state_checkpoint(async_session):
    repo = NovelStateRepository(async_session)
    await repo.save_checkpoint(
        "novel_1",
        current_phase="writing_chapter_1_draft",
        checkpoint_data={"retry_count": 0},
        current_volume_id="vol_1",
        current_chapter_id="ch_1",
    )
    state = await repo.get_state("novel_1")
    assert state.current_phase == "writing_chapter_1_draft"


@pytest.mark.asyncio
async def test_get_previous_chapter(async_session):
    repo = ChapterRepository(async_session)
    await repo.create("c1", "v1", 1, "First")
    await repo.create("c2", "v1", 2, "Second")
    prev = await repo.get_previous_chapter("v1", 2)
    assert prev is not None
    assert prev.chapter_number == 1
