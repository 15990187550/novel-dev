import pytest
from datetime import datetime
from novel_dev.db.models import PromptVersion
from novel_dev.repositories.prompt_version_repo import PromptVersionRepository


@pytest.mark.asyncio
async def test_update_experiment_state(async_session):
    pv = PromptVersion(agent_name="writer", version="v1.0", content="x")
    async_session.add(pv)
    await async_session.flush()
    repo = PromptVersionRepository(async_session)
    await repo.update_experiment_state(pv.id, "auto_accepted", last_score=82.5)
    await async_session.refresh(pv)
    assert pv.experiment_state == "auto_accepted"
    assert pv.last_score == 82.5


@pytest.mark.asyncio
async def test_list_by_ab_test_id(async_session):
    pv1 = PromptVersion(agent_name="writer", version="v1", content="x", ab_test_id="ab_1")
    pv2 = PromptVersion(agent_name="writer", version="v2", content="y", ab_test_id="ab_1")
    pv3 = PromptVersion(agent_name="writer", version="v3", content="z", ab_test_id="ab_2")
    async_session.add_all([pv1, pv2, pv3])
    await async_session.flush()
    repo = PromptVersionRepository(async_session)
    result = await repo.list_by_ab_test_id("ab_1")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_previous_stable_version(async_session):
    pv_old = PromptVersion(agent_name="writer", version="v0.9", content="x", experiment_state="stable", is_active=False)
    pv_new = PromptVersion(agent_name="writer", version="v1.0", content="y", experiment_state="auto_accepted", is_active=True)
    async_session.add_all([pv_old, pv_new])
    await async_session.flush()
    repo = PromptVersionRepository(async_session)
    prev = await repo.get_previous_stable("writer", exclude_version="v1.0")
    assert prev.version == "v0.9"


@pytest.mark.asyncio
async def test_append_experiment_history(async_session):
    pv = PromptVersion(agent_name="writer", version="v1", content="x")
    async_session.add(pv)
    await async_session.flush()
    repo = PromptVersionRepository(async_session)
    await repo.append_history(pv.id, {"action": "evaluate", "p": 0.03})
    await async_session.refresh(pv)
    assert len(pv.experiment_history) == 1
    assert pv.experiment_history[0]["action"] == "evaluate"