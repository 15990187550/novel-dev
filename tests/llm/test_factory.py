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
    structured_output:
      mode: openai_tool
      fallback_to_text: true
  claude-opus:
    provider: anthropic
    model: claude-opus-4-6
    structured_output:
      mode: anthropic_tool
      fallback_to_text: true
  deepseek:
    provider: anthropic
    model: deepseek-v4-flash
    base_url: https://api.deepseek.com/anthropic
    structured_output:
      mode: anthropic_tool
      tool_choice: auto
      fallback_to_text: true

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
  deepseek_agent:
    model: deepseek
    timeout: 120
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
    assert cfg.structured_output.mode == "anthropic_tool"
    assert cfg.fallback.structured_output.mode == "openai_tool"


def test_resolve_config_task_level(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak")
    factory = LLMFactory(settings)
    cfg = factory._resolve_config("test_agent", "special_task")
    assert cfg.model == "claude-opus-4-6"
    assert cfg.timeout == 60
    assert cfg.retries == 3  # inherited from agent level
    assert cfg.fallback is not None
    assert cfg.fallback.model == "gpt-4"


def test_resolve_orchestration_config_from_task_level(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak")
    factory = LLMFactory(settings)
    factory._config["agents"]["test_agent"]["tasks"]["special_task"]["orchestration"] = {
        "tool_allowlist": ["get_novel_state", "get_novel_documents"],
        "max_tool_calls": 2,
        "tool_timeout_seconds": 1.5,
        "max_tool_result_chars": 1200,
        "enable_subtasks": True,
        "retriever_subtasks": ["context_retriever"],
        "validator_subtask": "semantic",
        "repairer_subtask": "semantic_repair",
    }

    cfg = factory.resolve_orchestration_config("TestAgent", "special_task")

    assert cfg is not None
    assert cfg.tool_allowlist == ["get_novel_state", "get_novel_documents"]
    assert cfg.max_tool_calls == 2
    assert cfg.tool_timeout_seconds == 1.5
    assert cfg.max_tool_result_chars == 1200
    assert cfg.allow_writes is False
    assert cfg.enable_subtasks is True
    assert cfg.retriever_subtasks == ["context_retriever"]
    assert cfg.validator_subtask == "semantic"
    assert cfg.repairer_subtask == "semantic_repair"


def test_resolve_orchestration_config_returns_none_when_unconfigured(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak")
    factory = LLMFactory(settings)

    assert factory.resolve_orchestration_config("TestAgent", "special_task") is None


def test_resolve_orchestration_config_allows_subtask_only_config(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak")
    factory = LLMFactory(settings)
    factory._config["agents"]["test_agent"]["tasks"]["special_task"]["orchestration"] = {
        "enabled": True,
        "enable_subtasks": True,
        "repairer_subtask": "schema_repair",
    }

    cfg = factory.resolve_orchestration_config("TestAgent", "special_task")

    assert cfg is not None
    assert cfg.tool_allowlist == []
    assert cfg.enable_subtasks is True
    assert cfg.repairer_subtask == "schema_repair"


def test_default_llm_config_resolves_context_agent_orchestration():
    settings = Settings(llm_config_path="llm_config.yaml", anthropic_api_key="ak")
    factory = LLMFactory(settings)

    cfg = factory.resolve_orchestration_config("ContextAgent", "build_scene_context")

    assert cfg is not None
    assert cfg.tool_allowlist == [
        "get_context_location_details",
        "get_context_entity_states",
        "get_context_foreshadowing_details",
        "get_context_timeline_events",
        "get_novel_state",
        "get_chapter_draft_status",
    ]
    assert cfg.max_tool_calls == 20
    assert cfg.max_tool_result_chars == 3200
    assert cfg.enable_subtasks is True
    assert cfg.validator_subtask == "location_context_quality"
    assert cfg.repairer_subtask == "schema_repair"


def test_resolve_config_preserves_auto_tool_choice(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak")
    factory = LLMFactory(settings)
    cfg = factory._resolve_config("deepseek_agent", None)
    assert cfg.model == "deepseek-v4-flash"
    assert cfg.structured_output.mode == "anthropic_tool"
    assert cfg.structured_output.tool_choice == "auto"


def test_missing_api_key_raises(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key=None)
    factory = LLMFactory(settings)
    with pytest.raises(LLMConfigError, match="anthropic_api_key"):
        factory.get("test_agent")


def test_resolve_api_key_prefers_profile_api_key_env(tmp_path, monkeypatch):
    config_path = tmp_path / "llm_config.yaml"
    config_path.write_text(
        "defaults:\n"
        "  timeout: 30\n"
        "models:\n"
        "  kimi:\n"
        "    provider: anthropic\n"
        "    model: kimi-test\n"
        "    base_url: https://api.kimi.com/coding\n"
        "    api_key_env: KIMI_API_KEY\n"
        "agents:\n"
        "  writer_agent:\n"
        "    model: kimi\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KIMI_API_KEY", "sk-env-kimi")

    from novel_dev.config import Settings
    from novel_dev.llm.factory import LLMFactory

    factory = LLMFactory(Settings(llm_config_path=str(config_path)))
    client = factory.get("writer_agent")

    assert client.config.api_key_env == "KIMI_API_KEY"
    assert factory._resolve_api_key("anthropic", "https://api.kimi.com/coding", client.config.model_dump()) == "sk-env-kimi"


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


def test_factory_reload_picks_up_saved_config_and_clears_cache(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak", openai_api_key="ok")
    factory = LLMFactory(settings)
    old_driver = factory._get_cached_driver(factory._resolve_config("test_agent", None))

    with open(temp_yaml, "w", encoding="utf-8") as f:
        f.write("""
defaults:
  timeout: 30
  retries: 2
  temperature: 0.7
models:
  gpt-4:
    provider: openai_compatible
    model: gpt-4
    base_url: https://api.openai.com/v1
agents:
  test_agent:
    model: gpt-4
    timeout: 45
""")

    factory.reload()

    cfg = factory._resolve_config("test_agent", None)
    new_driver = factory._get_cached_driver(cfg)
    assert cfg.provider == "openai_compatible"
    assert cfg.model == "gpt-4"
    assert cfg.timeout == 45
    assert new_driver is not old_driver


def test_writer_relay_task_uses_writer_primary_model():
    settings = Settings(llm_config_path="llm_config.yaml")
    factory = LLMFactory(settings)

    cfg = factory._resolve_config("WriterAgent", "generate_relay")

    assert cfg.model == "deepseek-v4-flash"
    assert cfg.fallback is not None
    assert cfg.fallback.model == "Minimax-2.7"


def test_critic_score_chapter_has_enough_output_budget():
    settings = Settings(llm_config_path="llm_config.yaml")
    factory = LLMFactory(settings)

    cfg = factory._resolve_config("CriticAgent", "score_chapter")

    assert cfg.max_tokens == 8192


def test_default_max_tokens_is_doubled_for_tasks_without_override():
    settings = Settings(llm_config_path="llm_config.yaml")
    factory = LLMFactory(settings)

    cfg = factory._resolve_config("WriterAgent", "generate_beat")

    assert cfg.max_tokens == 8192


def test_outline_workbench_synopsis_revision_has_bounded_timeout():
    settings = Settings(llm_config_path="llm_config.yaml")
    factory = LLMFactory(settings)

    cfg = factory._resolve_config("OutlineWorkbenchService", "revise_synopsis_with_feedback")

    assert cfg.timeout == 180
    assert cfg.retries == 1
    assert cfg.temperature == 0.5
    assert cfg.fallback is not None
    assert cfg.fallback.timeout == 120
    assert cfg.fallback.retries == 1
    assert cfg.fallback.temperature == 0.5
