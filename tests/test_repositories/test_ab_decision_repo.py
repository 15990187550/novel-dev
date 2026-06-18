import pytest
from datetime import datetime
from novel_dev.repositories.ab_decision_repo import ABDecisionRepository


@pytest.mark.asyncio
async def test_create_and_query_recent(async_session):
    repo = ABDecisionRepository(async_session)
    for i in range(3):
        await repo.create(
            experiment_id="exp_1", action="evaluate",
            scores={"v1": 75.0 + i}, meta={"i": i},
        )
    recent = await repo.list_recent(window_minutes=60)
    assert len(recent) == 3
    assert all(d.experiment_id == "exp_1" for d in recent)


@pytest.mark.asyncio
async def test_list_by_experiment(async_session):
    repo = ABDecisionRepository(async_session)
    await repo.create(experiment_id="exp_1", action="accept", scores={"v2": 80.0})
    await repo.create(experiment_id="exp_2", action="timeout", scores={"v1": 70.0})
    exp1 = await repo.list_by_experiment("exp_1")
    assert len(exp1) == 1
    assert exp1[0].action == "accept"
