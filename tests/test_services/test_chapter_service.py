import pytest

from novel_dev.services.chapter_service import ChapterService


@pytest.mark.asyncio
async def test_create_and_complete_chapter(async_session):
    svc = ChapterService(async_session, "/tmp/test_output")
    ch = await svc.create("ch_1", "vol_1", 1, "Prologue")
    assert ch.status == "pending"

    await svc.complete_chapter("novel_1", "ch_1", "vol_1", "draft", "polished")
    updated = await svc.get("ch_1")
    assert updated.status == "completed"
    assert updated.polished_text == "polished"
