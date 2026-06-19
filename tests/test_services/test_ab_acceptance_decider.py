import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from novel_dev.db.models import PromptVersion, ABTest
from novel_dev.services.ab_acceptance_decider import ABAcceptanceDecider


@pytest.mark.asyncio
async def test_accepts_challenger_when_significant(async_session):
    # Setup A/B test
    pv_baseline = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv_challenger = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([pv_baseline, pv_challenger, ab])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    # Inject deterministic significant test + score
    decider.significance_tester = MagicMock()
    decider.significance_tester.test = MagicMock(return_value=MagicMock(is_significant=True, p_value=0.03, effect_size=4.0, threshold_used="strict", reason=None))
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": 75.0, "v2": 80.0})

    result = await decider.evaluate(experiment_id="ab_1", sample_scores={
        "v1": {"critic_scores": [80.0]*50, "hook_achieved": [True]*50, "thrill_verified": [False]*50},
        "v2": {"critic_scores": [85.0]*50, "hook_achieved": [True]*50, "thrill_verified": [True]*50},
    })
    assert result.action == "accepted"
    assert result.winner == "v2"
    await async_session.refresh(pv_challenger)
    assert pv_challenger.experiment_state == "auto_accepted"
    assert pv_challenger.is_active is True


@pytest.mark.asyncio
async def test_no_action_when_samples_below_min(async_session):
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=5)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=5)
    async_session.add_all([pv1, pv2])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    result = await decider.evaluate(experiment_id="ab_1", sample_scores={
        "v1": {"critic_scores": [80.0], "hook_achieved": [True], "thrill_verified": [True]},
        "v2": {"critic_scores": [85.0], "hook_achieved": [True], "thrill_verified": [True]},
    })
    assert result.action == "no_action"


@pytest.mark.asyncio
async def test_returns_skipped_on_calculator_failure(async_session):
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=50)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=50)
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2", status="running")
    async_session.add_all([pv1, pv2, ab])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    decider.weighted_calc = MagicMock()
    decider.weighted_calc.compute_batch = MagicMock(return_value={"v1": None, "v2": None})
    result = await decider.evaluate(experiment_id="ab_1", sample_scores={
        "v1": {"critic_scores": [], "hook_achieved": [], "thrill_verified": []},
        "v2": {"critic_scores": [], "hook_achieved": [], "thrill_verified": []},
    })
    assert result.action == "skipped"
