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
