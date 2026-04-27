import json
from typing import List, Optional, Union

from openai import AsyncOpenAI

from novel_dev.llm.drivers.base import BaseDriver
from novel_dev.llm.exceptions import (
    LLMConfigError,
    LLMContentPolicyError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from novel_dev.llm.models import ChatMessage, LLMResponse, TaskConfig, TokenUsage


class OpenAICompatibleDriver(BaseDriver):
    def __init__(self, client: Optional[AsyncOpenAI] = None):
        self._client = client

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            raise RuntimeError("OpenAICompatibleDriver client not initialized")
        return self._client

    async def acomplete(self, messages: Union[str, List[ChatMessage]], config: TaskConfig) -> LLMResponse:
        if isinstance(messages, str):
            msgs = [{"role": "user", "content": messages}]
        else:
            msgs = [{"role": m.role, "content": m.content} for m in messages]

        request_kwargs = {
            "model": config.model,
            "messages": msgs,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "timeout": config.timeout,
        }
        if config.response_tool_name and config.response_json_schema:
            request_kwargs["tools"] = [{
                "type": "function",
                "function": {
                    "name": config.response_tool_name,
                    "description": "Return the requested structured payload.",
                    "parameters": config.response_json_schema,
                },
            }]
            request_kwargs["tool_choice"] = {"type": "function", "function": {"name": config.response_tool_name}}

        try:
            resp = await self.client.chat.completions.create(**request_kwargs)
        except Exception as exc:
            raise self._map_exception(exc) from exc

        choice = resp.choices[0]
        message = choice.message
        content = message.content or ""
        structured_payload = None
        tool_calls = getattr(message, "tool_calls", None) or []
        if config.response_tool_name and tool_calls:
            arguments = getattr(tool_calls[0].function, "arguments", "")
            if arguments:
                structured_payload = json.loads(arguments)
        usage = None
        if resp.usage:
            usage = TokenUsage(
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                total_tokens=resp.usage.total_tokens,
            )
        finish_reason = getattr(choice, "finish_reason", None)
        if not isinstance(finish_reason, str):
            finish_reason = None
        return LLMResponse(
            text=content,
            usage=usage,
            structured_payload=structured_payload,
            finish_reason=finish_reason,
        )

    def _map_exception(self, exc: Exception) -> Exception:
        import openai
        import httpx

        if isinstance(exc, openai.RateLimitError):
            return LLMRateLimitError(str(exc))
        if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
            return LLMTimeoutError(str(exc))
        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return LLMConfigError(str(exc))
        if isinstance(exc, openai.BadRequestError):
            msg = str(exc).lower()
            if "content_policy" in msg or "safety" in msg or "moderation" in msg:
                return LLMContentPolicyError(str(exc))
        if isinstance(exc, httpx.TimeoutException):
            return LLMTimeoutError(str(exc))
        return exc
