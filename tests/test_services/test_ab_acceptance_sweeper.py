import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from novel_dev.db.models import PromptVersion, ABTest
from novel_dev.services.ab_acceptance_sweeper import ABAcceptanceSweeper


@pytest.mark.asyncio
async def test_early_stops_challenger_after_consecutive_loss(async_session):
    ab = ABTest(id="ab_1", agent_name="writer", baseline_version="v1", challenger_version="v2",
                status="running", started_at=datetime.utcnow() - timedelta(days=1),
                config={"early_stop_consecutive_loss": 3, "early_stop_min_lift": -0.10})
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_1", sample_count=30)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_1", sample_count=30, experiment_state="running")
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    # Mock weight calculator returning v2 much lower than v1
    sweeper = ABAcceptanceSweeper(async_session)
    sweeper.weighted_calc = MagicMock()
    sweeper.weighted_calc.compute_batch = MagicMock(return_value={"v1": 80.0, "v2": 65.0})
    sweeper._consecutive_loss_count = lambda ab_id: 3

    decisions = await sweeper.tick()
    assert any(d["action"] == "early_stop" for d in decisions)


@pytest.mark.asyncio
async def test_times_out_after_max_days_without_significance(async_session):
    ab = ABTest(id="ab_2", agent_name="writer", baseline_version="v1", challenger_version="v2",
                status="running", started_at=datetime.utcnow() - timedelta(days=8),
                config={"timeout_days": 7})
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_2", sample_count=100)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_2", sample_count=100)
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    sweeper.weighted_calc = MagicMock()
    sweeper.weighted_calc.compute_batch = MagicMock(return_value={"v1": 80.0, "v2": 80.5})

    decisions = await sweeper.tick()
    assert any(d["action"] == "timeout" for d in decisions)


@pytest.mark.asyncio
async def test_rolls_back_active_version_after_drop_in_monitoring_window(async_session):
    ab = ABTest(id="ab_3", agent_name="writer", baseline_version="v1", challenger_version="v2",
                status="completed", winner="v2", ended_at=datetime.utcnow() - timedelta(hours=2),
                config={"monitoring_hours": 24, "rollback_drop_threshold": 0.05})
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=False, ab_test_id="ab_3", sample_count=100, experiment_state="active-rolled-back")
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=True, ab_test_id="ab_3", sample_count=50, experiment_state="auto_accepted", last_score=82.0)
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    sweeper.weighted_calc = MagicMock()
    sweeper.weighted_calc.compute_batch = MagicMock(return_value={"v1": 80.0, "v2": 70.0})
    # Mock decision_repo so _baseline_score_at_accept returns a score
    mock_decision = MagicMock()
    mock_decision.scores = {"v1": 78.0, "v2": 82.0}
    sweeper.decision_repo.latest_for_experiment = AsyncMock(return_value=mock_decision)
    sweeper.pv_repo.update_experiment_state = AsyncMock()
    sweeper.pv_repo.get_previous_stable = AsyncMock(return_value=pv1)

    decisions = await sweeper.tick()
    assert any(d["action"] == "rolled_back" for d in decisions)


@pytest.mark.asyncio
async def test_isolates_failure_per_experiment(async_session):
    ab = ABTest(id="ab_4", agent_name="writer", baseline_version="v1", challenger_version="v2",
                status="running", started_at=datetime.utcnow() - timedelta(days=1))
    pv1 = PromptVersion(agent_name="writer", version="v1", content="a", is_active=True, ab_test_id="ab_4", sample_count=10)
    pv2 = PromptVersion(agent_name="writer", version="v2", content="b", is_active=False, ab_test_id="ab_4", sample_count=10)
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    sweeper.weighted_calc = AsyncMock(side_effect=RuntimeError("boom"))

    decisions = await sweeper.tick()
    assert len(decisions) == 0
