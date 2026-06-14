import pytest
from sqlalchemy import select
from novel_dev.db.models import Chapter


@pytest.mark.asyncio
async def test_chapter_attempt_index_default(async_session):
    ch = Chapter(
        id="ch_attempt_test",
        volume_id="vol_1",
        chapter_number=1,
        status="pending",
        novel_id="novel_1",
    )
    async_session.add(ch)
    await async_session.flush()
    row = await async_session.execute(select(Chapter).where(Chapter.id == "ch_attempt_test"))
    found = row.scalar_one()
    assert found.attempt_index == 0
