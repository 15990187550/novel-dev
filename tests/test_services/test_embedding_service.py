import pytest
from unittest.mock import AsyncMock
from types import SimpleNamespace

from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.db.models import NovelDocument


@pytest.mark.asyncio
async def test_generate_embedding_truncates_long_text(async_session):
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    svc = EmbeddingService(async_session, mock_embedder, max_query_length=10)
    result = await svc.generate_embedding("hello world this is long")
    mock_embedder.aembed.assert_awaited_once_with(["hello worl"])
    assert result == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_index_document_reads_and_updates(async_session):
    repo = DocumentRepository(async_session)
    doc = await repo.create(
        doc_id="doc_1",
        novel_id="n1",
        doc_type="setting",
        title="Test",
        content="test content",
    )
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    svc = EmbeddingService(async_session, mock_embedder)
    await svc.index_document("doc_1")
    mock_embedder.aembed.assert_awaited_once_with(["test content"])
    updated = await repo.get_by_id("doc_1")
    assert updated.vector_embedding == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_index_document_missing_doc_silently_returns(async_session):
    mock_embedder = AsyncMock()
    svc = EmbeddingService(async_session, mock_embedder)
    await svc.index_document("nonexistent")
    mock_embedder.aembed.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_similar_generates_query_then_searches(async_session):
    doc = NovelDocument(
        id="doc_1",
        novel_id="n1",
        doc_type="setting",
        title="A",
        content="content",
        vector_embedding=[1.0, 0.0],
        version=1,
    )
    async_session.add(doc)
    await async_session.flush()
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[1.0, 0.0]])
    svc = EmbeddingService(async_session, mock_embedder)
    results = await svc.search_similar("n1", "query text", limit=3)
    mock_embedder.aembed.assert_awaited_once_with(["query text"])
    assert len(results) == 1
    assert results[0].doc_id == "doc_1"


@pytest.mark.asyncio
async def test_search_similar_skips_wrong_dimension_query_on_postgres(async_session, monkeypatch):
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1] * 1536])
    monkeypatch.setattr(
        async_session,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
    )

    svc = EmbeddingService(async_session, mock_embedder)
    results = await svc.search_similar("n1", "query text", limit=3)

    assert results == []
