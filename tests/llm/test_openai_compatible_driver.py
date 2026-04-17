import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_dev.llm.drivers.openai_compatible import OpenAICompatibleDriver
from novel_dev.llm.models import ChatMessage, TaskConfig


@pytest.mark.asyncio
async def test_openai_compatible_acomplete_with_string():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content="hello"))],
            usage=MagicMock(prompt_tokens=2, completion_tokens=1, total_tokens=3),
        )
    )
    driver = OpenAICompatibleDriver(client=mock_client)
    config = TaskConfig(provider="openai_compatible", model="gpt-4")
    response = await driver.acomplete("say hi", config)
    assert response.text == "hello"
    assert response.usage.total_tokens == 3


@pytest.mark.asyncio
async def test_openai_compatible_acomplete_with_messages():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content="world"))],
            usage=MagicMock(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )
    )
    driver = OpenAICompatibleDriver(client=mock_client)
    config = TaskConfig(provider="openai_compatible", model="kimi-k2.5")
    messages = [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="usr")]
    response = await driver.acomplete(messages, config)
    assert response.text == "world"
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "kimi-k2.5"
    assert call_kwargs["messages"][0]["role"] == "system"
