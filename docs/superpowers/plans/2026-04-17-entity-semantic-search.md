# Entity Semantic Search Implementation Plan

**Goal:** Add vector embedding to Entity table and integrate semantic entity retrieval into ContextAgent/WriterAgent to prevent "setting drift".

---

## Task 1: Entity Model + Migration

**Files:**
- Modify: `src/novel_dev/db/models.py`
- Create: `migrations/versions/20260417_xxxx_add_entity_vector_embedding.py`

- Add `vector_embedding: Mapped[Optional[list[float]]] = mapped_column(VectorCompat(1536), nullable=True)` to `Entity`
- Alembic migration to add column

## Task 2: EntityRepository.similarity_search()

**Files:**
- Modify: `src/novel_dev/repositories/entity_repo.py`
- Test: `tests/test_repositories/test_entity_repo_similarity.py`

- Add `similarity_search(novel_id, query_vector, limit=5, type_filter=None)` with PostgreSQL + SQLite dual paths
- Add `_cosine_similarity()` static method

## Task 3: EmbeddingService Entity Methods

**Files:**
- Modify: `src/novel_dev/services/embedding_service.py`
- Test: `tests/test_services/test_embedding_service_entities.py`

- Add `index_entity(entity_id)` - flatten state JSON to key=value text, embed, persist
- Add `search_similar_entities(novel_id, query_text, limit=5, type_filter=None)`
- State flattening: `{"name": "林风", "level": "筑基期"}` → `name=林风, level=筑基期`

## Task 4: EntityService Trigger Embedding

**Files:**
- Modify: `src/novel_dev/services/entity_service.py`

- In `update_state()`, after creating new version, trigger `embedding_service.index_entity(entity_id)` asynchronously (fire-and-forget via `asyncio.create_task`)
- `create_entity()` also triggers initial embedding

## Task 5: ContextAgent + WriterAgent Integration

**Files:**
- Modify: `src/novel_dev/agents/context_agent.py`
- Modify: `src/novel_dev/agents/writer_agent.py`
- Test: `tests/test_agents/test_context_agent_entities.py`
- Test: `tests/test_agents/test_writer_agent_entities.py`

**ContextAgent:**
- After `_load_active_entities()`, call `embedding_service.search_similar_entities()`
- Filter out entities already in `active_entities`
- Add to `ChapterContext.related_entities: list[EntityState]`

**WriterAgent:**
- Add `_build_related_entities_text()` helper
- Insert "### 相关角色/势力/地点（请注意设定一致性）" block in `_build_beat_prompt()` and `_rewrite_angle()`

## Task 6: Full Test Verification

Run `PYTHONPATH=src pytest -q` and verify no new failures.
