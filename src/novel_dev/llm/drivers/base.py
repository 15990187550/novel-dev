from abc import ABC, abstractmethod
from typing import List, Union

from novel_dev.llm.models import LLMResponse, TaskConfig


class BaseDriver(ABC):
    @abstractmethod
    async def acomplete(
        self,
        messages: Union[str, List],
        config: TaskConfig,
    ) -> LLMResponse:
        """
        Accepts either a plain string (auto-wrapped as user message)
        or a list of ChatMessage, and returns a normalized LLMResponse.
        """
