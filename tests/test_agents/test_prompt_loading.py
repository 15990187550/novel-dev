"""验证 8 个 agent 全部从 PromptRegistry 加载 prompt"""
import pytest

AGENT_NAMES = [
    "brainstorm", "volume_planner", "context_agent",
    "writer", "critic", "editor",
    "fast_review", "librarian",
]


@pytest.mark.asyncio
async def test_each_agent_loads_prompt_from_registry(async_session):
    from novel_dev.services.prompt_registry import PromptRegistry
    reg = PromptRegistry(async_session)
    await reg.bootstrap_defaults()

    for agent_name in AGENT_NAMES:
        active = await reg.get_active(agent_name)
        assert active, f"{agent_name} has no active prompt after bootstrap"
        assert len(active) > 0, f"{agent_name} active prompt is empty"


@pytest.mark.asyncio
async def test_each_agent_has_version_after_bootstrap(async_session):
    from novel_dev.services.prompt_registry import PromptRegistry
    reg = PromptRegistry(async_session)
    await reg.bootstrap_defaults()

    for agent_name in AGENT_NAMES:
        version = await reg.get_active_version_name(agent_name)
        assert version, f"{agent_name} has no active version after bootstrap"
        assert version == "v1.0", f"{agent_name} default version should be v1.0, got {version}"
