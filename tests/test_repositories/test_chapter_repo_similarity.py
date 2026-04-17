import pytest

from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.db.models import Chapter


@pytest.mark.asyncio
async def test_similarity_search_sqlite_fallback_ranking(async_session):
    repo = ChapterRepository(async_session)
    # Create chapters with different embeddings
    c1 = Chapter(id="c1", volume_id="v1", chapter_number=1, title="First",
                 novel_id="n1", vector_embedding=[1.0, 0.0, 0.0])
    c2 = Chapter(id="c2", volume_id="v1", chapter_number=2, title="Second",
                 novel_id="n1", vector_embedding=[0.0, 1.0, 0.0])
    c3 = Chapter(id="c3", volume_id="v1", chapter_number=3, title="Third",
                 novel_id="n1", vector_embedding=[0.9, 0.1, 0.0])
    async_session.add_all([c1, c2, c3])
    await async_session.flush()

    query = [1.0, 0.0, 0.0]
    results = await repo.similarity_search("n1", query, limit=2)

    assert len(results) == 2
    # c1 and c3 should be top 2, with c1 first (exact match)
    assert results[0].doc_id == "c1"
    assert results[0].similarity_score == pytest.approx(1.0, abs=1e-6)
    assert results[1].doc_id == "c3"


@pytest.mark.asyncio
async def test_similarity_search_empty_result(async_session):
    repo = ChapterRepository(async_session)
    results = await repo.similarity_search("n1", [1.0, 0.0, 0.0], limit=5)
    assert results == []


@pytest.mark.asyncio
async def test_similarity_search_excludes_other_novels(async_session):
    repo = ChapterRepository(async_session)
    c1 = Chapter(id="c1", volume_id="v1", chapter_number=1, title="First",
                 novel_id="n1", vector_embedding=[1.0, 0.0, 0.0])
    c2 = Chapter(id="c2", volume_id="v1", chapter_number=2, title="Second",
                 novel_id="n2", vector_embedding=[1.0, 0.0, 0.0])
    async_session.add_all([c1, c2])
    await async_session.flush()

    query = [1.0, 0.0, 0.0]
    results = await repo.similarity_search("n1", query, limit=5)

    assert len(results) == 1
    assert results[0].doc_id == "c1"


@pytest.mark.asyncio
async def test_similarity_search_content_preview_from_polished_text(async_session):
    repo = ChapterRepository(async_session)
    polished = "a" * 250
    raw = "b" * 250
    c1 = Chapter(id="c1", volume_id="v1", chapter_number=1, title="My Chapter",
                 novel_id="n1", polished_text=polished, raw_draft=raw,
                 vector_embedding=[1.0, 0.0, 0.0])
    async_session.add(c1)
    await async_session.flush()

    query = [1.0, 0.0, 0.0]
    results = await repo.similarity_search("n1", query, limit=5)

    assert len(results) == 1
    assert results[0].content_preview == polished[:200]
    assert results[0].title == "My Chapter"
    assert results[0].doc_type == "chapter"
