import logging
from typing import Optional, Protocol

from novel_dev.llm.models import TokenUsage

logger = logging.getLogger(__name__)


class UsageTracker(Protocol):
    async def log(self, agent: str, task: Optional[str], usage: TokenUsage) -> None:
        ...


class LoggingUsageTracker:
    async def log(self, agent: str, task: Optional[str], usage: TokenUsage) -> None:
        logger.info(
            "llm_usage",
            extra={"agent": agent, "task": task, "usage": usage.model_dump()},
        )
