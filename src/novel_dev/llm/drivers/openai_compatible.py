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

        try:
            resp = await self.client.chat.completions.create(
                model=config.model,
                messages=msgs,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=config.timeout,
            )
        except Exception as exc:
            raise self._map_exception(exc) from exc

        content = resp.choices[0].message.content or ""
        usage = None
        if resp.usage:
            usage = TokenUsage(
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                total_tokens=resp.usage.total_tokens,
            )
        return LLMResponse(text=content, usage=usage)

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
