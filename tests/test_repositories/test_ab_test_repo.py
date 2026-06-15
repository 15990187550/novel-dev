import pytest
from datetime import datetime
from novel_dev.repositories.ab_test_repo import ABTestRepository


@pytest.mark.asyncio
async def test_create_and_get(async_session):
    repo = ABTestRepository(async_session)
    ab = await repo.create(
        agent_name="critic",
        baseline_version="v1.0",
        challenger_version="v2.0",
        config={"max_samples": 10, "min_samples": 3, "alpha": 0.05},
    )
    found = await repo.get(ab.id)
    assert found.agent_name == "critic"
    assert found.status == "running"


@pytest.mark.asyncio
async def test_list_running(async_session):
    repo = ABTestRepository(async_session)
    await repo.create("critic", "v1.0", "v2.0", {})
    await repo.create("writer", "v1.0", "v2.0", {})
    running = await repo.list_running()
    assert len(running) == 2


@pytest.mark.asyncio
async def test_mark_completed(async_session):
    repo = ABTestRepository(async_session)
    ab = await repo.create("critic", "v1.0", "v2.0", {})
    await repo.mark_completed(ab.id, winner="challenger", ended_at=datetime.utcnow())
    found = await repo.get(ab.id)
    assert found.status == "completed"
    assert found.winner == "challenger"
    assert found.ended_at is not None


@pytest.mark.asyncio
async def test_list_all(async_session):
    repo = ABTestRepository(async_session)
    await repo.create("critic", "v1.0", "v2.0", {})
    await repo.create("writer", "v1.0", "v2.0", {})
    all_tests = await repo.list_all()
    assert len(all_tests) == 2


@pytest.mark.asyncio
async def test_mark_completed_noop_when_missing(async_session):
    repo = ABTestRepository(async_session)
    # Should not raise
    await repo.mark_completed("nonexistent", winner="challenger", ended_at=datetime.utcnow())


@pytest.mark.asyncio
async def test_mark_aborted(async_session):
    repo = ABTestRepository(async_session)
    ab = await repo.create("critic", "v1.0", "v2.0", {})
    await repo.mark_aborted(ab.id)
    found = await repo.get(ab.id)
    assert found.status == "aborted"
    assert found.ended_at is not None


@pytest.mark.asyncio
async def test_mark_aborted_noop_when_missing(async_session):
    repo = ABTestRepository(async_session)
    # Should not raise
    await repo.mark_aborted("nonexistent")
