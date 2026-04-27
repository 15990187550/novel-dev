from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from novel_dev.agents._llm_helpers import call_and_parse, call_and_parse_model, register_structured_normalizer
from novel_dev.llm.fallback_driver import FallbackDriver
from novel_dev.llm.models import LLMResponse, StructuredOutputConfig, TaskConfig
from novel_dev.services.flow_control_service import FlowCancelledError, clear_cancel_request, request_cancel
from novel_dev.services.log_service import LogService


class ExamplePayload(BaseModel):
    title: str
    tags: list[str] = []


@pytest.fixture(autouse=True)
def clear_log_buffers():
    LogService._buffers.clear()
    LogService._listeners.clear()
    clear_cancel_request("novel-cancel")


@pytest.mark.asyncio
async def test_call_and_parse_success():
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text='{"key": "value"}')

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse(
            "TestAgent", "test_task", "prompt",
            lambda text: {"key": "value"}, max_retries=3
        )

    assert result == {"key": "value"}


@pytest.mark.asyncio
async def test_call_and_parse_retry_on_validation_error():
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text="invalid json"),
        LLMResponse(text='{"key": "value"}'),
    ]

    def parser(text):
        import json
        return json.loads(text)

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse(
            "TestAgent", "test_task", "prompt",
            parser, max_retries=3
        )

    assert result == {"key": "value"}
    assert mock_client.acomplete.call_count == 2


@pytest.mark.asyncio
async def test_call_and_parse_raises_after_max_retries():
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text="invalid json")

    def parser(text):
        import json
        return json.loads(text)

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        with pytest.raises(RuntimeError, match="LLM parse failed after 3 retries"):
            await call_and_parse(
                "TestAgent", "test_task", "prompt",
                parser, max_retries=3
            )

    assert mock_client.acomplete.call_count == 3


@pytest.mark.asyncio
async def test_call_and_parse_model_extracts_markdown_json_array():
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text='''结果如下：\n```json\n[{"title": "主线", "tags": ["成长"]}]\n```'''
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent", "test_task", "prompt", list[ExamplePayload], max_retries=3
        )

    assert len(result) == 1
    assert result[0].title == "主线"
    assert result[0].tags == ["成长"]


@pytest.mark.asyncio
async def test_call_and_parse_model_prefers_structured_payload():
    mock_client = AsyncMock()
    mock_client.config = TaskConfig(provider="anthropic", model="test-model")
    mock_client.acomplete.return_value = LLMResponse(
        text="",
        structured_payload={"title": "主线", "tags": ["成长"]},
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent", "test_task", "prompt", ExamplePayload, max_retries=3
        )

    assert result.title == "主线"
    assert result.tags == ["成长"]
    call_kwargs = mock_client.acomplete.call_args.kwargs
    assert call_kwargs["config"].response_tool_name == "emit_test_task"
    assert call_kwargs["config"].response_json_schema["type"] == "object"
    assert "$defs" not in call_kwargs["config"].response_json_schema
    assert "title" not in call_kwargs["config"].response_json_schema


@pytest.mark.asyncio
async def test_call_and_parse_model_wraps_list_structured_payload():
    mock_client = AsyncMock()
    mock_client.config = TaskConfig(provider="anthropic", model="test-model")
    mock_client.acomplete.return_value = LLMResponse(
        text="",
        structured_payload={"items": [{"title": "主线", "tags": ["成长"]}]},
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent", "test_task", "prompt", list[ExamplePayload], max_retries=3
        )

    assert len(result) == 1
    assert result[0].title == "主线"
    call_kwargs = mock_client.acomplete.call_args.kwargs
    assert call_kwargs["config"].structured_output.wrap_array is True
    assert "items" in call_kwargs["config"].response_json_schema["properties"]


@pytest.mark.asyncio
async def test_call_and_parse_model_unwraps_single_list_payload_key():
    mock_client = AsyncMock()
    mock_client.config = TaskConfig(provider="anthropic", model="test-model")
    mock_client.acomplete.return_value = LLMResponse(
        text="",
        structured_payload={"beats": [{"title": "主线", "tags": ["成长"]}]},
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent", "test_task", "prompt", list[ExamplePayload], max_retries=3
        )

    assert len(result) == 1
    assert result[0].title == "主线"


