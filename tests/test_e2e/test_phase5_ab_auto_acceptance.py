"""Phase 5 E2E: A/B auto-acceptance system.

5 scenarios:
  1. Full A/B -> accept -> stable
  2. A/B -> early stop
  3. A/B -> timeout
  4. A/B -> accepted -> 24h rollback (freezegun)
  5. User manual override -> sweeper should not rollback
"""
import pytest
from datetime import datetime, timedelta
from freezegun import freeze_time
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select

from novel_dev.db.models import ABTest, PromptVersion, ABDecision


@pytest.mark.asyncio
async def test_e2e_full_ab_to_acceptance(async_session):
    """场景 1: 完整 A/B -> 采纳 -> 稳定"""
    from novel_dev.services.ab_acceptance_decider import ABAcceptanceDecider

    pv1 = PromptVersion(
        agent_name="writer", version="v1", content="a", is_active=True,
        ab_test_id="ab_1", sample_count=50,
    )
    pv2 = PromptVersion(
        agent_name="writer", version="v2", content="b", is_active=False,
        ab_test_id="ab_1", sample_count=50,
    )
    ab = ABTest(
        id="ab_1", agent_name="writer", baseline_version="v1",
        challenger_version="v2", status="running",
        started_at=datetime.utcnow() - timedelta(days=1),
    )
    async_session.add_all([pv1, pv2, ab])
    await async_session.flush()

    decider = ABAcceptanceDecider(async_session)
    decider.significance_tester.test = lambda scores: type("R", (), {
        "is_significant": True, "p_value": 0.03,
        "effect_size": 5.0, "threshold_used": "strict", "reason": None,
    })()
    decider.weighted_calc.compute_batch = lambda samples: {"v1": 75.0, "v2": 82.0}

    result = await decider.evaluate(
        "ab_1",
        sample_scores={
            "v1": {"critic_scores": [75.0] * 50, "hook_achieved": [True] * 50, "thrill_verified": [False] * 50},
            "v2": {"critic_scores": [85.0] * 50, "hook_achieved": [True] * 50, "thrill_verified": [True] * 50},
        },
    )
    assert result.action == "accepted"
    assert result.winner == "v2"

    await async_session.refresh(pv2)
    assert pv2.experiment_state == "auto_accepted"
    assert pv2.is_active is True

    from novel_dev.repositories.ab_decision_repo import ABDecisionRepository
    decisions = await ABDecisionRepository(async_session).list_by_experiment("ab_1")
    assert any(d.action == "accept" for d in decisions)


@pytest.mark.asyncio
async def test_e2e_early_stop(async_session):
    """场景 2: A/B -> 早停"""
    from novel_dev.services.ab_acceptance_sweeper import ABAcceptanceSweeper

    ab = ABTest(
        id="ab_es", agent_name="writer", baseline_version="v1",
        challenger_version="v2", status="running",
        started_at=datetime.utcnow() - timedelta(days=1),
        config={"early_stop_consecutive_loss": 3, "early_stop_min_lift": -0.10},
    )
    pv1 = PromptVersion(
        agent_name="writer", version="v1", content="a", is_active=True,
        ab_test_id="ab_es", sample_count=30,
    )
    pv2 = PromptVersion(
        agent_name="writer", version="v2", content="b", is_active=False,
        ab_test_id="ab_es", sample_count=30, experiment_state="running",
    )
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    sweeper._consecutive_loss_count = MagicMock(return_value=3)
    sweeper.weighted_calc.compute_batch = MagicMock(return_value={"v1": 80.0, "v2": 65.0})

    decisions = await sweeper.tick()
    assert any(d["action"] == "early_stop" for d in decisions)


@pytest.mark.asyncio
async def test_e2e_timeout(async_session):
    """场景 3: A/B -> 超时"""
    from novel_dev.services.ab_acceptance_sweeper import ABAcceptanceSweeper

    ab = ABTest(
        id="ab_to", agent_name="writer", baseline_version="v1",
        challenger_version="v2", status="running",
        started_at=datetime.utcnow() - timedelta(days=8),
        config={"timeout_days": 7},
    )
    pv1 = PromptVersion(
        agent_name="writer", version="v1", content="a", is_active=True,
        ab_test_id="ab_to", sample_count=100,
    )
    pv2 = PromptVersion(
        agent_name="writer", version="v2", content="b", is_active=False,
        ab_test_id="ab_to", sample_count=100,
    )
    async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    decisions = await sweeper.tick()
    assert any(d["action"] == "timeout" for d in decisions)


