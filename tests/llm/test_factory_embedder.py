import pytest
from novel_dev.llm.factory import LLMFactory
from novel_dev.llm.exceptions import LLMConfigError


class FakeSettings:
    llm_config_path = "tests/fixtures/test_embed_config.yaml"
    anthropic_api_key = "fake"
    minimax_api_key = "fake"
    openai_api_key = "fake"
    moonshot_api_key = "fake"
    zhipu_api_key = "fake"
    llm_user_agent = None


def test_factory_get_embedder_returns_embedder():
    factory = LLMFactory(settings=FakeSettings())
    embedder = factory.get_embedder()
    assert embedder is not None
    assert embedder.model == "text-embedding-3-small"
    assert embedder.dimensions == 1536


def test_factory_get_embedder_missing_config_raises():
    class FakeSettingsNoEmbed:
        llm_config_path = "tests/fixtures/test_no_embed_config.yaml"
        anthropic_api_key = "fake"
        minimax_api_key = "fake"
        openai_api_key = "fake"
        moonshot_api_key = "fake"
        zhipu_api_key = "fake"
        llm_user_agent = None

    factory = LLMFactory(settings=FakeSettingsNoEmbed())
    with pytest.raises(LLMConfigError, match="Missing 'embedding' configuration"):
        factory.get_embedder()
