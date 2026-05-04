import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_dev.llm.drivers.openai_compatible import OpenAICompatibleDriver
from novel_dev.llm.models import CapabilityToolConfig, ChatMessage, StructuredOutputConfig, TaskConfig


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


@pytest.mark.asyncio
async def test_openai_compatible_forwards_structured_tool_config():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content="{}", tool_calls=None), finish_reason="stop")],
            usage=MagicMock(prompt_tokens=2, completion_tokens=1, total_tokens=3),
        )
    )
    driver = OpenAICompatibleDriver(client=mock_client)
    config = TaskConfig(
        provider="openai_compatible",
        model="gpt-4",
        response_tool_name="emit_payload",
        response_json_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )
    await driver.acomplete("say hi", config)
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["tools"][0]["function"]["name"] == "emit_payload"
    assert call_kwargs["tool_choice"] == {"type": "function", "function": {"name": "emit_payload"}}


@pytest.mark.asyncio
async def test_openai_compatible_extracts_tool_payload():
    tool_call = MagicMock(function=MagicMock(arguments='{"value":"ok"}'))
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content=None, tool_calls=[tool_call]), finish_reason="tool_calls")],
            usage=MagicMock(prompt_tokens=2, completion_tokens=1, total_tokens=3),
        )
    )
    driver = OpenAICompatibleDriver(client=mock_client)
    config = TaskConfig(
        provider="openai_compatible",
        model="gpt-4",
        response_tool_name="emit_payload",
        response_json_schema={"type": "object", "properties": {"value": {"type": "string"}}},
    )
    response = await driver.acomplete("say hi", config)
    assert response.structured_payload == {"value": "ok"}
    assert response.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_openai_compatible_distinguishes_response_tool_from_capability_tools():
    response_tool_call = MagicMock(
        id="response_1",
        function=MagicMock(name="emit_payload", arguments='{"value":"done"}'),
    )
    capability_tool_call = MagicMock(
        id="tool_1",
        function=MagicMock(name="get_novel_state", arguments='{"novel_id":"n1"}'),
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(content=None, tool_calls=[capability_tool_call, response_tool_call]),
                    finish_reason="tool_calls",
                )
            ],
            usage=MagicMock(prompt_tokens=2, completion_tokens=1, total_tokens=3),
        )
    )
    driver = OpenAICompatibleDriver(client=mock_client)
    config = TaskConfig(
        provider="openai_compatible",
        model="gpt-4",
        structured_output=StructuredOutputConfig(mode="openai_tool", tool_choice="auto"),
        response_tool_name="emit_payload",
        response_json_schema={"type": "object", "properties": {"value": {"type": "string"}}},
        capability_tools=[
            CapabilityToolConfig(
                name="get_novel_state",
                description="Read the current novel state.",
                input_schema={
                    "type": "object",
                    "properties": {"novel_id": {"type": "string"}},
                    "required": ["novel_id"],
                },
            )
        ],
    )
    response = await driver.acomplete("say hi", config)
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert [tool["function"]["name"] for tool in call_kwargs["tools"]] == ["emit_payload", "get_novel_state"]
    assert call_kwargs["tool_choice"] == "auto"
    assert response.structured_payload == {"value": "done"}
    assert response.tool_calls[0].name == "get_novel_state"
    assert response.tool_calls[0].arguments == {"novel_id": "n1"}