@pytest.mark.asyncio
@freeze_time("2026-06-19 10:00:00")
async def test_e2e_rollback_after_24h(async_session):
    """场景 4: A/B -> 采纳 -> 24h 后回滚(用 freezegun)"""
    from novel_dev.services.ab_acceptance_sweeper import ABAcceptanceSweeper
    from novel_dev.repositories.ab_decision_repo import ABDecisionRepository

    # Previous stable version needed for rollback target
    pv_stable = PromptVersion(
        agent_name="writer", version="v0", content="stable", is_active=False,
        ab_test_id=None, sample_count=200, experiment_state="stable",
        last_decision_at=datetime(2026, 6, 18, 10, 0, 0),
    )
    ab = ABTest(
        id="ab_rb", agent_name="writer", baseline_version="v1",
        challenger_version="v2", status="completed", winner="v2",
        ended_at=datetime(2026, 6, 19, 8, 0, 0),
        config={"monitoring_hours": 24, "rollback_drop_threshold": 0.05},
    )
    pv1 = PromptVersion(
        agent_name="writer", version="v1", content="a", is_active=False,
        ab_test_id="ab_rb", sample_count=100, experiment_state="active-rolled-back",
    )
    pv2 = PromptVersion(
        agent_name="writer", version="v2", content="b", is_active=True,
        ab_test_id="ab_rb", sample_count=50, experiment_state="auto_accepted",
        last_score=82.0,
    )
    async_session.add_all([pv_stable, ab, pv1, pv2])
    await async_session.flush()

    # Record an accept decision so _baseline_score_at_accept returns 82.0
    await ABDecisionRepository(async_session).create(
        experiment_id="ab_rb",
        action="accept",
        prompt_version_id=pv2.id,
        scores={"v1": 75.0, "v2": 82.0},
        p_value=0.03,
        effect_size=5.0,
        decision_at=datetime(2026, 6, 19, 7, 0, 0),
    )

    sweeper = ABAcceptanceSweeper(async_session)
    sweeper.weighted_calc.compute_batch = MagicMock(return_value={"v1": 80.0, "v2": 70.0})

    decisions = await sweeper.tick()
    assert any(d["action"] == "rolled_back" for d in decisions)


@pytest.mark.asyncio
async def test_e2e_manual_override_pauses_sweeper(async_session):
    """场景 5: 用户手动改 active 后 Sweeper 不应自动回滚"""
    from novel_dev.services.ab_acceptance_sweeper import ABAcceptanceSweeper
    from novel_dev.repositories.ab_decision_repo import ABDecisionRepository

    # Previous stable version needed for rollback target
    pv_stable = PromptVersion(
        agent_name="writer", version="v0", content="stable", is_active=False,
        ab_test_id=None, sample_count=200, experiment_state="stable",
        last_decision_at=datetime.utcnow() - timedelta(days=2),
    )
    ab = ABTest(
        id="ab_mo", agent_name="writer", baseline_version="v1",
        challenger_version="v2", status="completed", winner="v2",
        ended_at=datetime.utcnow() - timedelta(hours=2),
        config={"monitoring_hours": 24, "rollback_drop_threshold": 0.05},
    )
    pv1 = PromptVersion(
        agent_name="writer", version="v1", content="a", is_active=False,
        ab_test_id="ab_mo", sample_count=100, experiment_state="manual_override",
    )
    pv2 = PromptVersion(
        agent_name="writer", version="v2", content="b", is_active=True,
        ab_test_id="ab_mo", sample_count=50, experiment_state="manual_override",
        last_score=82.0,
    )
    async_session.add_all([pv_stable, ab, pv1, pv2])
    await async_session.flush()

    # Record accept decision with baseline score for drop calculation
    await ABDecisionRepository(async_session).create(
        experiment_id="ab_mo",
        action="accept",
        prompt_version_id=pv2.id,
        scores={"v1": 75.0, "v2": 82.0},
        p_value=0.03,
        effect_size=5.0,
        decision_at=datetime.utcnow() - timedelta(hours=3),
    )

    sweeper = ABAcceptanceSweeper(async_session)
    sweeper.weighted_calc.compute_batch = MagicMock(return_value={"v1": 82.0, "v2": 70.0})

    decisions = await sweeper.tick()
    rolled_back = [d for d in decisions if d["action"] == "rolled_back"]
    assert len(rolled_back) == 0  # No rollback because winner PV state is manual_override