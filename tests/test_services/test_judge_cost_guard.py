import pytest
from unittest.mock import AsyncMock
from dataclasses import dataclass
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.services.judge_cost_guard import JudgeCostGuard, CostCheckResult


@pytest.mark.asyncio
async def test_disabled_judge_returns_disallow():
    config = JudgeConfig(enabled=False)
    guard = JudgeCostGuard(config, call_log_repo=AsyncMock())
    result = await guard.check_can_call("exp_1")
    assert result.allow is False
    assert result.reason == "judge_disabled"


@pytest.mark.asyncio
async def test_experiment_cost_under_cap_allows():
    config = JudgeConfig(enabled=True, max_cost_per_experiment_usd=0.50)
    mock_repo = AsyncMock()
    mock_repo.sum_cost_for_experiment = AsyncMock(return_value=0.10)
    guard = JudgeCostGuard(config, call_log_repo=mock_repo)
    result = await guard.check_can_call("exp_1")
    assert result.allow is True


@pytest.mark.asyncio
async def test_experiment_cost_over_cap_denies():
    config = JudgeConfig(enabled=True, max_cost_per_experiment_usd=0.50)
    mock_repo = AsyncMock()
    mock_repo.sum_cost_for_experiment = AsyncMock(return_value=0.51)
    guard = JudgeCostGuard(config, call_log_repo=mock_repo)
    result = await guard.check_can_call("exp_1")
    assert result.allow is False
    assert result.reason == "experiment_cost_cap"
    assert result.current == 0.51


@pytest.mark.asyncio
async def test_boundary_equal_to_cap_denies():
    config = JudgeConfig(enabled=True, max_cost_per_experiment_usd=0.50)
    mock_repo = AsyncMock()
    mock_repo.sum_cost_for_experiment = AsyncMock(return_value=0.50)
    guard = JudgeCostGuard(config, call_log_repo=mock_repo)
    result = await guard.check_can_call("exp_1")
    assert result.allow is False  # 严格 ≥ 拒绝


@pytest.mark.asyncio
async def test_single_call_cost_estimate_over_decision_cap():
    config = JudgeConfig(enabled=True, max_cost_per_decision_usd=0.05)
    guard = JudgeCostGuard(config, call_log_repo=AsyncMock())
    # 假设这次调用 input=20000, output=1000 → 估算成本 $0.075(超过 $0.05 上限)
    cost = guard.estimate_call_cost(input_tokens=20000, output_tokens=1000)
    assert cost > 0.05
    allow = guard.allow_single_call(input_tokens=20000, output_tokens=1000)
    assert allow is False
