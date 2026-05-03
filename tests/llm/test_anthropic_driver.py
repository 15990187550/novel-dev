import pytest
from unittest.mock import AsyncMock, MagicMock
import sys
import types

from novel_dev.llm.drivers.anthropic import AnthropicDriver
from novel_dev.llm.exceptions import LLMRateLimitError
from novel_dev.llm.models import ChatMessage, StructuredOutputConfig, TaskConfig


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


@pytest.mark.asyncio
async def test_anthropic_forwards_structured_tool_config():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(text="ok")],
            usage=MagicMock(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )
    )
    driver = AnthropicDriver(client=mock_client)
    config = TaskConfig(
        provider="anthropic",
        model="claude-sonnet",
        response_tool_name="emit_payload",
        response_json_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )
    await driver.acomplete("hi", config)
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["tools"][0]["name"] == "emit_payload"
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "emit_payload"}


@pytest.mark.asyncio
async def test_anthropic_allows_auto_tool_choice_for_compatible_providers():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(text="ok")],
            usage=MagicMock(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )
    )
    driver = AnthropicDriver(client=mock_client)
    config = TaskConfig(
        provider="anthropic",
        model="deepseek-v4-flash",
        structured_output=StructuredOutputConfig(mode="anthropic_tool", tool_choice="auto"),
        response_tool_name="emit_payload",
        response_json_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )
    await driver.acomplete("hi", config)
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["tools"][0]["name"] == "emit_payload"
    assert call_kwargs["tool_choice"] == {"type": "auto"}


@pytest.mark.asyncio
async def test_anthropic_can_omit_tool_choice_when_configured():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(text="ok")],
            usage=MagicMock(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )
    )
    driver = AnthropicDriver(client=mock_client)
    config = TaskConfig(
        provider="anthropic",
        model="compatible-model",
        structured_output=StructuredOutputConfig(mode="anthropic_tool", tool_choice="none"),
        response_tool_name="emit_payload",
        response_json_schema={"type": "object", "properties": {"value": {"type": "string"}}},
    )
    await driver.acomplete("hi", config)
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["tools"][0]["name"] == "emit_payload"
    assert "tool_choice" not in call_kwargs


@pytest.mark.asyncio
async def test_anthropic_extracts_tool_use_payload():
    tool_block = MagicMock()
    del tool_block.text
    tool_block.type = "tool_use"
    tool_block.name = "emit_payload"
    tool_block.input = {"value": "ok"}
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[tool_block],
            usage=MagicMock(input_tokens=1, output_tokens=1),
            stop_reason="tool_use",
        )
    )
    driver = AnthropicDriver(client=mock_client)
    config = TaskConfig(
        provider="anthropic",
        model="claude-sonnet",
        response_tool_name="emit_payload",
        response_json_schema={"type": "object", "properties": {"value": {"type": "string"}}},
    )
    response = await driver.acomplete("hi", config)
    assert response.structured_payload == {"value": "ok"}
    assert response.finish_reason == "tool_use"


def test_map_exception_without_overloaded_error_symbol():
    driver = AnthropicDriver(client=MagicMock())

    class FakeRateLimitError(Exception):
        pass

    fake_module = types.SimpleNamespace(
        RateLimitError=FakeRateLimitError,
        APITimeoutError=type("APITimeoutError", (Exception,), {}),
        APIConnectionError=type("APIConnectionError", (Exception,), {}),
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
        PermissionDeniedError=type("PermissionDeniedError", (Exception,), {}),
    )
    original = sys.modules.get("anthropic")
    sys.modules["anthropic"] = fake_module
    try:
        mapped = driver._map_exception(FakeRateLimitError("busy"))
    finally:
        if original is not None:
            sys.modules["anthropic"] = original
        else:
            del sys.modules["anthropic"]

    assert isinstance(mapped, LLMRateLimitError)


def test_map_payment_required_status_to_rate_limit_error():
    driver = AnthropicDriver(client=MagicMock())

    class FakePaymentRequired(Exception):
        status_code = 402

    mapped = driver._map_exception(FakePaymentRequired("membership unavailable"))

    assert isinstance(mapped, LLMRateLimitError)
