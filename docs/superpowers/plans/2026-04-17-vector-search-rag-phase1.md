# Vector Search & RAG Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build embedding infrastructure, vector similarity search for NovelDocument, and integrate semantic retrieval into ContextAgent/WriterAgent with explicit prompt guidance.

**Architecture:** Add a cross-cutting embedding layer (BaseEmbedder → OpenAIEmbedder → EmbeddingService) that generates vectors from document content and enables cosine-similarity search. ContextAgent uses semantic search to augment (not replace) exact-type queries. WriterAgent consumes retrieved documents through an explicit prompt section with guiding instructions.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 (async), pgvector, OpenAI SDK (AsyncOpenAI), Pydantic v2, pytest-asyncio

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/novel_dev/llm/embedder.py` | `BaseEmbedder` ABC and `OpenAIEmbedder` implementation (batch text → vectors) |
| `src/novel_dev/schemas/similar_document.py` | `SimilarDocument` Pydantic model for search results |
| `src/novel_dev/services/embedding_service.py` | `EmbeddingService` — orchestrates embedding generation, indexing, and similarity search |
| `migrations/versions/20260417_xxxx_enable_pgvector.py` | Alembic migration to `CREATE EXTENSION IF NOT EXISTS vector` |
| `tests/llm/test_embedder.py` | Tests for `OpenAIEmbedder` |
| `tests/llm/test_factory_embedder.py` | Tests for `LLMFactory.get_embedder()` |
| `tests/test_schemas/test_similar_document.py` | Tests for `SimilarDocument` schema |
| `tests/test_repositories/test_document_repo_similarity.py` | Tests for `DocumentRepository.similarity_search()` (SQLite fallback + mock PG) |
| `tests/test_services/test_embedding_service.py` | Tests for `EmbeddingService` |
| `tests/test_agents/test_context_agent_semantic.py` | Tests for ContextAgent with mock EmbeddingService |
| `tests/test_agents/test_writer_agent_relevant_docs.py` | Tests for WriterAgent prompt construction with `relevant_documents` |

### Modified Files

| File | Changes |
|------|---------|
| `src/novel_dev/llm/models.py` | Add `EmbeddingConfig` Pydantic model |
| `src/novel_dev/llm/factory.py` | Add `get_embedder()` method; import `EmbeddingConfig`, `OpenAIEmbedder` |
| `src/novel_dev/llm/__init__.py` | Export `BaseEmbedder` |
| `src/novel_dev/repositories/document_repo.py` | Remove `vector_embedding` param from `create()`; add `similarity_search()` |
| `src/novel_dev/schemas/context.py` | Add `relevant_documents: List[SimilarDocument]` to `ChapterContext` |
| `src/novel_dev/agents/context_agent.py` | Add optional `embedding_service` param; integrate semantic search in `assemble()`; add `_build_search_query()` |
| `src/novel_dev/agents/writer_agent.py` | Add `relevant_docs_text` block in `_generate_beat()` and `_rewrite_angle()` prompts |
| `src/novel_dev/api/routes.py` | Inject `EmbeddingService` when constructing `ContextAgent` |
| `src/novel_dev/mcp_server/server.py` | Inject `EmbeddingService` when constructing `ContextAgent` |
| `llm_config.yaml` | Add `embedding:` configuration section |

---

## Task 1: EmbeddingConfig Model + BaseEmbedder + OpenAIEmbedder

**Files:**
- Modify: `src/novel_dev/llm/models.py`
- Create: `src/novel_dev/llm/embedder.py`
- Test: `tests/llm/test_embedder.py`

- [ ] **Step 1: Write the failing test**

Create `tests/llm/test_embedder.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_dev.llm.embedder import OpenAIEmbedder


@pytest.mark.asyncio
async def test_openai_embedder_single_text():
    mock_client = MagicMock()
    mock_client.embeddings.create = AsyncMock(return_value=MagicMock(
        data=[MagicMock(embedding=[0.1, 0.2, 0.3])]
    ))

    embedder = OpenAIEmbedder(client=mock_client, model="text-embedding-3-small", dimensions=3)
    result = await embedder.aembed(["hello world"])

    assert len(result) == 1
    assert result[0] == [0.1, 0.2, 0.3]
    mock_client.embeddings.create.assert_awaited_once_with(
        model="text-embedding-3-small",
        input=["hello world"],
        dimensions=3,
    )


