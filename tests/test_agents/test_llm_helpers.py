import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from novel_dev.agents._llm_helpers import (
    _await_llm_response_with_progress,
    call_and_parse,
    call_and_parse_model,
    register_structured_normalizer,
)
from novel_dev.llm.fallback_driver import FallbackDriver
from novel_dev.llm.models import LLMResponse, StructuredOutputConfig, TaskConfig
from novel_dev.services.flow_control_service import FlowCancelledError, clear_cancel_request, request_cancel
from novel_dev.services.log_service import LogService


class ExamplePayload(BaseModel):
    title: str
    tags: list[str] = []


class DummyLLMClient:
    def __init__(
        self,
        *,
        agent: str = "ConfigAgent",
        task: str = "config_task",
        config: TaskConfig | None = None,
        response: LLMResponse | None = None,
        primary=None,
        fallback=None,
    ):
        self.agent = agent
        self.task = task
        self.config = config
        self.response = response or LLMResponse(text='{"title": "主线", "tags": ["成长"]}')
        self.primary = primary
        self.fallback = fallback
        self.calls = []

    async def acomplete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.response


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
async def test_call_and_parse_model_can_inherit_config_from_another_agent():
    mock_client = AsyncMock()
    mock_client.agent = "VolumePlannerAgent"
    mock_client.task = "generate_volume_plan"
    mock_client.config = TaskConfig(provider="anthropic", model="volume-model")
    mock_client.acomplete.return_value = LLMResponse(
        text="",
        structured_payload={"title": "澄清结果", "tags": ["继承配置"]},
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "OutlineClarificationAgent",
            "outline_clarify",
            "prompt",
            ExamplePayload,
            max_retries=1,
            novel_id="novel-config-alias",
            context_metadata={"purpose": "clarification"},
            config_agent_name="VolumePlannerAgent",
            config_task="generate_volume_plan",
        )

    assert result.title == "澄清结果"
    mock_factory.get.assert_called_once_with("VolumePlannerAgent", task="generate_volume_plan")
    call_kwargs = mock_client.acomplete.call_args.kwargs
    assert call_kwargs["config"].response_tool_name == "emit_outline_clarify"
    assert mock_client.agent == "OutlineClarificationAgent"
    assert mock_client.task == "outline_clarify"

    entries = LogService._buffers["novel-config-alias"]
    assert any(
        entry.get("agent") == "OutlineClarificationAgent"
        and entry.get("task") == "outline_clarify"
        and entry.get("metadata", {}).get("purpose") == "clarification"
        for entry in entries
    )


