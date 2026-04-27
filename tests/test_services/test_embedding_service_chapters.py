import pytest
from unittest.mock import AsyncMock
from types import SimpleNamespace

from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.repositories.chapter_repo import ChapterRepository


@pytest.mark.asyncio
async def test_index_chapter_polished_text(async_session):
    repo = ChapterRepository(async_session)
    ch = await repo.create(
        chapter_id="ch_1",
        volume_id="vol_1",
        chapter_number=1,
        title="Test Chapter",
    )
    await repo.update_text(chapter_id="ch_1", polished_text="polished content here")

    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    svc = EmbeddingService(async_session, mock_embedder)
    await svc.index_chapter("ch_1")

    mock_embedder.aembed.assert_awaited_once_with(["polished content here"])
    updated = await repo.get_by_id("ch_1")
    assert updated.vector_embedding == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_index_chapter_fallback_to_raw_draft(async_session):
    repo = ChapterRepository(async_session)
    ch = await repo.create(
        chapter_id="ch_2",
        volume_id="vol_1",
        chapter_number=2,
        title="Draft Chapter",
    )
    await repo.update_text(chapter_id="ch_2", raw_draft="raw draft content")

    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.4, 0.5, 0.6]])
    svc = EmbeddingService(async_session, mock_embedder)
    await svc.index_chapter("ch_2")

    mock_embedder.aembed.assert_awaited_once_with(["raw draft content"])
    updated = await repo.get_by_id("ch_2")
    assert updated.vector_embedding == [0.4, 0.5, 0.6]


@pytest.mark.asyncio
async def test_index_chapter_skips_wrong_dimension_vector_on_postgres(async_session, monkeypatch):
    repo = ChapterRepository(async_session)
    await repo.create(
        chapter_id="ch_wrong_dim",
        volume_id="vol_1",
        chapter_number=20,
        title="Wrong Dimension",
    )
    await repo.update_text(chapter_id="ch_wrong_dim", raw_draft="raw draft content")

    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1] * 1536])
    monkeypatch.setattr(
        async_session,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
    )

    svc = EmbeddingService(async_session, mock_embedder)
    await svc.index_chapter("ch_wrong_dim")

    updated = await repo.get_by_id("ch_wrong_dim")
    assert updated.vector_embedding is None


@pytest.mark.asyncio
async def test_index_chapter_missing_silently_returns(async_session):
    mock_embedder = AsyncMock()
    svc = EmbeddingService(async_session, mock_embedder)
    await svc.index_chapter("nonexistent")
    mock_embedder.aembed.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_similar_chapters(async_session):
    repo = ChapterRepository(async_session)
    ch = await repo.create(
        chapter_id="ch_3",
        volume_id="vol_1",
        chapter_number=3,
        title="Searchable Chapter",
    )
    # Set novel_id directly on the model since create() doesn't accept it
    ch.novel_id = "n1"
    await repo.update_text(chapter_id="ch_3", polished_text="hero saves the day")

    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[1.0, 0.0]])
    svc = EmbeddingService(async_session, mock_embedder)

    # Seed the vector via index_chapter
    await svc.index_chapter("ch_3")

    results = await svc.search_similar_chapters("n1", "hero", limit=3)
    assert len(results) == 1
    assert results[0].doc_id == "ch_3"
    assert results[0].title == "Searchable Chapter"


@pytest.mark.asyncio
async def test_search_similar_chapters_skips_wrong_dimension_query_on_postgres(async_session, monkeypatch):
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1] * 1536])
    monkeypatch.setattr(
        async_session,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
    )

    svc = EmbeddingService(async_session, mock_embedder)
    results = await svc.search_similar_chapters("n1", "hero", limit=3)

    assert results == []
