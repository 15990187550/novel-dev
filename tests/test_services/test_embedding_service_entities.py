import pytest
from unittest.mock import AsyncMock

from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository


@pytest.mark.asyncio
async def test_index_entity_flattens_state_and_updates(async_session):
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    entity = await entity_repo.create(
        entity_id="ent_1",
        entity_type="character",
        name="张三",
        novel_id="n1",
    )
    await version_repo.create(
        entity_id="ent_1",
        version=1,
        state={"age": 25, "personality": {"trait1": "brave", "trait2": "kind"}},
    )

    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    svc = EmbeddingService(async_session, mock_embedder)
    await svc.index_entity("ent_1")

    mock_embedder.aembed.assert_awaited_once()
    call_args = mock_embedder.aembed.call_args[0][0][0]
    assert "名称：张三" in call_args
    assert "类型：character" in call_args
    assert "age：25" in call_args
    assert "personality：trait1=brave, trait2=kind" in call_args

    updated = await entity_repo.get_by_id("ent_1")
    assert updated.vector_embedding == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_index_entity_missing_entity_silently_returns(async_session):
    mock_embedder = AsyncMock()
    svc = EmbeddingService(async_session, mock_embedder)
    await svc.index_entity("nonexistent")
    mock_embedder.aembed.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_similar_entities(async_session):
    entity_repo = EntityRepository(async_session)
    await entity_repo.create(
        entity_id="ent_1",
        entity_type="character",
        name="主角",
        novel_id="n1",
    )
    version_repo = EntityVersionRepository(async_session)
    await version_repo.create(
        entity_id="ent_1",
        version=1,
        state={"description": "hero"},
    )

    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[1.0, 0.0]])
    svc = EmbeddingService(async_session, mock_embedder)

    # Seed the vector via index_entity
    await svc.index_entity("ent_1")

    results = await svc.search_similar_entities("n1", "hero", limit=3)
    assert len(results) == 1
    assert results[0].doc_id == "ent_1"
    assert results[0].title == "主角"


@pytest.mark.asyncio
async def test_flatten_entity_state_nested_dict():
    text = EmbeddingService._flatten_entity_state(
        "测试", "item", {"level": {"hp": 100, "mp": 50}, "rarity": "legendary"}
    )
    assert "名称：测试" in text
    assert "类型：item" in text
    assert "level：hp=100, mp=50" in text
    assert "rarity：legendary" in text