@pytest.mark.asyncio
async def test_call_and_parse_model_retags_nested_usage_identity_for_config_inheritance():
    primary = DummyLLMClient(agent="VolumePlannerAgent", task="generate_volume_plan")
    fallback = DummyLLMClient(agent="VolumePlannerAgent", task="generate_volume_plan")
    client = DummyLLMClient(
        agent="VolumePlannerAgent",
        task="generate_volume_plan",
        config=TaskConfig(provider="anthropic", model="volume-model"),
        response=LLMResponse(text="", structured_payload={"title": "澄清结果", "tags": ["继承配置"]}),
        primary=primary,
        fallback=fallback,
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = client
        result = await call_and_parse_model(
            "OutlineClarificationAgent",
            "outline_clarify",
            "prompt",
            ExamplePayload,
            max_retries=1,
            config_agent_name="VolumePlannerAgent",
            config_task="generate_volume_plan",
        )

    assert result.title == "澄清结果"
    assert client.agent == "OutlineClarificationAgent"
    assert client.task == "outline_clarify"
    assert primary.agent == "OutlineClarificationAgent"
    assert primary.task == "outline_clarify"
    assert fallback.agent == "OutlineClarificationAgent"
    assert fallback.task == "outline_clarify"


@pytest.mark.asyncio
async def test_call_and_parse_model_uses_config_identity_for_text_fallback():
    mock_client = AsyncMock()
    mock_client.config = None
    mock_client.acomplete.return_value = LLMResponse(
        text='{"title": "文本结果", "tags": ["继承配置"]}',
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "OutlineClarificationAgent",
            "outline_clarify",
            "prompt",
            ExamplePayload,
            max_retries=1,
            novel_id="novel-config-text-alias",
            context_metadata={"purpose": "text fallback"},
            config_agent_name="BrainstormAgent",
            config_task="generate_synopsis",
        )

    assert result.title == "文本结果"
    assert result.tags == ["继承配置"]
    mock_factory.get.assert_called_once_with("BrainstormAgent", task="generate_synopsis")

    entries = LogService._buffers["novel-config-text-alias"]
    assert any(
        entry.get("agent") == "OutlineClarificationAgent"
        and entry.get("task") == "outline_clarify"
        and entry.get("metadata", {}).get("purpose") == "text fallback"
        for entry in entries
    )


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
    prompt = "prompt-" + ("很长的提示" * 80)

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent",
            "test_task",
            prompt,
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
    started = next(entry for entry in entries if entry.get("status") == "started")
    metadata = started["metadata"]
    assert metadata["prompt_chars"] == len(prompt)
    assert metadata["prompt"] == prompt
    assert len(metadata["prompt_preview"]) <= 300
    assert metadata["prompt_preview"] != prompt
    succeeded = next(entry for entry in entries if entry.get("status") == "succeeded")
    assert succeeded["metadata"]["output_source"] == "text"
    assert "finish_reason" in succeeded["metadata"]


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
async def test_call_and_parse_model_falls_back_to_json_text_when_tool_payload_is_empty_dict():
    mock_client = AsyncMock()
    mock_client.config = TaskConfig(provider="anthropic", model="primary")
    markdown_score = "### plot_tension - 80/100\n理由: 有推进, 但不是 JSON。"
    mock_client.acomplete.side_effect = [
        LLMResponse(text=markdown_score, structured_payload={}, finish_reason="end_turn"),
        LLMResponse(text='{"title": "文本模式", "tags": ["稳定"]}', finish_reason="end_turn"),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        result = await call_and_parse_model(
            "TestAgent",
            "empty_payload_task",
            "prompt",
            ExamplePayload,
            max_retries=3,
            novel_id="novel-empty-payload",
        )

    assert result.title == "文本模式"
    assert mock_client.acomplete.call_count == 2
    first_config = mock_client.acomplete.call_args_list[0].kwargs["config"]
    second_config = mock_client.acomplete.call_args_list[1].kwargs["config"]
    assert first_config.response_tool_name == "emit_empty_payload_task"
    assert second_config.response_tool_name is None
    assert second_config.response_json_schema is None
    assert any(entry.get("node") == "llm_text_fallback" for entry in LogService._buffers["novel-empty-payload"])


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


@pytest.mark.asyncio
async def test_waiting_llm_response_stops_when_cancel_requested():
    cancelled = False

    async def never_returns():
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise

    wait_task = asyncio.create_task(
        _await_llm_response_with_progress(
            never_returns(),
            novel_id="novel-cancel",
            agent_name="TestAgent",
            task="test_task",
            attempt_metadata={},
            started_at=0.0,
            interval_seconds=0.01,
        )
    )
    await asyncio.sleep(0.02)
    request_cancel("novel-cancel")

    with pytest.raises(FlowCancelledError):
        await asyncio.wait_for(wait_task, timeout=0.2)
    assert cancelled is True


@pytest.mark.asyncio
async def test_call_and_parse_stops_during_retry_backoff():
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text="invalid json"),
        LLMResponse(text='{"title": "主线", "tags": ["成长"]}'),
    ]

    def parser(text):
        import json
        payload = json.loads(text)
        return ExamplePayload.model_validate(payload)

    original_log_llm_event = __import__(
        "novel_dev.agents._llm_helpers",
        fromlist=["_log_llm_event"],
    )._log_llm_event

    def cancel_after_parse_failure(*args, **kwargs):
        original_log_llm_event(*args, **kwargs)
        if kwargs.get("status") == "failed" and kwargs.get("node") == "llm_parse":
            request_cancel("novel-cancel")

    started_at = time.perf_counter()
    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        with patch("novel_dev.agents._llm_helpers._log_llm_event", side_effect=cancel_after_parse_failure):
            with pytest.raises(FlowCancelledError):
                await call_and_parse(
                    "TestAgent",
                    "test_task",
                    "prompt",
                    parser,
                    max_retries=3,
                    novel_id="novel-cancel",
                )

    assert time.perf_counter() - started_at < 0.5
    assert mock_client.acomplete.call_count == 1
