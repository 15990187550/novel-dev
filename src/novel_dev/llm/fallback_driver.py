from typing import List, Optional, Union

from novel_dev.llm.drivers.base import BaseDriver
from novel_dev.llm.exceptions import LLMError, LLMConfigError
from novel_dev.llm.models import ChatMessage, LLMResponse, TaskConfig


class FallbackDriver(BaseDriver):
    def __init__(
        self,
        primary: BaseDriver,
        fallback: Optional[BaseDriver],
        fallback_config: Optional[TaskConfig] = None,
    ):
        self.primary = primary
        self.fallback = fallback
        self.fallback_config = fallback_config

    async def acomplete(self, messages: Union[str, List[ChatMessage]], config: TaskConfig) -> LLMResponse:
        try:
            return await self.primary.acomplete(messages, config)
        except LLMConfigError:
            raise
        except LLMError:
            if self.fallback is None:
                raise
            fallback_config = self.fallback_config or config
            return await self.fallback.acomplete(messages, fallback_config)
