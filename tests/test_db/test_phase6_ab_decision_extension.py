import pytest
from datetime import datetime
from novel_dev.db.models import ABDecision


@pytest.mark.asyncio
async def test_ab_decision_has_judge_fields(async_session):
    d = ABDecision(
        experiment_id="exp_1",
        action="evaluate",
        decision_at=datetime.utcnow(),
        judge_triggered=True,
        judge_tie_breaker_baseline=7.5,
        judge_tie_breaker_challenger=8.2,
        judge_scores_baseline={"口吻": 7.0, "叙事连贯": 8.0, "风格调性": 7.5},
        judge_scores_challenger={"口吻": 8.0, "叙事连贯": 8.5, "风格调性": 8.0},
        judge_rationale_baseline="口吻自然,推进流畅",
        judge_rationale_challenger="叙事更紧凑",
        judge_model="claude-sonnet-4-6",
    )
    async_session.add(d)
    await async_session.flush()
    fetched = await async_session.get(ABDecision, d.id)
    assert fetched.judge_triggered is True
    assert fetched.judge_tie_breaker_baseline == 7.5
    assert fetched.judge_tie_breaker_challenger == 8.2
    assert fetched.judge_scores_challenger["口吻"] == 8.0
    assert fetched.judge_model == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_ab_decision_judge_optional_by_default(async_session):
    d = ABDecision(
        experiment_id="exp_2",
        action="evaluate",
        decision_at=datetime.utcnow(),
    )
    async_session.add(d)
    await async_session.flush()
    fetched = await async_session.get(ABDecision, d.id)
    assert fetched.judge_triggered is False
    assert fetched.judge_tie_breaker_baseline is None
    assert fetched.judge_error is None
