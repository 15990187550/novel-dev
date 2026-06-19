import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.db.models import JudgePromptVersion, JudgeABTest
from novel_dev.services.judge_acceptance_decider import JudgeAcceptanceDecider, JudgeDeciderResult


@pytest.mark.asyncio
async def test_accepts_challenger_when_agreement_high(async_session):
    jpv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    jpv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=False, ab_test_id="ab_judge_1")
    ab = JudgeABTest(id="ab_judge_1", agent_name="judge_agent", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([jpv1, jpv2, ab])
    await async_session.flush()

    decider = JudgeAcceptanceDecider(async_session, JudgeConfig())
    decider.meta_evaluator = MagicMock()
    decider.meta_evaluator.evaluate = AsyncMock(return_value=MagicMock(sample_size=50, agreement_rate=0.85, insufficient_data=False))

    result = await decider.evaluate(experiment_id="ab_judge_1")
    assert result.action == "accept"
    assert result.winner == "v2"


@pytest.mark.asyncio
async def test_continues_monitoring_when_agreement_middle(async_session):
    jpv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    jpv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=False, ab_test_id="ab_judge_1")
    ab = JudgeABTest(id="ab_judge_1", agent_name="judge_agent", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([jpv1, jpv2, ab])
    await async_session.flush()

    decider = JudgeAcceptanceDecider(async_session, JudgeConfig())
    decider.meta_evaluator = MagicMock()
    decider.meta_evaluator.evaluate = AsyncMock(return_value=MagicMock(sample_size=50, agreement_rate=0.65, insufficient_data=False))

    result = await decider.evaluate(experiment_id="ab_judge_1")
    assert result.action == "continue_monitoring"


@pytest.mark.asyncio
async def test_early_stops_when_agreement_low(async_session):
    jpv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    jpv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=False, ab_test_id="ab_judge_1")
    ab = JudgeABTest(id="ab_judge_1", agent_name="judge_agent", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([jpv1, jpv2, ab])
    await async_session.flush()

    decider = JudgeAcceptanceDecider(async_session, JudgeConfig())
    decider.meta_evaluator = MagicMock()
    decider.meta_evaluator.evaluate = AsyncMock(return_value=MagicMock(sample_size=50, agreement_rate=0.45, insufficient_data=False))

    result = await decider.evaluate(experiment_id="ab_judge_1")
    assert result.action == "early_stop"
    assert result.reason == "low_calibration"


@pytest.mark.asyncio
async def test_continues_when_insufficient_data(async_session):
    jpv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    jpv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=False, ab_test_id="ab_judge_1")
    ab = JudgeABTest(id="ab_judge_1", agent_name="judge_agent", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([jpv1, jpv2, ab])
    await async_session.flush()

    decider = JudgeAcceptanceDecider(async_session, JudgeConfig())
    decider.meta_evaluator = MagicMock()
    decider.meta_evaluator.evaluate = AsyncMock(return_value=MagicMock(sample_size=10, agreement_rate=None, insufficient_data=True))

    result = await decider.evaluate(experiment_id="ab_judge_1")
    assert result.action == "continue_monitoring"
    assert result.reason == "insufficient_data"


@pytest.mark.asyncio
async def test_skips_when_experiment_not_running(async_session):
    ab = JudgeABTest(id="ab_judge_1", agent_name="judge_agent", baseline_version="v1", challenger_version="v2", status="completed")
    async_session.add(ab)
    await async_session.flush()

    decider = JudgeAcceptanceDecider(async_session, JudgeConfig())
    result = await decider.evaluate(experiment_id="ab_judge_1")
    assert result.action == "no_action"
    assert result.reason == "experiment_not_running"
