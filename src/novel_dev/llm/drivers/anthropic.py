from typing import List, Optional, Union

from anthropic import AsyncAnthropic

from novel_dev.llm.drivers.base import BaseDriver
from novel_dev.llm.exceptions import (
    LLMConfigError,
    LLMContentPolicyError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from novel_dev.llm.models import ChatMessage, LLMResponse, TaskConfig, TokenUsage


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

        try:
            resp = await self.client.messages.create(
                model=config.model,
                messages=msgs,
                system=system,
                max_tokens=config.max_tokens or 4096,
                temperature=config.temperature,
                timeout=config.timeout,
            )
        except Exception as exc:
            raise self._map_exception(exc) from exc

        content = resp.content[0].text if resp.content else ""
        usage = None
        if resp.usage:
            usage = TokenUsage(
                prompt_tokens=resp.usage.input_tokens,
                completion_tokens=resp.usage.output_tokens,
                total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
            )
        return LLMResponse(text=content, usage=usage)

    def _map_exception(self, exc: Exception) -> Exception:
        import anthropic
        import httpx

        if isinstance(exc, anthropic.RateLimitError):
            return LLMRateLimitError(str(exc))
        if isinstance(exc, (anthropic.APITimeoutError, anthropic.APIConnectionError)):
            return LLMTimeoutError(str(exc))
        if isinstance(exc, anthropic.AuthenticationError):
            return LLMConfigError(str(exc))
        if isinstance(exc, anthropic.PermissionDeniedError):
            return LLMContentPolicyError(str(exc))
        if isinstance(exc, httpx.TimeoutException):
            return LLMTimeoutError(str(exc))
        return exc