@pytest.mark.asyncio
async def test_call_and_parse_model_falls_back_to_text_without_structured_payload():
    mock_client = AsyncMock()
    mock_client.config = TaskConfig(provider="anthropic", model="test-model")
    mock_client.acomplete.return_value = LLMResponse(text='{"title": "主线", "tags": ["成长"]}')

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent", "test_task", "prompt", ExamplePayload, max_retries=3
        )

    assert result.title == "主线"


@pytest.mark.asyncio
async def test_call_and_parse_model_uses_registered_normalizer_before_retry():
    mock_client = AsyncMock()
    mock_client.config = TaskConfig(provider="anthropic", model="test-model")
    mock_client.acomplete.return_value = LLMResponse(
        text="",
        structured_payload={"name": "主线", "tags": "成长"},
    )

    def normalize(payload, _error):
        normalized = dict(payload)
        normalized["title"] = normalized.pop("name", "")
        normalized["tags"] = [normalized["tags"]]
        return normalized

    register_structured_normalizer("NormalizeAgent", "normalize_task", normalize)

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "NormalizeAgent",
            "normalize_task",
            "prompt",
            ExamplePayload,
            max_retries=3,
            novel_id="novel-normalize",
        )

    assert result.title == "主线"
    assert result.tags == ["成长"]
    assert mock_client.acomplete.call_count == 1
    assert any(entry.get("node") == "llm_normalize" for entry in LogService._buffers["novel-normalize"])


@pytest.mark.asyncio
async def test_call_and_parse_model_retries_with_json_repair_prompt():
    broken_json = '{"title": "诸天执道者", "tags": ["围绕"自由意志"展开"]}'
    fixed_json = '{"title": "诸天执道者", "tags": ["围绕自由意志展开"]}'

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=broken_json),
        LLMResponse(text=fixed_json),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent", "test_task", "original prompt", ExamplePayload, max_retries=3
        )

    assert result.title == "诸天执道者"
    assert result.tags == ["围绕自由意志展开"]
    assert mock_client.acomplete.call_count == 2

    repair_message = mock_client.acomplete.call_args_list[1].args[0][0].content
    assert "JSON 解析失败" in repair_message
    assert broken_json in repair_message


@pytest.mark.asyncio
async def test_call_and_parse_model_retries_with_regenerate_prompt_on_empty_output():
    fixed_json = '{"title": "诸天执道者", "tags": ["成长"]}'

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=""),
        LLMResponse(text=fixed_json),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent", "test_task", "original prompt", ExamplePayload, max_retries=3
        )

    assert result.title == "诸天执道者"
    assert result.tags == ["成长"]
    retry_message = mock_client.acomplete.call_args_list[1].args[0][0].content
    assert "返回为空" in retry_message
    assert "original prompt" in retry_message


@pytest.mark.asyncio
async def test_call_and_parse_model_recovers_truncated_json_without_retry():
    broken_json = '{"title": "诸天执道者", "tags": ["成长"]'

    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=broken_json)

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent", "test_task", "original prompt", ExamplePayload, max_retries=3
        )

    assert result.title == "诸天执道者"
    assert result.tags == ["成长"]
    assert mock_client.acomplete.call_count == 1


@pytest.mark.asyncio
async def test_call_and_parse_model_uses_regenerate_prompt_after_repair_attempt_fails():
    broken_json = '{"title": "诸天执道者", "tags": ["围绕'
    regenerated_json = '{"title": "诸天执道者", "tags": ["围绕自由意志展开"]}'

    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=broken_json),
        LLMResponse(text=regenerated_json),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent", "test_task", "original prompt", ExamplePayload, max_retries=3
        )

    assert result.title == "诸天执道者"
    assert result.tags == ["围绕自由意志展开"]
    retry_message = mock_client.acomplete.call_args_list[1].args[0][0].content
    assert "请重新完成原始任务" in retry_message
    assert "上次错误" in retry_message


