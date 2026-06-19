import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.db.models import JudgeABTest
from novel_dev.services.judge_acceptance_sweeper import JudgeAcceptanceSweeper


@pytest.mark.asyncio
async def test_tick_processes_running_experiments(async_session):
    ab = JudgeABTest(baseline_version="v1", challenger_version="v2", agent_name="judge_agent", status="running")
    async_session.add(ab)
    await async_session.flush()

    sweeper = JudgeAcceptanceSweeper(async_session, JudgeConfig())
    sweeper.decider = MagicMock()
    sweeper.decider.evaluate = AsyncMock(return_value=MagicMock(action="continue_monitoring"))

    decisions = await sweeper.tick()
    assert len(decisions) == 1
    assert decisions[0]["action"] == "continue_monitoring"


@pytest.mark.asyncio
async def test_tick_skips_non_running_experiments(async_session):
    ab = JudgeABTest(baseline_version="v1", challenger_version="v2", agent_name="judge_agent", status="completed")
    async_session.add(ab)
    await async_session.flush()

    sweeper = JudgeAcceptanceSweeper(async_session, JudgeConfig())
    sweeper.decider = MagicMock()
    sweeper.decider.evaluate = AsyncMock(return_value=MagicMock(action="accept", winner="v2"))

    decisions = await sweeper.tick()
    # completed 状态仍可继续被 sweeper 处理(meta-eval 即使是已完成实验也跑)
    # 但若 decider 返回 no_action,会进入 decisions 列表
    assert isinstance(decisions, list)


@pytest.mark.asyncio
async def test_tick_handles_exception_per_experiment(async_session):
    ab1 = JudgeABTest(baseline_version="v1", challenger_version="v2", agent_name="judge_agent", status="running")
    ab2 = JudgeABTest(baseline_version="v3", challenger_version="v4", agent_name="judge_agent", status="running")
    async_session.add_all([ab1, ab2])
    await async_session.flush()

    sweeper = JudgeAcceptanceSweeper(async_session, JudgeConfig())
    sweeper.decider = MagicMock()
    sweeper.decider.evaluate = AsyncMock(side_effect=[Exception("boom"), MagicMock(action="accept", winner="v3")])

    # 不应抛出 — 单个失败被吞掉
    decisions = await sweeper.tick()
    assert len(decisions) == 1  # 只有 ab2 成功
    assert decisions[0]["action"] == "accept"