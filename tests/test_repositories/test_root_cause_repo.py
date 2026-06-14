import pytest
from novel_dev.repositories.root_cause_repo import RootCauseRepository


@pytest.mark.asyncio
async def test_persist_and_get_latest(async_session):
    repo = RootCauseRepository(async_session)
    rc = await repo.persist(
        chapter_id="ch_1",
        analyzer_version="v1.0",
        summary="beat 越界",
        suggested_actions=[{"action": "重写 beat 2", "target": "beat:2", "severity": "high"}],
        confidence=0.85,
        input_snapshot={"chapter_preview": "..."},
    )
    latest = await repo.get_latest_for_chapter("ch_1")
    assert latest.id == rc.id
    assert latest.summary == "beat 越界"
    assert latest.suggested_actions["items"][0]["severity"] == "high"


@pytest.mark.asyncio
async def test_get_latest_returns_newest(async_session):
    repo = RootCauseRepository(async_session)
    await repo.persist("ch_1", "v1.0", "first", [], 0.5, {})
    await repo.persist("ch_1", "v1.0", "second", [], 0.7, {})
    latest = await repo.get_latest_for_chapter("ch_1")
    assert latest.summary == "second"


@pytest.mark.asyncio
async def test_get_latest_empty_returns_none(async_session):
    repo = RootCauseRepository(async_session)
    assert await repo.get_latest_for_chapter("nonexistent") is None
