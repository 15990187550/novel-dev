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
