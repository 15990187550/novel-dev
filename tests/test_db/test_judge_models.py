import pytest
from novel_dev.db.models import JudgePromptVersion, JudgeABTest, JudgeCallLog


@pytest.mark.asyncio
async def test_judge_prompt_version_persists(async_session):
    pv = JudgePromptVersion(
        version="judge-v1",
        agent_name="judge_agent",
        prompt_text="你是一位...",
        is_active=True,
        experiment_state="active",
        last_score=0.85,
        experiment_history=[{"action": "created", "at": "2026-06-19T00:00:00"}],
    )
    async_session.add(pv)
    await async_session.flush()
    fetched = await async_session.get(JudgePromptVersion, pv.id)
    assert fetched.version == "judge-v1"
    assert fetched.is_active is True
    assert fetched.last_score == 0.85
    assert fetched.experiment_history[0]["action"] == "created"


@pytest.mark.asyncio
async def test_judge_ab_test_persists(async_session):
    ab = JudgeABTest(
        agent_name="judge_agent",
        baseline_version="judge-v1",
        challenger_version="judge-v2",
        status="running",
        config={"samples_required": 50},
    )
    async_session.add(ab)
    await async_session.flush()
    fetched = await async_session.get(JudgeABTest, ab.id)
    assert fetched.baseline_version == "judge-v1"
    assert fetched.status == "running"
    assert fetched.winner is None


@pytest.mark.asyncio
async def test_judge_call_log_persists(async_session):
    log = JudgeCallLog(
        decision_id="dec_1",
        prompt_version_id="pv_1",
        model="claude-sonnet-4-6",
        input_tokens=1500,
        output_tokens=80,
        latency_ms=2300,
        cost_usd=0.0042,
    )
    async_session.add(log)
    await async_session.flush()
    fetched = await async_session.get(JudgeCallLog, log.id)
    assert fetched.model == "claude-sonnet-4-6"
    assert fetched.cost_usd == 0.0042
    assert fetched.latency_ms == 2300
