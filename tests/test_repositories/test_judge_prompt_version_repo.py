import pytest
from datetime import datetime
from novel_dev.db.models import JudgePromptVersion
from novel_dev.repositories.judge_prompt_version_repo import JudgePromptVersionRepository


@pytest.mark.asyncio
async def test_get_active_returns_only_active(async_session):
    pv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    pv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=False)
    async_session.add_all([pv1, pv2])
    await async_session.flush()

    repo = JudgePromptVersionRepository(async_session)
    active = await repo.get_active()
    assert active is not None
    assert active.version == "v1"


@pytest.mark.asyncio
async def test_get_active_returns_none_when_no_active(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=False)
    async_session.add(pv)
    await async_session.flush()

    repo = JudgePromptVersionRepository(async_session)
    assert await repo.get_active() is None


@pytest.mark.asyncio
async def test_get_active_at_picks_historical_version(async_session):
    pv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True, created_at=datetime(2026, 1, 1))
    pv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=True, created_at=datetime(2026, 6, 1))
    async_session.add_all([pv1, pv2])
    await async_session.flush()

    repo = JudgePromptVersionRepository(async_session)
    historical = await repo.get_active_at(datetime(2026, 3, 1))
    assert historical is not None
    assert historical.version == "v1"


@pytest.mark.asyncio
async def test_set_active_deactivates_others(async_session):
    pv1 = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="a", is_active=True)
    pv2 = JudgePromptVersion(version="v2", agent_name="judge_agent", prompt_text="b", is_active=False)
    async_session.add_all([pv1, pv2])
    await async_session.flush()

    repo = JudgePromptVersionRepository(async_session)
    await repo.set_active(pv2.id)
    await async_session.refresh(pv1)
    await async_session.refresh(pv2)
    assert pv1.is_active is False
    assert pv2.is_active is True


@pytest.mark.asyncio
async def test_set_ab_test_id(async_session):
    pv = JudgePromptVersion(version="v1", agent_name="judge_agent", prompt_text="x", is_active=False)
    async_session.add(pv)
    await async_session.flush()

    repo = JudgePromptVersionRepository(async_session)
    await repo.set_ab_test_id(pv.id, "ab_xyz")
    await async_session.refresh(pv)
    assert pv.ab_test_id == "ab_xyz"