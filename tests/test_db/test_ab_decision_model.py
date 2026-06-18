import pytest
from datetime import datetime, timedelta
from novel_dev.db.models import ABDecision


@pytest.mark.asyncio
async def test_ab_decision_persists_with_required_fields(async_session):
    d = ABDecision(
        experiment_id="exp_1",
        prompt_version_id="pv_1",
        action="evaluate",
        decision_at=datetime.utcnow(),
        p_value=0.03,
        scores={"v1": 75.0, "v2": 79.0},
        effect_size=0.4,
        meta={"samples": 50},
    )
    async_session.add(d)
    await async_session.flush()
    fetched = await async_session.get(ABDecision, d.id)
    assert fetched.action == "evaluate"
    assert fetched.scores["v2"] == 79.0