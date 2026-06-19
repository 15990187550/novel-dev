import pytest
from datetime import datetime
from novel_dev.db.models import JudgeCallLog
from novel_dev.repositories.judge_call_log_repo import JudgeCallLogRepository


@pytest.mark.asyncio
async def test_log_persists_call_metadata(async_session):
    repo = JudgeCallLogRepository(async_session)
    log = await repo.log(
        decision_id="dec_1",
        experiment_id="exp_1",
        prompt_version_id="pv_1",
        model="claude-sonnet-4-6",
        input_tokens=1500,
        output_tokens=80,
        latency_ms=2300,
        cost_usd=0.0042,
    )
    fetched = await async_session.get(JudgeCallLog, log.id)
    assert fetched.model == "claude-sonnet-4-6"
    assert fetched.cost_usd == 0.0042


@pytest.mark.asyncio
async def test_sum_cost_for_experiment_aggregates(async_session):
    repo = JudgeCallLogRepository(async_session)
    await repo.log(decision_id="d1", experiment_id="exp_1", prompt_version_id="p", model="m",
                   input_tokens=100, output_tokens=10, latency_ms=100, cost_usd=0.01)
    await repo.log(decision_id="d2", experiment_id="exp_1", prompt_version_id="p", model="m",
                   input_tokens=200, output_tokens=20, latency_ms=200, cost_usd=0.02)
    await repo.log(decision_id="d3", experiment_id="exp_2", prompt_version_id="p", model="m",
                   input_tokens=50, output_tokens=5, latency_ms=50, cost_usd=0.005)
    total = await repo.sum_cost_for_experiment("exp_1")
    assert abs(total - 0.03) < 1e-6


@pytest.mark.asyncio
async def test_count_calls_for_experiment_in_window(async_session):
    repo = JudgeCallLogRepository(async_session)
    for i in range(3):
        await repo.log(decision_id=f"d{i}", experiment_id="exp_1", prompt_version_id="p", model="m",
                       input_tokens=100, output_tokens=10, latency_ms=100, cost_usd=0.01)
    count = await repo.count_calls_for_experiment("exp_1", since=datetime(2020, 1, 1))
    assert count == 3