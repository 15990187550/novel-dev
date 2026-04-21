from datetime import datetime

import pytest

from novel_dev.repositories.outline_message_repo import OutlineMessageRepository
from novel_dev.repositories.outline_session_repo import OutlineSessionRepository


@pytest.mark.asyncio
async def test_outline_session_get_or_create_reuses_existing_session(async_session):
    repo = OutlineSessionRepository(async_session)

    first = await repo.get_or_create(
        novel_id="novel_1",
        outline_type="volume",
        outline_ref="vol_1",
    )
    second = await repo.get_or_create(
        novel_id="novel_1",
        outline_type="volume",
        outline_ref="vol_1",
    )

    assert first.id == second.id
    assert first.novel_id == "novel_1"
    assert first.outline_type == "volume"
    assert first.outline_ref == "vol_1"


@pytest.mark.asyncio
async def test_outline_message_create_and_list_recent_orders_by_created_at(async_session):
    session_repo = OutlineSessionRepository(async_session)
    message_repo = OutlineMessageRepository(async_session)

    outline_session = await session_repo.get_or_create(
        novel_id="novel_1",
        outline_type="chapter",
        outline_ref="ch_1",
    )

    older = await message_repo.create(
        session_id=outline_session.id,
        role="assistant",
        message_type="summary",
        content="older",
        meta={"step": 1},
    )
    newer = await message_repo.create(
        session_id=outline_session.id,
        role="user",
        message_type="request",
        content="newer",
        meta={"step": 2},
    )

    older.created_at = datetime(2026, 4, 21, 10, 0, 0)
    newer.created_at = datetime(2026, 4, 21, 11, 0, 0)
    await async_session.flush()

    recent = await message_repo.list_recent(outline_session.id, limit=10)

    assert [message.id for message in recent] == [newer.id, older.id]
    assert recent[0].content == "newer"
    assert recent[1].content == "older"
