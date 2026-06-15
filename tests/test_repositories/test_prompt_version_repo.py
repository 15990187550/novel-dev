import pytest
from novel_dev.db.models import PromptVersion
from novel_dev.repositories.prompt_version_repo import PromptVersionRepository


@pytest.mark.asyncio
async def test_create_and_get_active(async_session):
    repo = PromptVersionRepository(async_session)
    await repo.create(agent_name="writer", version="v1.0", content="hello {var}", is_active=True)
    active = await repo.get_active("writer")
    assert active is not None
    assert active.content == "hello {var}"
    assert active.is_active is True


@pytest.mark.asyncio
async def test_set_active_atomic_switch(async_session):
    repo = PromptVersionRepository(async_session)
    await repo.create(agent_name="writer", version="v1.0", content="old", is_active=True)
    await repo.create(agent_name="writer", version="v2.0", content="new", is_active=False)
    await repo.set_active("writer", "v2.0")
    active = await repo.get_active("writer")
    assert active.version == "v2.0"
    v1 = await repo.get_by_version("writer", "v1.0")
    assert v1.is_active is False


@pytest.mark.asyncio
async def test_list_versions_descending(async_session):
    repo = PromptVersionRepository(async_session)
    await repo.create(agent_name="writer", version="v1.0", content="a", is_active=True)
    await repo.create(agent_name="writer", version="v2.0", content="b")
    versions = await repo.list_versions("writer")
    assert [v.version for v in versions] == ["v2.0", "v1.0"]


@pytest.mark.asyncio
async def test_delete_inactive_only(async_session):
    repo = PromptVersionRepository(async_session)
    await repo.create(agent_name="writer", version="v1.0", content="a", is_active=True)
    with pytest.raises(ValueError, match="active"):
        await repo.delete("writer", "v1.0")
    await repo.create(agent_name="writer", version="v2.0", content="b")
    await repo.delete("writer", "v2.0")
    assert await repo.get_by_version("writer", "v2.0") is None


@pytest.mark.asyncio
async def test_increment_sample_count(async_session):
    repo = PromptVersionRepository(async_session)
    await repo.create(agent_name="writer", version="v1.0", content="x", is_active=True)
    await repo.increment_sample_count("writer", "v1.0")
    await repo.increment_sample_count("writer", "v1.0")
    v = await repo.get_by_version("writer", "v1.0")
    assert v.sample_count == 2


@pytest.mark.asyncio
async def test_set_active_raises_when_missing(async_session):
    from novel_dev.repositories.prompt_version_repo import PromptVersionRepository
    repo = PromptVersionRepository(async_session)
    with pytest.raises(ValueError, match="not found"):
        await repo.set_active("writer", "v9.9")


@pytest.mark.asyncio
async def test_delete_noop_when_missing(async_session):
    from novel_dev.repositories.prompt_version_repo import PromptVersionRepository
    repo = PromptVersionRepository(async_session)
    # Should not raise
    await repo.delete("writer", "v9.9")
