import pytest
from unittest.mock import AsyncMock

from novel_dev.llm.exceptions import LLMConfigError, LLMRateLimitError, LLMTimeoutError
from novel_dev.llm.factory import RetryableDriver
from novel_dev.llm.models import LLMResponse, RetryConfig, TaskConfig


@pytest.mark.asyncio
async def test_retryable_driver_retries_on_rate_limit():
    inner = AsyncMock()
    inner.acomplete.side_effect = [
        LLMRateLimitError("rate limit"),
        LLMResponse(text="ok"),
    ]
    driver = RetryableDriver(inner, RetryConfig(retries=2, timeout=30))
    config = TaskConfig(provider="anthropic", model="claude-opus-4-6")
    response = await driver.acomplete("hi", config)
    assert response.text == "ok"
    assert inner.acomplete.call_count == 2


@pytest.mark.asyncio
async def test_retryable_driver_no_retry_on_config_error():
    inner = AsyncMock()
    inner.acomplete.side_effect = LLMConfigError("bad config")
    driver = RetryableDriver(inner, RetryConfig(retries=3, timeout=30))
    config = TaskConfig(provider="anthropic", model="claude-opus-4-6")
    with pytest.raises(LLMConfigError):
        await driver.acomplete("hi", config)
    assert inner.acomplete.call_count == 1
