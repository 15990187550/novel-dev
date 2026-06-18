import pytest
from novel_dev.db.models import PromptVersion


@pytest.mark.asyncio
async def test_prompt_version_has_phase5_fields(async_session):
    pv = PromptVersion(
        agent_name="writer", version="v1.0", content="x",
        experiment_state="running", last_score=78.5,
    )
    async_session.add(pv)
    await async_session.flush()
    fetched = await async_session.get(PromptVersion, pv.id)
    assert fetched.experiment_state == "running"
    assert fetched.last_score == 78.5
    assert fetched.last_decision_at is None
    assert fetched.experiment_history == []
