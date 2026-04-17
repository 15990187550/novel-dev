import pytest
from unittest.mock import MagicMock, patch

from novel_dev.llm.models import TokenUsage
from novel_dev.llm.usage_tracker import LoggingUsageTracker


@pytest.mark.asyncio
async def test_logging_usage_tracker_logs_info():
    tracker = LoggingUsageTracker()
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    with patch("novel_dev.llm.usage_tracker.logger") as mock_logger:
        await tracker.log(agent="brainstorm_agent", task="generate_synopsis", usage=usage)
    mock_logger.info.assert_called_once()
    call_args = mock_logger.info.call_args
    assert call_args[1]["extra"]["agent"] == "brainstorm_agent"
    assert call_args[1]["extra"]["usage"]["total_tokens"] == 15
