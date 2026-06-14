import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from novel_dev.llm.factory import LLMFactory


@pytest.mark.asyncio
async def test_get_with_metadata_returns_prompt_version_when_ab_active(async_session):
    factory = LLMFactory(session=async_session, agent_name="writer", task="write_chapter")
    factory._ab_test_runner = AsyncMock()
    factory._ab_test_runner.pick_version = AsyncMock(return_value="v2.0")
    factory._prompt_registry = AsyncMock()
    factory._prompt_registry.get_by_version = AsyncMock(return_value="v2 content")
    factory._prompt_registry.get_active = AsyncMock(return_value="v1 content")
    factory._prompt_registry.get_active_version_name = AsyncMock(return_value="v1.0")
    factory._prompt_registry.increment_sample_count = AsyncMock()

    with patch.object(factory.__class__, "_original_get", new=lambda self: MagicMock()):
        client, metadata = await factory.get_with_metadata()
    assert metadata["prompt_version"] == "v2.0"
    assert metadata["prompt_content"] == "v2 content"


@pytest.mark.asyncio
async def test_get_with_metadata_falls_back_to_active_when_no_ab(async_session):
    factory = LLMFactory(session=async_session, agent_name="writer", task="write_chapter")
    factory._ab_test_runner = AsyncMock()
    factory._ab_test_runner.pick_version = AsyncMock(return_value=None)
    factory._prompt_registry = AsyncMock()
    factory._prompt_registry.get_active = AsyncMock(return_value="v1.0 content")
    factory._prompt_registry.get_active_version_name = AsyncMock(return_value="v1.0")
    factory._prompt_registry.increment_sample_count = AsyncMock()

    with patch.object(factory.__class__, "_original_get", new=lambda self: MagicMock()):
        client, metadata = await factory.get_with_metadata()
    assert metadata["prompt_version"] == "v1.0"
    assert metadata["prompt_content"] == "v1.0 content"
