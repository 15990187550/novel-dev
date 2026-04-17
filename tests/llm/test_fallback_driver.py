import pytest
from unittest.mock import AsyncMock

from novel_dev.llm.exceptions import LLMConfigError, LLMRateLimitError, LLMTimeoutError
from novel_dev.llm.fallback_driver import FallbackDriver
from novel_dev.llm.models import LLMResponse, TaskConfig


@pytest.mark.asyncio
async def test_fallback_triggered_on_rate_limit():
    primary = AsyncMock()
    primary.acomplete.side_effect = LLMRateLimitError("rate limit")
    fallback = AsyncMock()
    fallback.acomplete.return_value = LLMResponse(text="fallback ok")
    driver = FallbackDriver(primary, fallback, TaskConfig(provider="openai", model="gpt-4"))
    response = await driver.acomplete("hi", TaskConfig(provider="anthropic", model="claude"))
    assert response.text == "fallback ok"
    assert primary.acomplete.call_count == 1
    assert fallback.acomplete.call_count == 1


@pytest.mark.asyncio
async def test_fallback_not_triggered_on_config_error():
    primary = AsyncMock()
    primary.acomplete.side_effect = LLMConfigError("bad key")
    fallback = AsyncMock()
    driver = FallbackDriver(primary, fallback, TaskConfig(provider="openai", model="gpt-4"))
    with pytest.raises(LLMConfigError):
        await driver.acomplete("hi", TaskConfig(provider="anthropic", model="claude"))
    assert fallback.acomplete.call_count == 0


@pytest.mark.asyncio
async def test_no_fallback_raises_original_error():
    primary = AsyncMock()
    primary.acomplete.side_effect = LLMTimeoutError("timeout")
    driver = FallbackDriver(primary, None, None)
    with pytest.raises(LLMTimeoutError):
        await driver.acomplete("hi", TaskConfig(provider="anthropic", model="claude"))


@pytest.mark.asyncio
async def test_primary_success_no_fallback_call():
    primary = AsyncMock()
    primary.acomplete.return_value = LLMResponse(text="primary ok")
    fallback = AsyncMock()
    driver = FallbackDriver(primary, fallback, TaskConfig(provider="openai", model="gpt-4"))
    response = await driver.acomplete("hi", TaskConfig(provider="anthropic", model="claude"))
    assert response.text == "primary ok"
    assert fallback.acomplete.call_count == 0


@pytest.mark.asyncio
async def test_fallback_triggered_on_content_policy_error():
    from novel_dev.llm.exceptions import LLMContentPolicyError
    primary = AsyncMock()
    primary.acomplete.side_effect = LLMContentPolicyError("blocked")
    fallback = AsyncMock()
    fallback.acomplete.return_value = LLMResponse(text="fallback ok")
    driver = FallbackDriver(primary, fallback, TaskConfig(provider="openai", model="gpt-4"))
    response = await driver.acomplete("hi", TaskConfig(provider="anthropic", model="claude"))
    assert response.text == "fallback ok"


@pytest.mark.asyncio
async def test_fallback_raises_when_fallback_config_none():
    primary = AsyncMock()
    primary.acomplete.side_effect = LLMRateLimitError("rate limit")
    fallback = AsyncMock()
    fallback.acomplete.return_value = LLMResponse(text="fallback ok")
    driver = FallbackDriver(primary, fallback, fallback_config=None)
    incoming_config = TaskConfig(provider="anthropic", model="claude", temperature=0.5)
    with pytest.raises(LLMRateLimitError):
        await driver.acomplete("hi", incoming_config)
    fallback.acomplete.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_failure_propagates():
    primary = AsyncMock()
    primary.acomplete.side_effect = LLMTimeoutError("timeout")
    fallback = AsyncMock()
    fallback.acomplete.side_effect = LLMRateLimitError("fallback also failed")
    driver = FallbackDriver(primary, fallback, TaskConfig(provider="openai", model="gpt-4"))
    with pytest.raises(LLMRateLimitError):
        await driver.acomplete("hi", TaskConfig(provider="anthropic", model="claude"))
