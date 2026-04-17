import pytest

from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.db.models import Entity


@pytest.mark.asyncio
async def test_similarity_search_sqlite_fallback_ranking(async_session):
    repo = EntityRepository(async_session)
    # Create entities with different embeddings
    e1 = Entity(id="e1", type="character", name="Alice", novel_id="n1", vector_embedding=[1.0, 0.0, 0.0])
    e2 = Entity(id="e2", type="character", name="Bob", novel_id="n1", vector_embedding=[0.0, 1.0, 0.0])
    e3 = Entity(id="e3", type="character", name="Charlie", novel_id="n1", vector_embedding=[0.9, 0.1, 0.0])
    async_session.add_all([e1, e2, e3])
    await async_session.flush()

    query = [1.0, 0.0, 0.0]
    results = await repo.similarity_search("n1", query, limit=2)

    assert len(results) == 2
    # e1 and e3 should be top 2, with e1 first (exact match)
    assert results[0].doc_id == "e1"
    assert results[0].similarity_score == pytest.approx(1.0, abs=1e-6)
    assert results[1].doc_id == "e3"
    assert results[1].similarity_score > results[2].similarity_score if len(results) > 2 else True


@pytest.mark.asyncio
async def test_similarity_search_type_filter(async_session):
    repo = EntityRepository(async_session)
    e1 = Entity(id="e1", type="character", name="Alice", novel_id="n1", vector_embedding=[1.0, 0.0, 0.0])
    e2 = Entity(id="e2", type="location", name="Beach", novel_id="n1", vector_embedding=[1.0, 0.0, 0.0])
    async_session.add_all([e1, e2])
    await async_session.flush()

    query = [1.0, 0.0, 0.0]
    results = await repo.similarity_search("n1", query, limit=5, type_filter="character")

    assert len(results) == 1
    assert results[0].doc_id == "e1"
    assert results[0].doc_type == "character"


@pytest.mark.asyncio
async def test_similarity_search_empty_result(async_session):
    repo = EntityRepository(async_session)
    results = await repo.similarity_search("n1", [1.0, 0.0, 0.0], limit=5)
    assert results == []


@pytest.mark.asyncio
async def test_similarity_search_excludes_other_novels(async_session):
    repo = EntityRepository(async_session)
    e1 = Entity(id="e1", type="character", name="Alice", novel_id="n1", vector_embedding=[1.0, 0.0, 0.0])
    e2 = Entity(id="e2", type="character", name="Bob", novel_id="n2", vector_embedding=[1.0, 0.0, 0.0])
    async_session.add_all([e1, e2])
    await async_session.flush()

    query = [1.0, 0.0, 0.0]
    results = await repo.similarity_search("n1", query, limit=5)

    assert len(results) == 1
    assert results[0].doc_id == "e1"
