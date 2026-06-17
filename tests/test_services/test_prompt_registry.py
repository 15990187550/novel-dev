import pytest
from novel_dev.services.prompt_registry import PromptRegistry
from novel_dev.agents._default_prompts import DEFAULT_PROMPTS


@pytest.mark.asyncio
async def test_get_active_returns_db_version(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "from db", is_active=True)
    content = await reg.get_active("writer")
    assert content == "from db"


@pytest.mark.asyncio
async def test_get_active_falls_back_to_default(async_session, monkeypatch):
    monkeypatch.setattr("novel_dev.services.prompt_registry.settings", type("S", (), {
        "phase3_cold_start_allow_hardcoded_fallback": True,
    })())
    reg = PromptRegistry(async_session)
    content = await reg.get_active("writer")
    assert content == DEFAULT_PROMPTS["writer"]


@pytest.mark.asyncio
async def test_get_by_version_for_ab(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "v1 content", is_active=True)
    await reg.create_version("writer", "v2.0", "v2 content")
    v1 = await reg.get_by_version("writer", "v1.0")
    v2 = await reg.get_by_version("writer", "v2.0")
    assert v1 == "v1 content"
    assert v2 == "v2 content"


@pytest.mark.asyncio
async def test_bootstrap_loads_defaults(async_session):
    reg = PromptRegistry(async_session)
    await reg.bootstrap_defaults()
    for agent_name in DEFAULT_PROMPTS:
        content = await reg.get_active(agent_name)
        assert content == DEFAULT_PROMPTS[agent_name]


@pytest.mark.asyncio
async def test_get_active_version_name(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v2.0", "v2 content", is_active=True)
    name = await reg.get_active_version_name("writer")
    assert name == "v2.0"


@pytest.mark.asyncio
async def test_get_active_raises_when_fallback_disabled_and_no_db_version(async_session, monkeypatch):
    monkeypatch.setattr("novel_dev.services.prompt_registry.settings", type("S", (), {
        "phase3_cold_start_allow_hardcoded_fallback": False,
    })())
    reg = PromptRegistry(async_session)
    with pytest.raises(RuntimeError, match="cold_start fallback disabled"):
        await reg.get_active("writer")


@pytest.mark.asyncio
async def test_get_by_version_raises_when_missing(async_session):
    reg = PromptRegistry(async_session)
    with pytest.raises(ValueError, match="not found"):
        await reg.get_by_version("writer", "v9.9")


@pytest.mark.asyncio
async def test_list_versions_returns_dicts(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "v1", is_active=True)
    await reg.create_version("writer", "v2.0", "v2", parent_version="v1.0", ab_test_id="ab_1")
    versions = await reg.list_versions("writer")
    assert len(versions) == 2
    keys = set(versions[0].keys())
    assert {"id", "agent_name", "version", "content", "is_active", "created_at",
            "created_by", "sample_count", "parent_version", "ab_test_id"} <= keys


@pytest.mark.asyncio
async def test_create_version_raises_when_duplicate(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "first")
    with pytest.raises(ValueError, match="already exists"):
        await reg.create_version("writer", "v1.0", "second")


@pytest.mark.asyncio
async def test_set_active_switches(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "v1", is_active=True)
    await reg.create_version("writer", "v2.0", "v2")
    await reg.set_active("writer", "v2.0")
    assert await reg.get_active("writer") == "v2"
    from novel_dev.repositories.prompt_version_repo import PromptVersionRepository
    pv1 = await PromptVersionRepository(async_session).get_by_version("writer", "v1.0")
    assert pv1.is_active is False


@pytest.mark.asyncio
async def test_rollback_swaps_active(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "v1", is_active=True)
    await reg.create_version("writer", "v2.0", "v2")
    await reg.rollback("writer", "v2.0")
    assert await reg.get_active("writer") == "v2"


@pytest.mark.asyncio
async def test_delete_version(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "v1", is_active=True)
    await reg.create_version("writer", "v2.0", "v2")
    await reg.delete_version("writer", "v2.0")
    with pytest.raises(ValueError, match="not found"):
        await reg.get_by_version("writer", "v2.0")


@pytest.mark.asyncio
async def test_bootstrap_skips_existing_active(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "custom v1", is_active=True)
    await reg.bootstrap_defaults()
    # writer should still have the custom v1, not the default
    assert await reg.get_active("writer") == "custom v1"


@pytest.mark.asyncio
async def test_increment_sample_count(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "v1", is_active=True)
    await reg.increment_sample_count("writer", "v1.0")
    await reg.increment_sample_count("writer", "v1.0")
    from novel_dev.repositories.prompt_version_repo import PromptVersionRepository
    pv = await PromptVersionRepository(async_session).get_by_version("writer", "v1.0")
    assert pv.sample_count == 2


@pytest.mark.asyncio
async def test_get_active_for_chapter_no_ab_returns_active_version(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "v1 content", is_active=True)
    content = await reg.get_active_for_chapter("writer", "ch_1")
    assert content == "v1 content"


@pytest.mark.asyncio
async def test_get_active_for_chapter_routes_via_ab_when_running(async_session):
    from novel_dev.services.ab_test_runner import ABTestRunner
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "v1 content", is_active=True)
    await reg.create_version("writer", "v2.0", "v2 content")
    runner = ABTestRunner(async_session)
    await runner.start("writer", "v1.0", "v2.0", max_samples=10, min_samples=3)

    picked = set()
    for i in range(100):
        c = await reg.get_active_for_chapter("writer", f"ch_{i}")
        picked.add(c)
    assert picked == {"v1 content", "v2 content"}
