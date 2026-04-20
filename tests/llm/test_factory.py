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
  timeout: 30
  retries: 2
  temperature: 0.7

models:
  gpt-4:
    provider: openai_compatible
    model: gpt-4
    base_url: https://api.openai.com/v1
  claude-opus:
    provider: anthropic
    model: claude-opus-4-6

agents:
  test_agent:
    model: claude-opus
    timeout: 120
    retries: 3
    fallback:
      model: gpt-4
      timeout: 60
      retries: 2
    tasks:
      special_task:
        model: claude-opus
        timeout: 60
  no_fallback_agent:
    model: gpt-4
    timeout: 30
""")
    return str(path)


def test_resolve_config_unknown_profile_raises(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak")
    factory = LLMFactory(settings)
    factory._config["agents"]["bad_agent"] = {"model": "nonexistent"}
    with pytest.raises(LLMConfigError, match="Unknown model profile"):
        factory._resolve_config("bad_agent", None)


def test_resolve_config_agent_level(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak")
    factory = LLMFactory(settings)
    cfg = factory._resolve_config("test_agent", None)
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-opus-4-6"
    assert cfg.retries == 3
    assert cfg.fallback is not None
    assert cfg.fallback.model == "gpt-4"


def test_resolve_config_task_level(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak")
    factory = LLMFactory(settings)
    cfg = factory._resolve_config("test_agent", "special_task")
    assert cfg.model == "claude-opus-4-6"
    assert cfg.timeout == 60
    assert cfg.retries == 3  # inherited from agent level
    assert cfg.fallback is not None
    assert cfg.fallback.model == "gpt-4"


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
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak")
    factory = LLMFactory(settings)
    d1 = factory._get_cached_driver(factory._resolve_config("test_agent", None))
    d2 = factory._get_cached_driver(factory._resolve_config("test_agent", None))
    assert d1 is d2


def test_factory_returns_retryable_driver_without_fallback(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak", openai_api_key="ok")
    factory = LLMFactory(settings)
    from novel_dev.llm.factory import RetryableDriver
    driver = factory.get("no_fallback_agent")
    assert isinstance(driver, RetryableDriver)
    assert not isinstance(driver, FallbackDriver)
