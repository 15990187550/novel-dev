from typing import List, Optional, Union

from openai import AsyncOpenAI

from novel_dev.llm.drivers.base import BaseDriver
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

        resp = await self.client.chat.completions.create(
            model=config.model,
            messages=msgs,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.timeout,
        )
        content = resp.choices[0].message.content or ""
        usage = None
        if resp.usage:
            usage = TokenUsage(
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                total_tokens=resp.usage.total_tokens,
            )
        return LLMResponse(text=content, usage=usage)
