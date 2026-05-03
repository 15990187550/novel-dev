import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from novel_dev.db.models import NovelDocument, Entity, Chapter, EntityVersion
from novel_dev.scripts.backfill_embeddings import BackfillService
from novel_dev.services.embedding_service import EmbeddingService


@pytest.mark.asyncio
async def test_backfill_documents():
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])

    embedding_service = EmbeddingService(mock_session, mock_embedder)
    backfill = BackfillService(mock_session, embedding_service, batch_size=10)

    doc1 = MagicMock(spec=NovelDocument)
    doc1.id = "doc_1"
    doc1.content = "content a"
    doc1.vector_embedding = None
    doc2 = MagicMock(spec=NovelDocument)
    doc2.id = "doc_2"
    doc2.content = "content b"
    doc2.vector_embedding = None

    backfill._fetch_unembedded_documents = AsyncMock(return_value=[doc1, doc2])

    count = await backfill.backfill_documents()
    assert count == 2
    assert doc1.vector_embedding == [0.1, 0.2, 0.3]
    assert doc2.vector_embedding == [0.4, 0.5, 0.6]
    mock_embedder.aembed.assert_awaited_once_with(["content a", "content b"])
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_backfill_documents_filters_by_novel_id():
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    embedding_service = EmbeddingService(mock_session, mock_embedder)
    backfill = BackfillService(mock_session, embedding_service, batch_size=10)

    doc1 = MagicMock(spec=NovelDocument)
    doc1.id = "doc_1"
    doc1.content = "content a"
    doc1.vector_embedding = None

    backfill._fetch_unembedded_documents = AsyncMock(return_value=[doc1])

    count = await backfill.backfill_documents(novel_id="n1")
    assert count == 1
    backfill._fetch_unembedded_documents.assert_awaited_once_with("n1")


@pytest.mark.asyncio
async def test_backfill_documents_skips_already_embedded():
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.9, 0.9, 0.9]])

    embedding_service = EmbeddingService(mock_session, mock_embedder)
    backfill = BackfillService(mock_session, embedding_service, batch_size=10)

    doc1 = MagicMock(spec=NovelDocument)
    doc1.id = "doc_1"
    doc1.content = "content a"
    doc1.vector_embedding = [0.1, 0.2, 0.3]
    doc2 = MagicMock(spec=NovelDocument)
    doc2.id = "doc_2"
    doc2.content = "content b"
    doc2.vector_embedding = None

    backfill._fetch_unembedded_documents = AsyncMock(return_value=[doc2])

    count = await backfill.backfill_documents()
    assert count == 1
    assert doc2.vector_embedding == [0.9, 0.9, 0.9]
    mock_embedder.aembed.assert_awaited_once_with(["content b"])


@pytest.mark.asyncio
async def test_backfill_documents_empty_content_skipped():
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[])

    embedding_service = EmbeddingService(mock_session, mock_embedder)
    backfill = BackfillService(mock_session, embedding_service, batch_size=10)

    doc = MagicMock(spec=NovelDocument)
    doc.id = "doc_1"
    doc.content = ""
    doc.vector_embedding = None

    backfill._fetch_unembedded_documents = AsyncMock(return_value=[doc])

    count = await backfill.backfill_documents()
    assert count == 0
    # No embedding generated because content is empty
    assert doc.vector_embedding is None
    mock_embedder.aembed.assert_not_awaited()


def test_has_embedding_handles_pgvector_array():
    class VectorLike:
        def __len__(self):
            return 3

        def __bool__(self):
            raise ValueError("ambiguous")

    assert BackfillService._has_embedding(VectorLike()) is True
    assert BackfillService._has_embedding([]) is False
    assert BackfillService._has_embedding(None) is False


@pytest.mark.asyncio
async def test_backfill_documents_fallback_on_batch_failure():
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_embedder = AsyncMock()
    # First call (batch) fails, second call (single via index_document) succeeds
    mock_embedder.aembed = AsyncMock(side_effect=[
        Exception("batch failed"),
        [[0.1, 0.2, 0.3]],
    ])

    embedding_service = EmbeddingService(mock_session, mock_embedder)
    backfill = BackfillService(mock_session, embedding_service, batch_size=10)

    doc = MagicMock(spec=NovelDocument)
    doc.id = "doc_1"
    doc.content = "content a"
    doc.vector_embedding = None

    backfill._fetch_unembedded_documents = AsyncMock(return_value=[doc])
    async def index_document(doc_id):
        assert doc_id == "doc_1"
        doc.vector_embedding = [0.1, 0.2, 0.3]

    embedding_service.index_document = AsyncMock(side_effect=index_document)

    count = await backfill.backfill_documents()
    assert count == 1
    assert doc.vector_embedding == [0.1, 0.2, 0.3]
    assert mock_embedder.aembed.await_count == 1
    embedding_service.index_document.assert_awaited_once_with("doc_1")


@pytest.mark.asyncio
async def test_backfill_entities():
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    embedding_service = EmbeddingService(mock_session, mock_embedder)
    backfill = BackfillService(mock_session, embedding_service, batch_size=10)

    entity = MagicMock(spec=Entity)
    entity.id = "e1"
    entity.name = "林风"
    entity.type = "character"
    entity.vector_embedding = None

    backfill._fetch_unembedded_entities = AsyncMock(return_value=[entity])

    with patch(
        "novel_dev.scripts.backfill_embeddings.EntityVersionRepository.get_latest",
        new=AsyncMock(return_value=EntityVersion(state={"身份": "剑修"})),
    ):
        count = await backfill.backfill_entities()
    assert count == 1
    assert entity.vector_embedding == [0.1, 0.2, 0.3]
    call_args = mock_embedder.aembed.call_args[0][0]
    assert len(call_args) == 1
    assert "名称：林风" in call_args[0]
    assert "类型：character" in call_args[0]
    assert "身份：剑修" in call_args[0]


