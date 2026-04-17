import os
import pytest
from unittest.mock import MagicMock, patch

from novel_dev.config import Settings
from novel_dev.llm.exceptions import LLMConfigError
from novel_dev.llm.factory import LLMFactory
from novel_dev.llm.fallback_driver import FallbackDriver


@pytest.fixture
def temp_yaml(tmp_path):
    path = tmp_path / "llm_config.yaml"
    path.write_text("""
defaults:
  provider: openai_compatible
  model: gpt-4
  timeout: 30
  retries: 2

agents:
  test_agent:
    provider: anthropic
    model: claude-opus-4-6
    timeout: 120
    retries: 3
    fallback:
      provider: openai_compatible
      model: gpt-4.1
      base_url: https://api.openai.com/v1
      timeout: 60
      retries: 2
    tasks:
      special_task:
        model: claude-sonnet
        timeout: 60
""")
    return str(path)


def test_resolve_config_fallback_to_defaults(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak", openai_api_key="ok")
    factory = LLMFactory(settings)
    cfg = factory._resolve_config("unknown_agent", None)
    assert cfg.provider == "openai_compatible"
    assert cfg.model == "gpt-4"


def test_resolve_config_agent_level(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak", openai_api_key="ok")
    factory = LLMFactory(settings)
    cfg = factory._resolve_config("test_agent", None)
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-opus-4-6"
    assert cfg.retries == 3
    assert cfg.fallback is not None
    assert cfg.fallback.model == "gpt-4.1"


def test_resolve_config_task_level(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak", openai_api_key="ok")
    factory = LLMFactory(settings)
    cfg = factory._resolve_config("test_agent", "special_task")
    assert cfg.model == "claude-sonnet"
    assert cfg.timeout == 60
    assert cfg.retries == 3  # inherited from agent level
    assert cfg.fallback is not None
    assert cfg.fallback.model == "gpt-4.1"


def test_missing_api_key_raises(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml)
    factory = LLMFactory(settings)
    with pytest.raises(LLMConfigError, match="anthropic_api_key"):
        factory.get("test_agent")


def test_factory_returns_fallback_driver_when_fallback_configured(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak", openai_api_key="ok")
    factory = LLMFactory(settings)
    driver = factory.get("test_agent")
    assert isinstance(driver, FallbackDriver)


def test_factory_caches_drivers(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak", openai_api_key="ok")
    factory = LLMFactory(settings)
    d1 = factory._get_cached_driver(factory._resolve_config("test_agent", None))
    d2 = factory._get_cached_driver(factory._resolve_config("test_agent", None))
    assert d1 is d2


def test_factory_returns_retryable_driver_without_fallback(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak", openai_api_key="ok")
    factory = LLMFactory(settings)
    from novel_dev.llm.factory import RetryableDriver
    driver = factory.get("unknown_agent")
    assert isinstance(driver, RetryableDriver)
    assert not isinstance(driver, FallbackDriver)
