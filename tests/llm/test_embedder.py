import pytest
from unittest.mock import AsyncMock

from novel_dev.llm.models import EmbeddingConfig
from novel_dev.llm.embedder import BaseEmbedder, OpenAIEmbedder


def test_embedding_config_defaults():
    cfg = EmbeddingConfig(provider="openai", model="text-embedding-3-small")
    assert cfg.provider == "openai"
    assert cfg.model == "text-embedding-3-small"
    assert cfg.base_url is None
    assert cfg.timeout == 30
    assert cfg.retries == 3
    assert cfg.dimensions == 1024


def test_embedding_config_custom():
    cfg = EmbeddingConfig(
        provider="openai",
        model="text-embedding-3-small",
        base_url="https://custom.example.com",
        timeout=60,
        retries=5,
        dimensions=768,
    )
    assert cfg.base_url == "https://custom.example.com"
    assert cfg.timeout == 60
    assert cfg.retries == 5
    assert cfg.dimensions == 768


@pytest.mark.asyncio
async def test_openai_embedder_empty_input():
    mock_client = AsyncMock()
    embedder = OpenAIEmbedder(
        client=mock_client, model="text-embedding-3-small", dimensions=1024
    )
    result = await embedder.aembed([])
    assert result == []
    mock_client.embeddings.create.assert_not_called()


@pytest.mark.asyncio
async def test_openai_embedder_single_text():
    mock_client = AsyncMock()
    mock_item = AsyncMock()
    mock_item.embedding = [0.1, 0.2, 0.3]
    mock_resp = AsyncMock()
    mock_resp.data = [mock_item]
    mock_client.embeddings.create.return_value = mock_resp

    embedder = OpenAIEmbedder(
        client=mock_client, model="text-embedding-3-small", dimensions=3
    )
    result = await embedder.aembed(["hello world"])

    assert result == [[0.1, 0.2, 0.3]]
    mock_client.embeddings.create.assert_awaited_once_with(
        model="text-embedding-3-small",
        input=["hello world"],
        dimensions=3,
    )


@pytest.mark.asyncio
async def test_openai_embedder_multiple_texts():
    mock_client = AsyncMock()
    mock_item1 = AsyncMock()
    mock_item1.embedding = [0.1, 0.2]
    mock_item2 = AsyncMock()
    mock_item2.embedding = [0.3, 0.4]
    mock_resp = AsyncMock()
    mock_resp.data = [mock_item1, mock_item2]
    mock_client.embeddings.create.return_value = mock_resp

    embedder = OpenAIEmbedder(
        client=mock_client, model="text-embedding-3-small", dimensions=2
    )
    result = await embedder.aembed(["hello", "world"])

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    mock_client.embeddings.create.assert_awaited_once_with(
        model="text-embedding-3-small",
        input=["hello", "world"],
        dimensions=2,
    )


def test_base_embedder_is_abstract():
    with pytest.raises(TypeError):
        BaseEmbedder()