@pytest.mark.asyncio
async def test_call_and_parse_model_emits_frontend_visible_llm_node_logs():
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text='{"title": "主线", "tags": ["成长"]}')

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent",
            "test_task",
            "prompt",
            ExamplePayload,
            max_retries=3,
            novel_id="novel-logs",
        )

    assert result.title == "主线"
    entries = list(LogService._buffers["novel-logs"])
    statuses = [entry.get("status") for entry in entries]
    assert "started" in statuses
    assert "succeeded" in statuses
    assert any(entry.get("event") == "agent.llm" and entry.get("node") == "llm_call" for entry in entries)
    assert any(entry.get("task") == "test_task" for entry in entries)


@pytest.mark.asyncio
async def test_call_and_parse_model_switches_to_fallback_after_parse_failures():
    primary = AsyncMock()
    primary.config = TaskConfig(provider="anthropic", model="primary")
    primary.acomplete.return_value = LLMResponse(text="")

    fallback = AsyncMock()
    fallback.config = TaskConfig(provider="anthropic", model="fallback")
    fallback.acomplete.return_value = LLMResponse(
        text="",
        structured_payload={"title": "备用模型", "tags": ["稳定"]},
    )

    client = FallbackDriver(
        primary=primary,
        fallback=fallback,
        fallback_config=TaskConfig(provider="anthropic", model="fallback"),
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = client
        result = await call_and_parse_model(
            "TestAgent",
            "fallback_task",
            "prompt",
            ExamplePayload,
            max_retries=1,
            novel_id="novel-fallback",
    )

    assert result.title == "备用模型"
    assert primary.acomplete.call_count == 2
    fallback.acomplete.assert_called_once()
    assert any(entry.get("node") == "llm_text_fallback" for entry in LogService._buffers["novel-fallback"])
    assert any(entry.get("node") == "llm_fallback" for entry in LogService._buffers["novel-fallback"])


@pytest.mark.asyncio
async def test_call_and_parse_model_falls_back_to_json_text_when_tool_payload_missing():
    mock_client = AsyncMock()
    mock_client.config = TaskConfig(provider="anthropic", model="primary")
    mock_client.acomplete.side_effect = [
        LLMResponse(text="", finish_reason="end_turn"),
        LLMResponse(text='{"title": "文本模式", "tags": ["稳定"]}', finish_reason="end_turn"),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent",
            "text_fallback_task",
            "prompt",
            ExamplePayload,
            max_retries=3,
            novel_id="novel-text-fallback",
        )

    assert result.title == "文本模式"
    assert mock_client.acomplete.call_count == 2
    first_config = mock_client.acomplete.call_args_list[0].kwargs["config"]
    second_config = mock_client.acomplete.call_args_list[1].kwargs["config"]
    assert first_config.response_tool_name == "emit_text_fallback_task"
    assert second_config.response_tool_name is None
    assert second_config.response_json_schema is None
    assert any(entry.get("node") == "llm_text_fallback" for entry in LogService._buffers["novel-text-fallback"])


@pytest.mark.asyncio
async def test_call_and_parse_model_json_text_config_does_not_request_tool():
    mock_client = AsyncMock()
    mock_client.config = TaskConfig(
        provider="anthropic",
        model="json-text-model",
        structured_output=StructuredOutputConfig(mode="json_text"),
    )
    mock_client.acomplete.return_value = LLMResponse(
        text='{"title": "文本结构化", "tags": ["稳定"]}',
        finish_reason="end_turn",
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent",
            "json_text_task",
            "prompt",
            ExamplePayload,
            max_retries=3,
            novel_id="novel-json-text",
        )

    assert result.title == "文本结构化"
    call_config = mock_client.acomplete.call_args.kwargs["config"]
    assert call_config.structured_output.mode == "json_text"
    assert call_config.response_tool_name is None
    assert call_config.response_json_schema is None


@pytest.mark.asyncio
async def test_call_and_parse_model_stops_before_llm_call_when_cancel_requested():
    request_cancel("novel-cancel")
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text='{"title": "主线", "tags": ["成长"]}')

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        with pytest.raises(FlowCancelledError):
            await call_and_parse_model(
                "TestAgent",
                "test_task",
                "prompt",
                ExamplePayload,
                max_retries=3,
                novel_id="novel-cancel",
            )

    mock_client.acomplete.assert_not_called()
