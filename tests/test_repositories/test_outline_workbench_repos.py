from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from novel_dev.db.engine import async_session_maker
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
async def test_outline_session_get_or_create_ignores_deleted_cached_session(async_session):
    repo = OutlineSessionRepository(async_session)

    existing = await repo.get_or_create(
        novel_id="novel_del",
        outline_type="volume",
        outline_ref="vol_del",
    )
    await async_session.flush()
    await async_session.delete(existing)

    replacement = await repo.get_or_create(
        novel_id="novel_del",
        outline_type="volume",
        outline_ref="vol_del",
    )

    assert replacement.id != existing.id
    assert replacement not in async_session.deleted


@pytest.mark.asyncio
async def test_outline_session_get_or_create_recovers_from_unique_conflict(async_session, monkeypatch):
    repo = OutlineSessionRepository(async_session)
    conflict_key = {
        "novel_id": "novel_2",
        "outline_type": "volume",
        "outline_ref": "vol_2",
    }
    inserted_session = None
    original_flush = async_session.flush
    conflict_injected = False

    async def flush_with_conflict(*args, **kwargs):
        nonlocal conflict_injected, inserted_session
        if not conflict_injected:
            conflict_injected = True
            async with async_session_maker() as competing_session:
                competing_repo = OutlineSessionRepository(competing_session)
                inserted_session = await competing_repo.get_or_create(**conflict_key)
                await competing_session.commit()
            raise IntegrityError(
                "INSERT INTO outline_sessions",
                None,
                Exception("simulated unique constraint conflict"),
            )
        return await original_flush(*args, **kwargs)

    monkeypatch.setattr(async_session, "flush", flush_with_conflict)

    session = await repo.get_or_create(**conflict_key)

    assert inserted_session is not None
    assert session.id == inserted_session.id
    assert session.novel_id == conflict_key["novel_id"]
    assert session.outline_type == conflict_key["outline_type"]
    assert session.outline_ref == conflict_key["outline_ref"]
    followup = await repo.get_or_create(
        novel_id="novel_2",
        outline_type="chapter",
        outline_ref="ch_followup",
    )
    await async_session.commit()
    assert followup.novel_id == "novel_2"
    assert followup.outline_ref == "ch_followup"


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