@pytest.mark.asyncio
async def test_backfill_entities_no_version():
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    embedding_service = EmbeddingService(mock_session, mock_embedder)
    backfill = BackfillService(mock_session, embedding_service, batch_size=10)

    entity = MagicMock(spec=Entity)
    entity.id = "e1"
    entity.name = "林风"
    entity.type = "character"
    entity.vector_embedding = None

    backfill._fetch_unembedded_entities = AsyncMock(return_value=[entity])

    with patch(
        "novel_dev.scripts.backfill_embeddings.EntityVersionRepository.get_latest",
        new=AsyncMock(return_value=None),
    ):
        count = await backfill.backfill_entities()
    assert count == 1
    assert entity.vector_embedding == [0.1, 0.2, 0.3]
    call_args = mock_embedder.aembed.call_args[0][0]
    assert "名称：林风" in call_args[0]


@pytest.mark.asyncio
async def test_backfill_entity_search():
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    embedding_service = EmbeddingService(mock_session, mock_embedder)
    backfill = BackfillService(mock_session, embedding_service, batch_size=10)

    entity = MagicMock(spec=Entity)
    entity.id = "e1"
    entity.name = "林风"
    entity.type = "character"
    entity.manual_category = None
    entity.system_category = "人物"
    entity.system_needs_review = False
    entity.search_vector_embedding = None
    entity.search_document = None

    backfill._fetch_unembedded_entity_search = AsyncMock(return_value=[entity])

    with patch(
        "novel_dev.scripts.backfill_embeddings.EntityVersionRepository.get_latest",
        new=AsyncMock(return_value=EntityVersion(state={"身份": "剑修"})),
    ):
        count = await backfill.backfill_entity_search()

    assert count == 1
    assert entity.search_vector_embedding == [0.1, 0.2, 0.3]
    assert "名称：林风" in entity.search_document
    assert "一级分类：人物" in entity.search_document


@pytest.mark.asyncio
async def test_backfill_chapters():
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    embedding_service = EmbeddingService(mock_session, mock_embedder)
    backfill = BackfillService(mock_session, embedding_service, batch_size=10)

    ch = MagicMock(spec=Chapter)
    ch.id = "ch1"
    ch.polished_text = "这是一段 polished 文本。"
    ch.raw_draft = None
    ch.vector_embedding = None

    backfill._fetch_unembedded_chapters = AsyncMock(return_value=[ch])

    count = await backfill.backfill_chapters()
    assert count == 1
    assert ch.vector_embedding == [0.1, 0.2, 0.3]
    call_args = mock_embedder.aembed.call_args[0][0]
    assert call_args[0] == "这是一段 polished 文本。"


@pytest.mark.asyncio
async def test_backfill_chapters_uses_raw_draft_fallback():
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    embedding_service = EmbeddingService(mock_session, mock_embedder)
    backfill = BackfillService(mock_session, embedding_service, batch_size=10)

    ch = MagicMock(spec=Chapter)
    ch.id = "ch1"
    ch.polished_text = None
    ch.raw_draft = "这是一段 raw draft 文本。"
    ch.vector_embedding = None

    backfill._fetch_unembedded_chapters = AsyncMock(return_value=[ch])

    count = await backfill.backfill_chapters()
    assert count == 1
    assert ch.vector_embedding == [0.1, 0.2, 0.3]
    call_args = mock_embedder.aembed.call_args[0][0]
    assert call_args[0] == "这是一段 raw draft 文本。"


@pytest.mark.asyncio
async def test_backfill_all():
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    embedding_service = EmbeddingService(mock_session, mock_embedder)
    backfill = BackfillService(mock_session, embedding_service, batch_size=10)

    doc = MagicMock(spec=NovelDocument)
    doc.id = "doc_1"
    doc.content = "doc content"
    doc.vector_embedding = None
    entity = MagicMock(spec=Entity)
    entity.id = "e1"
    entity.name = "林风"
    entity.type = "character"
    entity.vector_embedding = None
    entity.manual_category = None
    entity.system_category = "人物"
    entity.system_needs_review = False
    entity.search_vector_embedding = None
    entity.search_document = None
    ch = MagicMock(spec=Chapter)
    ch.id = "ch1"
    ch.polished_text = "chapter text"
    ch.raw_draft = None
    ch.vector_embedding = None

    backfill._fetch_unembedded_documents = AsyncMock(return_value=[doc])
    backfill._fetch_unembedded_entities = AsyncMock(return_value=[entity])
    backfill._fetch_unembedded_entity_search = AsyncMock(return_value=[entity])
    backfill._fetch_unembedded_chapters = AsyncMock(return_value=[ch])

    with patch(
        "novel_dev.scripts.backfill_embeddings.EntityVersionRepository.get_latest",
        new=AsyncMock(return_value=None),
    ):
        counts = await backfill.backfill_all()
    assert counts["documents"] == 1
    assert counts["entities"] == 1
    assert counts["entity_search"] == 1
    assert counts["chapters"] == 1