@pytest.mark.asyncio
async def test_openai_embedder_batch_texts():
    mock_client = MagicMock()
    mock_client.embeddings.create = AsyncMock(return_value=MagicMock(
        data=[
            MagicMock(embedding=[0.1, 0.2]),
            MagicMock(embedding=[0.3, 0.4]),
        ]
    ))

    embedder = OpenAIEmbedder(client=mock_client, model="text-embedding-3-small", dimensions=2)
    result = await embedder.aembed(["text a", "text b"])

    assert len(result) == 2
    assert result[0] == [0.1, 0.2]
    assert result[1] == [0.3, 0.4]
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=src pytest tests/llm/test_embedder.py -v
```

Expected: `ModuleNotFoundError: No module named 'novel_dev.llm.embedder'`

- [ ] **Step 3: Add EmbeddingConfig to models.py**

Add to `src/novel_dev/llm/models.py` (after `RetryConfig` class):

```python
class EmbeddingConfig(BaseModel):
    provider: str
    model: str
    base_url: Optional[str] = None
    timeout: int = 30
    retries: int = 3
    dimensions: int = 1536
```

- [ ] **Step 4: Implement embedder.py**

Create `src/novel_dev/llm/embedder.py`:

```python
from abc import ABC, abstractmethod
from typing import List

from openai import AsyncOpenAI


