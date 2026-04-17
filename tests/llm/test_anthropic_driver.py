import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_dev.llm.drivers.anthropic import AnthropicDriver
from novel_dev.llm.models import ChatMessage, TaskConfig


@pytest.mark.asyncio
async def test_anthropic_acomplete_with_string():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(text="anthropic says hi")],
            usage=MagicMock(input_tokens=4, output_tokens=2),
        )
    )
    driver = AnthropicDriver(client=mock_client)
    config = TaskConfig(provider="anthropic", model="claude-opus-4-6")
    response = await driver.acomplete("say hi", config)
    assert response.text == "anthropic says hi"
    assert response.usage.prompt_tokens == 4


@pytest.mark.asyncio
async def test_anthropic_acomplete_extracts_system_message():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(text="ok")],
            usage=MagicMock(input_tokens=2, output_tokens=1),
        )
    )
    driver = AnthropicDriver(client=mock_client)
    config = TaskConfig(provider="anthropic", model="claude-sonnet")
    messages = [
        ChatMessage(role="system", content="be helpful"),
        ChatMessage(role="user", content="hello"),
    ]
    await driver.acomplete(messages, config)
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["system"] == "be helpful"
    assert call_kwargs["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_anthropic_concatenates_multiple_system_messages():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(text="ok")],
            usage=MagicMock(input_tokens=2, output_tokens=1),
        )
    )
    driver = AnthropicDriver(client=mock_client)
    config = TaskConfig(provider="anthropic", model="claude-sonnet")
    messages = [
        ChatMessage(role="system", content="sys1"),
        ChatMessage(role="system", content="sys2"),
        ChatMessage(role="user", content="hello"),
    ]
    await driver.acomplete(messages, config)
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["system"] == "sys1\n\nsys2"


@pytest.mark.asyncio
async def test_anthropic_forwards_temperature():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(text="ok")],
            usage=MagicMock(input_tokens=1, output_tokens=1),
        )
    )
    driver = AnthropicDriver(client=mock_client)
    config = TaskConfig(provider="anthropic", model="claude-sonnet", temperature=0.5)
    await driver.acomplete("hi", config)
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["temperature"] == 0.5
