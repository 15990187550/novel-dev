import time
import pytest
from novel_dev.services.ab_significance import SignificanceTester


def test_significance_test_1000_samples_under_100ms():
    tester = SignificanceTester()
    # Use 82.4 to get 3% lift: (82.4-80)/80 = 0.03
    scores = {"v1": [80.0] * 500, "v2": [82.4] * 500}
    start = time.time()
    result = tester.test(scores)
    elapsed = time.time() - start
    assert elapsed < 0.1
    assert result.is_significant is True


@pytest.mark.asyncio
async def test_sweeper_50_experiments_under_5s(async_session):
    from novel_dev.db.models import ABTest, PromptVersion
    from datetime import datetime, timedelta
    from novel_dev.services.ab_acceptance_sweeper import ABAcceptanceSweeper
    from unittest.mock import MagicMock

    for i in range(50):
        # Use unique version names per AB test since (agent_name, version) is unique-constrained
        baseline_v = f"v1_{i}"
        challenger_v = f"v2_{i}"
        ab = ABTest(id=f"ab_{i}", agent_name="writer", baseline_version=baseline_v, challenger_version=challenger_v,
                    status="running", started_at=datetime.utcnow() - timedelta(days=1))
        pv1 = PromptVersion(agent_name="writer", version=baseline_v, content="a", is_active=True, ab_test_id=f"ab_{i}", sample_count=10)
        pv2 = PromptVersion(agent_name="writer", version=challenger_v, content="b", is_active=False, ab_test_id=f"ab_{i}", sample_count=10)
        async_session.add_all([ab, pv1, pv2])
    await async_session.flush()

    sweeper = ABAcceptanceSweeper(async_session)
    # Mock compute_batch to return a dict keyed by baseline/challenger version
    sweeper.weighted_calc.compute_batch = MagicMock(return_value={"baseline": 80.0, "challenger": 80.5})

    start = time.time()
    decisions = await sweeper.tick()
    elapsed = time.time() - start
    assert elapsed < 5.0