class BaseEmbedder(ABC):
    @abstractmethod
    async def aembed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts. Returns one vector per input text."""
        ...


class OpenAIEmbedder(BaseEmbedder):
    def __init__(self, client: AsyncOpenAI, model: str, dimensions: int):
        self.client = client
        self.model = model
        self.dimensions = dimensions

    async def aembed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        resp = await self.client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions,
        )
        return [item.embedding for item in resp.data]
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
PYTHONPATH=src pytest tests/llm/test_embedder.py -v
```

Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/llm/models.py src/novel_dev/llm/embedder.py tests/llm/test_embedder.py
git commit -m "feat(embedder): add BaseEmbedder + OpenAIEmbedder with batch aembed"
```

---

## Task 2: LLMFactory.get_embedder()

**Files:**
- Modify: `src/novel_dev/llm/factory.py`
- Modify: `src/novel_dev/llm/__init__.py`
- Test: `tests/llm/test_factory_embedder.py`

- [ ] **Step 1: Write the failing test**

Create `tests/llm/test_factory_embedder.py`:

```python
import pytest
from novel_dev.llm.factory import LLMFactory
from novel_dev.llm.exceptions import LLMConfigError


class FakeSettings:
    llm_config_path = "tests/fixtures/test_embed_config.yaml"
    anthropic_api_key = "fake-anthropic-key"
    minimax_api_key = "fake-minimax-key"
    openai_api_key = "fake-openai-key"
    moonshot_api_key = "fake-moonshot-key"
    zhipu_api_key = "fake-zhipu-key"
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
```

Create `tests/fixtures/test_embed_config.yaml`:

```yaml
defaults:
  provider: openai_compatible

embedding:
  provider: openai_compatible
  model: text-embedding-3-small
  base_url: https://api.openai.com/v1
  timeout: 30
  retries: 3
  dimensions: 1536
```

Create `tests/fixtures/test_no_embed_config.yaml`:

```yaml
defaults:
  provider: openai_compatible
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=src pytest tests/llm/test_factory_embedder.py -v
```

Expected: `AttributeError: 'LLMFactory' object has no attribute 'get_embedder'`

- [ ] **Step 3: Add get_embedder() to LLMFactory**

Add to `src/novel_dev/llm/factory.py` (after `get()` method, before end of class):

```python
    def get_embedder(self) -> "BaseEmbedder":
        from novel_dev.llm.embedder import OpenAIEmbedder
        from novel_dev.llm.models import EmbeddingConfig

        raw = self._config.get("embedding", {})
        if not raw:
            raise LLMConfigError("Missing 'embedding' configuration in llm_config.yaml")

        config = EmbeddingConfig(**raw)
        key = self._resolve_api_key(config.provider, config.base_url)
        client = AsyncOpenAI(
            api_key=key,
            base_url=config.base_url,
            http_client=self._get_http_client(),
        )
        return OpenAIEmbedder(client=client, model=config.model, dimensions=config.dimensions)
```

Add import at top of `factory.py`:
```python
from novel_dev.llm.embedder import BaseEmbedder
```

(Note: use string annotation `"BaseEmbedder"` or add the import to avoid circular import issues.)

Actually, add the import near existing imports:
```python
from novel_dev.llm.embedder import BaseEmbedder
```

- [ ] **Step 4: Export BaseEmbedder from llm/__init__.py**

Modify `src/novel_dev/llm/__init__.py`:

```python
from novel_dev.llm.embedder import BaseEmbedder

__all__ = [
    ...
    "BaseEmbedder",
    ...
]
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
PYTHONPATH=src pytest tests/llm/test_factory_embedder.py -v
```

Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/llm/factory.py src/novel_dev/llm/__init__.py tests/llm/test_factory_embedder.py tests/fixtures/
git commit -m "feat(llm_factory): add get_embedder() for embedding model configuration"
```

---

## Task 3: SimilarDocument Schema + ChapterContext Update

**Files:**
- Create: `src/novel_dev/schemas/similar_document.py`
- Modify: `src/novel_dev/schemas/context.py`
- Test: `tests/test_schemas/test_similar_document.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_schemas/test_similar_document.py`:

```python
from novel_dev.schemas.similar_document import SimilarDocument


def test_similar_document_creation():
    doc = SimilarDocument(
        doc_id="doc_123",
        doc_type="setting",
        title="星辰学院",
        content_preview="位于大陆中央的魔法学院...",
        similarity_score=0.92,
    )
    assert doc.doc_id == "doc_123"
    assert doc.similarity_score == 0.92


def test_similar_document_defaults():
    doc = SimilarDocument(
        doc_id="doc_456",
        doc_type="worldview",
        title="世界观",
        content_preview="",
        similarity_score=0.0,
    )
    assert doc.content_preview == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=src pytest tests/test_schemas/test_similar_document.py -v
```

Expected: `ModuleNotFoundError: No module named 'novel_dev.schemas.similar_document'`

- [ ] **Step 3: Create SimilarDocument schema**

Create `src/novel_dev/schemas/similar_document.py`:

```python
from pydantic import BaseModel


class SimilarDocument(BaseModel):
    doc_id: str
    doc_type: str
    title: str
    content_preview: str
    similarity_score: float
```

- [ ] **Step 4: Update ChapterContext**

Modify `src/novel_dev/schemas/context.py`:

Add import:
```python
from novel_dev.schemas.similar_document import SimilarDocument
```

Modify `ChapterContext`:
```python
class ChapterContext(BaseModel):
    chapter_plan: ChapterPlan
    style_profile: dict
    worldview_summary: str
    active_entities: List[EntityState]
    location_context: LocationContext
    timeline_events: List[dict]
    pending_foreshadowings: List[dict]
    previous_chapter_summary: Optional[str] = None
    relevant_documents: List[SimilarDocument] = Field(default_factory=list)
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
PYTHONPATH=src pytest tests/test_schemas/test_similar_document.py tests/test_schemas/test_outline_schemas.py -v
```

Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/schemas/similar_document.py src/novel_dev/schemas/context.py tests/test_schemas/test_similar_document.py
git commit -m "feat(schemas): add SimilarDocument and relevant_documents to ChapterContext"
```

---

## Task 4: DocumentRepository.similarity_search()

**Files:**
- Modify: `src/novel_dev/repositories/document_repo.py`
- Test: `tests/test_repositories/test_document_repo_similarity.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_repositories/test_document_repo_similarity.py`:

```python
import pytest
import math
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.db.models import NovelDocument


@pytest.mark.asyncio
async def test_similarity_search_sqlite_fallback(async_session: AsyncSession):
    """SQLite has no pgvector operators; test Python-side cosine fallback."""
    repo = DocumentRepository(async_session)

    # Create documents with manual vector_embedding (JSON in SQLite)
    doc1 = NovelDocument(
        id="doc_1", novel_id="n1", doc_type="setting", title="A",
        content="content a", vector_embedding=[1.0, 0.0, 0.0], version=1,
    )
    doc2 = NovelDocument(
        id="doc_2", novel_id="n1", doc_type="worldview", title="B",
        content="content b", vector_embedding=[0.0, 1.0, 0.0], version=1,
    )
    doc3 = NovelDocument(
        id="doc_3", novel_id="n1", doc_type="concept", title="C",
        content="content c", vector_embedding=[0.5, 0.5, 0.0], version=1,
    )
    async_session.add_all([doc1, doc2, doc3])
    await async_session.flush()

    # Query vector aligns with doc1
    query = [1.0, 0.0, 0.0]
    results = await repo.similarity_search("n1", query, limit=2)

    assert len(results) == 2
    assert results[0].doc_id == "doc_1"
    assert results[0].similarity_score == pytest.approx(1.0, abs=0.01)
    assert results[1].doc_id == "doc_3"


@pytest.mark.asyncio
async def test_similarity_search_with_doc_type_filter(async_session: AsyncSession):
    repo = DocumentRepository(async_session)

    doc1 = NovelDocument(
        id="doc_1", novel_id="n1", doc_type="setting", title="A",
        content="content a", vector_embedding=[1.0, 0.0], version=1,
    )
    doc2 = NovelDocument(
        id="doc_2", novel_id="n1", doc_type="worldview", title="B",
        content="content b", vector_embedding=[1.0, 0.0], version=1,
    )
    async_session.add_all([doc1, doc2])
    await async_session.flush()

    results = await repo.similarity_search("n1", [1.0, 0.0], limit=5, doc_type_filter="setting")
    assert len(results) == 1
    assert results[0].doc_id == "doc_1"


@pytest.mark.asyncio
async def test_similarity_search_no_vectors_returns_empty(async_session: AsyncSession):
    repo = DocumentRepository(async_session)
    results = await repo.similarity_search("n1", [1.0, 0.0], limit=5)
    assert results == []


@pytest.mark.asyncio
async def test_similarity_search_excludes_other_novels(async_session: AsyncSession):
    repo = DocumentRepository(async_session)

    doc = NovelDocument(
        id="doc_1", novel_id="n2", doc_type="setting", title="A",
        content="content", vector_embedding=[1.0, 0.0], version=1,
    )
    async_session.add(doc)
    await async_session.flush()

    results = await repo.similarity_search("n1", [1.0, 0.0], limit=5)
    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=src pytest tests/test_repositories/test_document_repo_similarity.py -v
```

Expected: `AttributeError: 'DocumentRepository' object has no attribute 'similarity_search'`

- [ ] **Step 3: Implement similarity_search()**

Modify `src/novel_dev/repositories/document_repo.py`:

Add imports:
```python
import math
from sqlalchemy import text
from novel_dev.schemas.similar_document import SimilarDocument
```

Modify `create()` — remove `vector_embedding` parameter:
```python
    async def create(
        self,
        doc_id: str,
        novel_id: str,
        doc_type: str,
        title: str,
        content: str,
        version: int = 1,
    ) -> NovelDocument:
        doc = NovelDocument(
            id=doc_id,
            novel_id=novel_id,
            doc_type=doc_type,
            title=title,
            content=content,
            version=version,
        )
        self.session.add(doc)
        await self.session.flush()
        return doc
```

Add `similarity_search()` method (after `get_by_type_and_version`):

```python
    async def similarity_search(
        self,
        novel_id: str,
        query_vector: List[float],
        limit: int = 5,
        doc_type_filter: Optional[str] = None,
    ) -> List[SimilarDocument]:
        bind = self.session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            return await self._similarity_search_postgres(novel_id, query_vector, limit, doc_type_filter)
        return await self._similarity_search_sqlite(novel_id, query_vector, limit, doc_type_filter)

    async def _similarity_search_postgres(
        self,
        novel_id: str,
        query_vector: List[float],
        limit: int,
        doc_type_filter: Optional[str],
    ) -> List[SimilarDocument]:
        vector_str = "[" + ",".join(str(float(x)) for x in query_vector) + "]"
        sql = """
            SELECT id, doc_type, title, content,
                   1 - (vector_embedding <=> :query_vector) AS similarity
            FROM novel_documents
            WHERE novel_id = :novel_id
              AND vector_embedding IS NOT NULL
        """
        params = {"novel_id": novel_id, "query_vector": vector_str, "limit": limit}
        if doc_type_filter:
            sql += " AND doc_type = :doc_type"
            params["doc_type"] = doc_type_filter
        sql += " ORDER BY vector_embedding <=> :query_vector LIMIT :limit"

        result = await self.session.execute(text(sql), params)
        rows = result.all()
        return [
            SimilarDocument(
                doc_id=row.id,
                doc_type=row.doc_type,
                title=row.title,
                content_preview=(row.content or "")[:200],
                similarity_score=float(row.similarity),
            )
            for row in rows
        ]

    async def _similarity_search_sqlite(
        self,
        novel_id: str,
        query_vector: List[float],
        limit: int,
        doc_type_filter: Optional[str],
    ) -> List[SimilarDocument]:
        stmt = select(NovelDocument).where(
            NovelDocument.novel_id == novel_id,
            NovelDocument.vector_embedding.is_not(None),
        )
        if doc_type_filter:
            stmt = stmt.where(NovelDocument.doc_type == doc_type_filter)

        result = await self.session.execute(stmt)
        docs = result.scalars().all()

        scored = []
        for doc in docs:
            vec = doc.vector_embedding
            if not vec:
                continue
            score = self._cosine_similarity(query_vector, vec)
            scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SimilarDocument(
                doc_id=doc.id,
                doc_type=doc.doc_type,
                title=doc.title,
                content_preview=(doc.content or "")[:200],
                similarity_score=score,
            )
            for score, doc in scored[:limit]
        ]

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=src pytest tests/test_repositories/test_document_repo_similarity.py -v
```

Expected: 4 passed

- [ ] **Step 5: Verify existing DocumentRepository tests still pass**

Run:
```bash
PYTHONPATH=src pytest tests/test_repositories/test_document_repo.py -v
```

Expected: all passed (vector_embedding param removal should not break tests since no caller passed it)

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/repositories/document_repo.py tests/test_repositories/test_document_repo_similarity.py
git commit -m "feat(document_repo): add similarity_search with PostgreSQL + SQLite dual paths"
```

---

## Task 5: EmbeddingService

**Files:**
- Create: `src/novel_dev/services/embedding_service.py`
- Test: `tests/test_services/test_embedding_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_services/test_embedding_service.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.db.models import NovelDocument
from novel_dev.repositories.document_repo import DocumentRepository


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
    # Create a doc first
    repo = DocumentRepository(async_session)
    doc = await repo.create(
        doc_id="doc_1", novel_id="n1", doc_type="setting",
        title="Test", content="test content",
    )

    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    svc = EmbeddingService(async_session, mock_embedder)
    await svc.index_document("doc_1")

    mock_embedder.aembed.assert_awaited_once_with(["test content"])

    # Verify DB updated
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
    # Seed document with embedding
    from novel_dev.db.models import NovelDocument
    doc = NovelDocument(
        id="doc_1", novel_id="n1", doc_type="setting", title="A",
        content="content", vector_embedding=[1.0, 0.0], version=1,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=src pytest tests/test_services/test_embedding_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'novel_dev.services.embedding_service'`

- [ ] **Step 3: Implement EmbeddingService**

Create `src/novel_dev/services/embedding_service.py`:

```python
import logging
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.llm.embedder import BaseEmbedder
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.schemas.similar_document import SimilarDocument

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(
        self,
        session: AsyncSession,
        embedder: BaseEmbedder,
        max_query_length: int = 8000,
    ):
        self.session = session
        self.embedder = embedder
        self.max_query_length = max_query_length

    async def generate_embedding(self, text: str) -> List[float]:
        truncated = text[: self.max_query_length]
        vectors = await self.embedder.aembed([truncated])
        return vectors[0]

    async def index_document(self, doc_id: str) -> None:
        repo = DocumentRepository(self.session)
        doc = await repo.get_by_id(doc_id)
        if not doc or not doc.content:
            return
        try:
            vector = await self.generate_embedding(doc.content)
        except Exception as exc:
            logger.warning("embedding_generation_failed", extra={"doc_id": doc_id, "error": str(exc)})
            return
        doc.vector_embedding = vector
        await self.session.flush()

    async def search_similar(
        self,
        novel_id: str,
        query_text: str,
        limit: int = 5,
        doc_type_filter: Optional[str] = None,
    ) -> List[SimilarDocument]:
        query_vector = await self.generate_embedding(query_text)
        repo = DocumentRepository(self.session)
        return await repo.similarity_search(
            novel_id, query_vector, limit, doc_type_filter
        )

    async def search_similar_by_vector(
        self,
        novel_id: str,
        query_vector: List[float],
        limit: int = 5,
        doc_type_filter: Optional[str] = None,
    ) -> List[SimilarDocument]:
        repo = DocumentRepository(self.session)
        return await repo.similarity_search(
            novel_id, query_vector, limit, doc_type_filter
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=src pytest tests/test_services/test_embedding_service.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/embedding_service.py tests/test_services/test_embedding_service.py
git commit -m "feat(embedding_service): add generate, index, and search operations"
```

---

## Task 6: ContextAgent Semantic Integration

**Files:**
- Modify: `src/novel_dev/agents/context_agent.py`
- Test: `tests/test_agents/test_context_agent_semantic.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agents/test_context_agent_semantic.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_dev.agents.context_agent import ContextAgent
from novel_dev.schemas.similar_document import SimilarDocument


@pytest.mark.asyncio
async def test_assemble_with_embedding_service_includes_relevant_docs(
    async_session, mock_llm_factory
):
    # Setup novel state with checkpoint
    from novel_dev.db.models import NovelState
    state = NovelState(
        novel_id="n1",
        current_phase="drafting",
        checkpoint_data={
            "current_chapter_plan": {
                "chapter_number": 1,
                "title": "第一章",
                "target_word_count": 3000,
                "beats": [
                    {"summary": "主角进入学院", "target_mood": "好奇", "key_entities": ["主角"]}
                ],
            },
            "current_time_tick": 1,
        },
    )
    async_session.add(state)
    await async_session.flush()

    mock_emb_svc = AsyncMock()
    mock_emb_svc.search_similar = AsyncMock(return_value=[
        SimilarDocument(
            doc_id="doc_s1", doc_type="setting", title="星辰学院",
            content_preview="位于大陆中央的魔法学院", similarity_score=0.95,
        ),
    ])

    agent = ContextAgent(async_session, embedding_service=mock_emb_svc)
    context = await agent.assemble("n1", "ch1")

    assert len(context.relevant_documents) == 1
    assert context.relevant_documents[0].doc_id == "doc_s1"
    mock_emb_svc.search_similar.assert_awaited_once()


@pytest.mark.asyncio
async def test_assemble_without_embedding_service_has_empty_relevant_docs(
    async_session, mock_llm_factory
):
    from novel_dev.db.models import NovelState
    state = NovelState(
        novel_id="n1",
        current_phase="drafting",
        checkpoint_data={
            "current_chapter_plan": {
                "chapter_number": 1,
                "title": "第一章",
                "target_word_count": 3000,
                "beats": [
                    {"summary": "主角进入学院", "target_mood": "好奇", "key_entities": ["主角"]}
                ],
            },
            "current_time_tick": 1,
        },
    )
    async_session.add(state)
    await async_session.flush()

    agent = ContextAgent(async_session)
    context = await agent.assemble("n1", "ch1")

    assert context.relevant_documents == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=src pytest tests/test_agents/test_context_agent_semantic.py -v
```

Expected: `TypeError: ContextAgent.__init__() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Modify ContextAgent**

Modify `src/novel_dev/agents/context_agent.py`:

Add imports:
```python
import logging
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.schemas.similar_document import SimilarDocument

logger = logging.getLogger(__name__)
```

Modify `__init__`:
```python
class ContextAgent:
    def __init__(
        self,
        session: AsyncSession,
        embedding_service: Optional[EmbeddingService] = None,
    ):
        self.session = session
        self.embedding_service = embedding_service
        ...
```

Modify `assemble()` — after `worldview_doc` retrieval, before constructing `ChapterContext`:

```python
        worldview_doc = await self.doc_repo.get_latest_by_type(novel_id, "worldview")
        worldview_summary = worldview_doc.content if worldview_doc else ""

        # Semantic search augmentation
        relevant_docs: List[SimilarDocument] = []
        if self.embedding_service:
            query_text = self._build_search_query(chapter_plan)
            try:
                results = await self.embedding_service.search_similar(
                    novel_id=novel_id,
                    query_text=query_text,
                    limit=3,
                )
                exclude_id = worldview_doc.id if worldview_doc else None
                relevant_docs = [r for r in results if r.doc_id != exclude_id]
            except Exception as exc:
                logger.warning("semantic_search_failed", extra={"novel_id": novel_id, "error": str(exc)})

        ...
        context = ChapterContext(
            chapter_plan=chapter_plan,
            style_profile=style_profile,
            worldview_summary=worldview_summary,
            active_entities=active_entities,
            location_context=location_context,
            timeline_events=timeline_events,
            pending_foreshadowings=pending_foreshadowings,
            previous_chapter_summary=prev_summary,
            relevant_documents=relevant_docs,
        )
```

Add `_build_search_query` method:

```python
    def _build_search_query(self, chapter_plan: ChapterPlan) -> str:
        parts = []
        if chapter_plan.title:
            parts.append(chapter_plan.title)
        for beat in chapter_plan.beats[:2]:
            parts.append(beat.summary)
        return "\n".join(parts)[:8000]
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=src pytest tests/test_agents/test_context_agent_semantic.py -v
```

Expected: 2 passed

- [ ] **Step 5: Verify existing ContextAgent tests still pass**

Run:
```bash
PYTHONPATH=src pytest tests/test_agents/test_context_agent.py -v
```

Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/agents/context_agent.py tests/test_agents/test_context_agent_semantic.py
git commit -m "feat(context_agent): integrate semantic search via optional EmbeddingService"
```

---

## Task 7: WriterAgent Prompt with relevant_documents

**Files:**
- Modify: `src/novel_dev/agents/writer_agent.py`
- Test: `tests/test_agents/test_writer_agent_relevant_docs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agents/test_writer_agent_relevant_docs.py`:

```python
import pytest

from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.schemas.context import ChapterContext, ChapterPlan, BeatPlan
from novel_dev.schemas.similar_document import SimilarDocument


def test_relevant_docs_text_block_in_prompt():
    context = ChapterContext(
        chapter_plan=ChapterPlan(
            chapter_number=1,
            title="第一章",
            target_word_count=3000,
            beats=[BeatPlan(summary="主角进入学院", target_mood="好奇", key_entities=["主角"])],
        ),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=MagicMock(),
        timeline_events=[],
        pending_foreshadowings=[],
        relevant_documents=[
            SimilarDocument(
                doc_id="d1", doc_type="setting", title="星辰学院",
                content_preview="位于大陆中央的魔法学院", similarity_score=0.95,
            ),
        ],
    )

    agent = WriterAgent(MagicMock())
    beat = context.chapter_plan.beats[0]
    prompt = agent._build_beat_prompt(beat, context, "")

    assert "相关设定补充" in prompt
    assert "星辰学院" in prompt
    assert "位于大陆中央的魔法学院" in prompt


def test_relevant_docs_text_block_empty_when_no_docs():
    context = ChapterContext(
        chapter_plan=ChapterPlan(
            chapter_number=1,
            title="第一章",
            target_word_count=3000,
            beats=[BeatPlan(summary="主角进入学院", target_mood="好奇", key_entities=["主角"])],
        ),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=MagicMock(),
        timeline_events=[],
        pending_foreshadowings=[],
        relevant_documents=[],
    )

    agent = WriterAgent(MagicMock())
    beat = context.chapter_plan.beats[0]
    prompt = agent._build_beat_prompt(beat, context, "")

    assert "相关设定补充" not in prompt
```

Note: `MagicMock` needs import. The test assumes `_build_beat_prompt` exists as a helper. We need to refactor `_generate_beat` to extract the prompt building.

Actually, let me reconsider. The test should verify the prompt structure by testing a new helper method. Let me adjust:

```python
from unittest.mock import MagicMock
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=src pytest tests/test_agents/test_writer_agent_relevant_docs.py -v
```

Expected: `AttributeError: 'WriterAgent' object has no attribute '_build_beat_prompt'`

- [ ] **Step 3: Refactor WriterAgent to extract prompt builder**

Modify `src/novel_dev/agents/writer_agent.py`:

Add `_build_relevant_docs_text` helper:

```python
    def _build_relevant_docs_text(self, context: ChapterContext) -> str:
        if not context.relevant_documents:
            return ""
        docs_block = "\n\n".join(
            f"[{d.doc_type}] {d.title}\n{d.content_preview}"
            for d in context.relevant_documents
        )
        return (
            f"\n\n### 相关设定补充（与本节拍高度相关，写作时请优先参考）\n"
            f"{docs_block}\n"
        )
```

Refactor `_generate_beat`:

```python
    async def _generate_beat(self, beat: BeatPlan, context: ChapterContext, previous_text: str) -> str:
        prompt = self._build_beat_prompt(beat, context, previous_text)
        from novel_dev.llm import llm_factory
        client = llm_factory.get("WriterAgent", task="generate_beat")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return response.text.strip()

    def _build_beat_prompt(self, beat: BeatPlan, context: ChapterContext, previous_text: str) -> str:
        relevant_docs_text = self._build_relevant_docs_text(context)
        return (
            "你是一位小说家。请根据以下节拍计划和上下文，生成该节拍的正文。"
            "要求：只返回正文内容，不添加解释。\n\n"
            f"### 节拍计划\n{beat.model_dump_json()}\n\n"
            f"### 章节上下文\n{context.model_dump_json()}\n\n"
            f"{relevant_docs_text}"
            f"### 已写文本\n{previous_text}\n\n"
            "请生成正文："
        )
```

Refactor `_rewrite_angle`:

```python
    async def _rewrite_angle(self, beat: BeatPlan, original_text: str, context: ChapterContext) -> str:
        relevant_docs_text = self._build_relevant_docs_text(context)
        prompt = (
            "你是一位小说家。当前节拍过短，请扩写并保持与上下文的连贯。"
            "只返回扩写后的正文，不添加解释。\n\n"
            f"### 节拍计划\n{beat.model_dump_json()}\n\n"
            f"### 章节上下文\n{context.model_dump_json()}\n\n"
            f"{relevant_docs_text}"
            f"### 当前过短文本\n{original_text}\n\n"
            "请扩写："
        )
        from novel_dev.llm import llm_factory
        client = llm_factory.get("WriterAgent", task="rewrite_beat")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return response.text.strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=src pytest tests/test_agents/test_writer_agent_relevant_docs.py -v
```

Expected: 2 passed

- [ ] **Step 5: Verify existing WriterAgent tests still pass**

Run:
```bash
PYTHONPATH=src pytest tests/test_agents/test_writer_agent.py -v
```

Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/agents/writer_agent.py tests/test_agents/test_writer_agent_relevant_docs.py
git commit -m "feat(writer_agent): add relevant_documents block to beat prompts"
```

---

## Task 8: API Routes + MCP Server Wiring

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Modify: `src/novel_dev/mcp_server/server.py`

- [ ] **Step 1: Modify api/routes.py**

Modify `src/novel_dev/api/routes.py` (around line 342):

```python
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.llm import llm_factory

@router.post("/api/novels/{novel_id}/chapters/{chapter_id}/context")
async def prepare_chapter_context(
    novel_id: str,
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    agent = ContextAgent(session, embedding_service)
    ...
```

- [ ] **Step 2: Modify mcp_server/server.py**

Modify `src/novel_dev/mcp_server/server.py` (around line 180):

```python
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.llm import llm_factory

@mcp.tool()
async def prepare_chapter_context(novel_id: str, chapter_id: str) -> dict:
    async with async_session_maker() as session:
        embedder = llm_factory.get_embedder()
        embedding_service = EmbeddingService(session, embedder)
        agent = ContextAgent(session, embedding_service)
        ...
```

- [ ] **Step 3: Run affected tests**

Run:
```bash
PYTHONPATH=src pytest tests/test_api/ tests/test_mcp_server.py -q --tb=short 2>&1 | tail -n 20
```

Expected: Tests pass (or pre-existing failures unchanged)

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/api/routes.py src/novel_dev/mcp_server/server.py
git commit -m "feat(api/mcp): inject EmbeddingService into ContextAgent construction"
```

---

## Task 9: llm_config.yaml + Migration

**Files:**
- Modify: `llm_config.yaml`
- Create: `migrations/versions/20260417_xxxx_enable_pgvector.py`

- [ ] **Step 1: Add embedding config to llm_config.yaml**

Add to `llm_config.yaml` (after `defaults:`, before `agents:`):

```yaml
embedding:
  provider: openai_compatible
  model: text-embedding-3-small
  base_url: https://api.openai.com/v1
  timeout: 30
  retries: 3
  dimensions: 1536

agents:
  ...
```

- [ ] **Step 2: Create Alembic migration for pgvector extension**

Create `migrations/versions/20260417_xxxx_enable_pgvector.py`:

```python
"""Enable pgvector extension.

