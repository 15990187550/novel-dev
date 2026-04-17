import asyncio
import logging
from typing import List, Optional, Union

from novel_dev.llm.drivers.base import BaseDriver
from novel_dev.llm.exceptions import LLMError, LLMConfigError
from novel_dev.llm.models import ChatMessage, LLMResponse, TaskConfig
from novel_dev.llm.usage_tracker import UsageTracker

logger = logging.getLogger(__name__)


class FallbackDriver(BaseDriver):
    def __init__(
        self,
        primary: BaseDriver,
        fallback: Optional[BaseDriver],
        fallback_config: Optional[TaskConfig] = None,
        usage_tracker: Optional[UsageTracker] = None,
        agent: Optional[str] = None,
        task: Optional[str] = None,
    ):
        self.primary = primary
        self.fallback = fallback
        self.fallback_config = fallback_config
        self.usage_tracker = usage_tracker
        self.agent = agent
        self.task = task

    async def acomplete(self, messages: Union[str, List[ChatMessage]], config: TaskConfig) -> LLMResponse:
        try:
            return await self.primary.acomplete(messages, config)
        except LLMConfigError:
            raise
        except LLMError as exc:
            if self.fallback is None:
                raise
            if self.fallback_config is None:
                raise
            fallback_config = self.fallback_config
            if self.usage_tracker:
                async def _log():
                    try:
                        await self.usage_tracker.log(
                            agent=self.agent,
                            task=self.task,
                            usage=None,
                            meta={"event": "fallback_triggered", "reason": str(exc)},
                        )
                    except Exception as log_exc:
                        logger.warning("llm_fallback_tracking_failed", extra={"error": str(log_exc)})
                asyncio.create_task(_log())
            return await self.fallback.acomplete(messages, fallback_config)
