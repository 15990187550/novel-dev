from abc import ABC, abstractmethod

from openai import AsyncOpenAI


class BaseEmbedder(ABC):
    @abstractmethod
    async def aembed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder(BaseEmbedder):
    def __init__(self, client: AsyncOpenAI, model: str, dimensions: int):
        self.client = client
        self.model = model
        self.dimensions = dimensions

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = await self.client.embeddings.create(
                model=self.model, input=texts, dimensions=self.dimensions
            )
        except Exception as exc:
            raise self._map_exception(exc) from exc
        return [item.embedding for item in resp.data]

    def _map_exception(self, exc: Exception) -> Exception:
        import openai
        import httpx

        if isinstance(exc, openai.RateLimitError):
            from novel_dev.llm.exceptions import LLMRateLimitError

            return LLMRateLimitError(str(exc))
        if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
            from novel_dev.llm.exceptions import LLMTimeoutError

            return LLMTimeoutError(str(exc))
        if isinstance(exc, httpx.TimeoutException):
            from novel_dev.llm.exceptions import LLMTimeoutError

            return LLMTimeoutError(str(exc))
        return exc
