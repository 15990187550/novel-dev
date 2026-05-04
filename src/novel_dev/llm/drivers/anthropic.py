from typing import List, Optional, Union

from anthropic import AsyncAnthropic

from novel_dev.llm.drivers.base import BaseDriver
from novel_dev.llm.exceptions import (
    LLMConfigError,
    LLMContentPolicyError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from novel_dev.llm.models import ChatMessage, LLMResponse, LLMToolCall, TaskConfig, TokenUsage


class AnthropicDriver(BaseDriver):
    def __init__(self, client: Optional[AsyncAnthropic] = None):
        self._client = client

    @property
    def client(self) -> AsyncAnthropic:
        if self._client is None:
            raise RuntimeError("AnthropicDriver client not initialized")
        return self._client

    async def acomplete(self, messages: Union[str, List[ChatMessage]], config: TaskConfig) -> LLMResponse:
        if isinstance(messages, str):
            msgs = [{"role": "user", "content": messages}]
            system = None
        else:
            system_msgs = [m.content for m in messages if m.role == "system"]
            system = "\n\n".join(system_msgs) if system_msgs else None
            msgs = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]

        request_kwargs = {
            "model": config.model,
            "messages": msgs,
            "system": system,
            "max_tokens": config.max_tokens or 4096,
            "temperature": config.temperature,
            "timeout": config.timeout,
        }
        tools = []
        if config.response_tool_name and config.response_json_schema:
            tools.append({
                "name": config.response_tool_name,
                "description": "Return the requested structured payload.",
                "input_schema": config.response_json_schema,
            })
        for tool in config.capability_tools:
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            })
        if tools:
            request_kwargs["tools"] = tools
            tool_choice = "force"
            if config.structured_output:
                tool_choice = config.structured_output.tool_choice
            if tool_choice == "force" and config.response_tool_name:
                request_kwargs["tool_choice"] = {"type": "tool", "name": config.response_tool_name}
            elif tool_choice == "auto":
                request_kwargs["tool_choice"] = {"type": "auto"}

        try:
            resp = await self.client.messages.create(**request_kwargs)
        except Exception as exc:
            raise self._map_exception(exc) from exc

        # Filter for TextBlock only (skip ThinkingBlock)
        text_blocks = [c for c in resp.content if hasattr(c, "text")]
        content = text_blocks[0].text if text_blocks else ""
        structured_payload = None
        tool_calls: list[LLMToolCall] = []
        for block in resp.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            name = getattr(block, "name", None)
            if name == config.response_tool_name:
                structured_payload = getattr(block, "input", None)
            elif name:
                tool_calls.append(LLMToolCall(
                    id=getattr(block, "id", None),
                    name=name,
                    arguments=getattr(block, "input", None) or {},
                ))
        usage = None
        if resp.usage:
            usage = TokenUsage(
                prompt_tokens=resp.usage.input_tokens,
                completion_tokens=resp.usage.output_tokens,
                total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
            )
        finish_reason = getattr(resp, "stop_reason", None)
        if not isinstance(finish_reason, str):
            finish_reason = None
        return LLMResponse(
            text=content,
            usage=usage,
            structured_payload=structured_payload,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
        )

    def _map_exception(self, exc: Exception) -> Exception:
        import anthropic
        import httpx
        overloaded_error = getattr(anthropic, "OverloadedError", None)

        if isinstance(exc, anthropic.RateLimitError):
            return LLMRateLimitError(str(exc))
        if overloaded_error is not None and isinstance(exc, overloaded_error):
            return LLMRateLimitError(str(exc))
        status_code = getattr(exc, "status_code", None)
        if status_code == 402:
            return LLMRateLimitError(str(exc))
        if isinstance(exc, (anthropic.APITimeoutError, anthropic.APIConnectionError)):
            return LLMTimeoutError(str(exc))
        if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return LLMConfigError(str(exc))
        if isinstance(exc, httpx.TimeoutException):
            return LLMTimeoutError(str(exc))
        return exc
