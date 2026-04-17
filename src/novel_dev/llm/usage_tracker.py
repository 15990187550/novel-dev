import logging
from typing import Any, Optional, Protocol

from novel_dev.llm.models import TokenUsage

logger = logging.getLogger(__name__)


class UsageTracker(Protocol):
    async def log(
        self,
        agent: str,
        task: Optional[str],
        usage: Optional[TokenUsage],
        **kwargs: Any,
    ) -> None:
        ...


class LoggingUsageTracker:
    async def log(
        self,
        agent: str,
        task: Optional[str],
        usage: Optional[TokenUsage],
        **kwargs: Any,
    ) -> None:
        extra = {"agent": agent, "task": task}
        if usage:
            extra["usage"] = usage.model_dump()
        if kwargs:
            extra["meta"] = kwargs
        logger.info("llm_usage", extra=extra)
