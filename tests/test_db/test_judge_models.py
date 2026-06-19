import pytest
from novel_dev.db.models import JudgePromptVersion


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