Revision ID: xxxx
Revises: a198e260c3bf
Create Date: 2026-04-17 xx:xx:xx.xxxxxx

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "xxxx"
down_revision: Union[str, None] = "a198e260c3bf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
```

Replace `xxxx` with actual revision ID from `alembic revision --autogenerate -m "enable pgvector"`.

- [ ] **Step 3: Verify embedding config parse**

Run:
```bash
PYTHONPATH=src python -c "
from novel_dev.llm import llm_factory
emb = llm_factory.get_embedder()
print('model:', emb.model)
print('dimensions:', emb.dimensions)
"
```

Expected:
```
model: text-embedding-3-small
dimensions: 1536
```

- [ ] **Step 4: Commit**

```bash
git add llm_config.yaml migrations/versions/
git commit -m "config: add embedding model config and pgvector extension migration"
```

---

## Task 10: Full Test Suite Verification

**Files:**
- All test files

- [ ] **Step 1: Run full test suite**

Run:
```bash
PYTHONPATH=src pytest -q --tb=short 2>&1 | tail -n 20
```

Expected: All existing tests (187+) pass. New tests (from Tasks 1-7) also pass.

- [ ] **Step 2: Run specific new test modules**

Run:
```bash
PYTHONPATH=src pytest \
  tests/llm/test_embedder.py \
  tests/llm/test_factory_embedder.py \
  tests/test_schemas/test_similar_document.py \
  tests/test_repositories/test_document_repo_similarity.py \
  tests/test_services/test_embedding_service.py \
  tests/test_agents/test_context_agent_semantic.py \
  tests/test_agents/test_writer_agent_relevant_docs.py \
  -v
```

Expected: All new tests pass.

- [ ] **Step 3: Commit any test fixes**

If any fixes were needed, commit them. Otherwise mark as done.

---

## Self-Review Checklist

### Spec Coverage

| Spec Section | Implementing Task | Status |
|-------------|-------------------|--------|
| EmbeddingConfig model | Task 1 | ✅ |
| BaseEmbedder + OpenAIEmbedder | Task 1 | ✅ |
| LLMFactory.get_embedder() | Task 2 | ✅ |
| SimilarDocument schema | Task 3 | ✅ |
| ChapterContext.relevant_documents | Task 3 | ✅ |
| DocumentRepository.similarity_search() (PG + SQLite) | Task 4 | ✅ |
| DocumentRepository.create() remove vector_embedding | Task 4 | ✅ |
| EmbeddingService.generate_embedding | Task 5 | ✅ |
| EmbeddingService.index_document | Task 5 | ✅ |
| EmbeddingService.search_similar | Task 5 | ✅ |
| ContextAgent embedding_service param | Task 6 | ✅ |
| ContextAgent._build_search_query | Task 6 | ✅ |
| ContextAgent semantic search integration | Task 6 | ✅ |
| WriterAgent prompt with relevant_documents | Task 7 | ✅ |
| API routes injection | Task 8 | ✅ |
| MCP server injection | Task 8 | ✅ |
| llm_config.yaml embedding config | Task 9 | ✅ |
| pgvector extension migration | Task 9 | ✅ |

### Placeholder Scan

- [x] No "TBD", "TODO", "implement later"
- [x] No vague "add error handling" without specifics
- [x] No "similar to Task N" references
- [x] Every step has actual code or exact command

### Type Consistency

- [x] `EmbeddingConfig` fields match usage in `factory.py`
- [x] `BaseEmbedder.aembed()` signature consistent across `embedder.py` and mocks
- [x] `DocumentRepository.similarity_search()` params consistent in `document_repo.py`, `embedding_service.py`, tests
- [x] `SimilarDocument` fields consistent across schema, repo, service, tests
- [x] `ChapterContext.relevant_documents` type `List[SimilarDocument]` everywhere

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-17-vector-search-rag-phase1.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session, batch execution with checkpoints for review

Which approach do you prefer?
