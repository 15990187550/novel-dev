# Entity Encyclopedia Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the new entity encyclopedia classification system with novel-scoped group registry, manual override workflow, search-specific embeddings, hybrid search API, and the left-tree/right-workspace frontend.

**Architecture:** Extend the existing `entities` table rather than replacing it, keeping `Entity.type` as a compatibility field while adding a new classification layer built around `system_*`, `manual_*`, and `effective_*` values. Add a dedicated group registry plus search-specific embedding fields and service logic, then expose these through new encyclopedia API endpoints and a refactored frontend built around a tree navigator and detail workspace.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Alembic, PostgreSQL/pgvector, pytest, Vue 3, Pinia, Element Plus, vue-echarts

---

## File Structure

### Backend data and migrations

- Modify: `src/novel_dev/db/models.py`
  - Add classification fields and search-specific embedding fields to `Entity`
  - Add a new `EntityGroup` model for novel-scoped secondary groups
- Create: `migrations/versions/20260421_add_entity_classification_and_search_fields.py`
  - Add entity classification columns
  - Add `entity_groups` table
  - Add search vector/search text columns and indexes

### Backend repositories and services

- Modify: `src/novel_dev/repositories/entity_repo.py`
  - Add classification-aware listing, filtering, and hybrid search helpers
- Create: `src/novel_dev/repositories/entity_group_repo.py`
  - Manage group registry CRUD and lookup by `novel_id/category/group_slug`
- Modify: `src/novel_dev/services/embedding_service.py`
  - Add `search_document` flattening and `search_vector_embedding` indexing
- Create: `src/novel_dev/services/entity_classification_service.py`
  - Generate `system_category/system_group/classification_reason/classification_confidence/system_needs_review`
- Modify: `src/novel_dev/services/entity_service.py`
  - Apply manual overrides
  - Enforce category/group consistency
  - Trigger classification + search index refresh

### Backend API

- Modify: `src/novel_dev/api/routes.py`
  - Extend entity list/detail payloads
  - Add update/search endpoints

### Frontend

- Modify: `src/novel_dev/web/src/api.js`
  - Add search/update endpoints
- Modify: `src/novel_dev/web/src/stores/novel.js`
  - Store tree/search/detail state and new entity payload shape
- Modify: `src/novel_dev/web/src/views/Entities.vue`
  - Replace tabular layout with left tree + right workspace
- Create: `src/novel_dev/web/src/components/entities/EntityTree.vue`
  - Render category/group/entity hierarchy
- Create: `src/novel_dev/web/src/components/entities/EntityGroupTable.vue`
  - Render group-level list with inline edits
- Create: `src/novel_dev/web/src/components/entities/EntityDetailPanel.vue`
  - Render single-entity detail and manual override controls

### Tests

- Modify: `tests/test_repositories/test_entity_repo.py`
- Create: `tests/test_repositories/test_entity_group_repo.py`
- Modify: `tests/test_services/test_embedding_service_entities.py`
- Create: `tests/test_services/test_entity_classification_service.py`
- Modify: `tests/test_services/test_entity_service.py`
- Modify: `tests/test_api/test_encyclopedia_routes.py`

## Task 1: Add classification/search data model and migration

**Files:**
- Create: `migrations/versions/20260421_add_entity_classification_and_search_fields.py`
- Modify: `src/novel_dev/db/models.py`
- Test: `tests/test_repositories/test_entity_repo.py`

- [ ] **Step 1: Write the failing repository/model test**

```python
@pytest.mark.asyncio
async def test_create_entity_initializes_classification_fields(async_session):
    repo = EntityRepository(async_session)
    entity = await repo.create("char_100", "character", "陆照", novel_id="novel_x")

    assert entity.system_category is None
    assert entity.system_group_id is None
    assert entity.manual_category is None
    assert entity.manual_group_id is None
    assert entity.search_document is None
    assert entity.search_vector_embedding is None
    assert entity.system_needs_review is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_repositories/test_entity_repo.py::test_create_entity_initializes_classification_fields -v`

Expected: FAIL with `AttributeError` or ORM column error because the new fields do not exist yet.

- [ ] **Step 3: Write the minimal model and migration**

In `src/novel_dev/db/models.py`, extend `Entity` and add `EntityGroup`:

```python
class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at_chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    novel_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    vector_embedding: Mapped[Optional[list[float]]] = mapped_column(VectorCompat(1024), nullable=True)
    system_category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    system_group_id: Mapped[Optional[str]] = mapped_column(ForeignKey("entity_groups.id"), nullable=True)
    manual_category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    manual_group_id: Mapped[Optional[str]] = mapped_column(ForeignKey("entity_groups.id"), nullable=True)
    classification_reason: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    classification_confidence: Mapped[Optional[float]] = mapped_column(nullable=True)
    system_needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    search_document: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    search_vector_embedding: Mapped[Optional[list[float]]] = mapped_column(VectorCompat(1024), nullable=True)


class EntityGroup(Base):
    __tablename__ = "entity_groups"
    __table_args__ = (
        UniqueConstraint("novel_id", "category", "group_slug", name="uix_entity_group_scope"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    group_name: Mapped[str] = mapped_column(Text, nullable=False)
    group_slug: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="system")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

In `migrations/versions/20260421_add_entity_classification_and_search_fields.py`, create the table and columns:

```python
def upgrade() -> None:
    op.create_table(
        "entity_groups",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("group_name", sa.Text(), nullable=False),
        sa.Column("group_slug", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="system"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("novel_id", "category", "group_slug", name="uix_entity_group_scope"),
    )
    op.add_column("entities", sa.Column("system_category", sa.Text(), nullable=True))
    op.add_column("entities", sa.Column("system_group_id", sa.Text(), nullable=True))
    op.add_column("entities", sa.Column("manual_category", sa.Text(), nullable=True))
    op.add_column("entities", sa.Column("manual_group_id", sa.Text(), nullable=True))
    op.add_column("entities", sa.Column("classification_reason", sa.JSON(), nullable=True))
    op.add_column("entities", sa.Column("classification_confidence", sa.Float(), nullable=True))
    op.add_column("entities", sa.Column("system_needs_review", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("entities", sa.Column("search_document", sa.Text(), nullable=True))
    op.add_column("entities", sa.Column("search_vector_embedding", sa.JSON(), nullable=True))
```

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `pytest tests/test_repositories/test_entity_repo.py::test_create_entity_initializes_classification_fields -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/db/models.py migrations/versions/20260421_add_entity_classification_and_search_fields.py tests/test_repositories/test_entity_repo.py
git commit -m "feat: add entity classification data model"
```

## Task 2: Add novel-scoped group registry repository and classification-aware repository helpers

**Files:**
- Create: `src/novel_dev/repositories/entity_group_repo.py`
- Modify: `src/novel_dev/repositories/entity_repo.py`
- Test: `tests/test_repositories/test_entity_group_repo.py`
- Test: `tests/test_repositories/test_entity_repo.py`

- [ ] **Step 1: Write the failing repository tests**

```python
@pytest.mark.asyncio
async def test_entity_group_repo_upserts_with_novel_scope(async_session):
    repo = EntityGroupRepository(async_session)
    first = await repo.upsert(
        novel_id="n1",
        category="人物",
        group_name="主角阵营",
        group_slug="zhujiao-zhenying",
        source="system",
    )
    second = await repo.upsert(
        novel_id="n1",
        category="人物",
        group_name="主角阵营",
        group_slug="zhujiao-zhenying",
        source="custom",
    )

    assert first.id == second.id
    assert second.source == "custom"


@pytest.mark.asyncio
async def test_entity_repo_rejects_manual_group_outside_manual_category(async_session):
    group_repo = EntityGroupRepository(async_session)
    repo = EntityRepository(async_session)

    hero_group = await group_repo.upsert(
        novel_id="n1",
        category="人物",
        group_name="主角阵营",
        group_slug="hero-camp",
    )
    entity = await repo.create("e1", "character", "陆照", novel_id="n1")

    with pytest.raises(ValueError, match="manual_group must belong to manual_category"):
        await repo.update_classification(
            entity_id="e1",
            system_category="人物",
            manual_category="势力",
            manual_group_id=hero_group.id,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_repositories/test_entity_group_repo.py tests/test_repositories/test_entity_repo.py -k "group_repo or manual_group_outside" -v`

Expected: FAIL because `EntityGroupRepository` and `update_classification()` do not exist yet.

- [ ] **Step 3: Implement repository helpers**

In `src/novel_dev/repositories/entity_group_repo.py`:

```python
class EntityGroupRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(
        self,
        novel_id: str,
        category: str,
        group_name: str,
        group_slug: str,
        source: str = "system",
        sort_order: int = 0,
    ) -> EntityGroup:
        stmt = select(EntityGroup).where(
            EntityGroup.novel_id == novel_id,
            EntityGroup.category == category,
            EntityGroup.group_slug == group_slug,
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            existing.group_name = group_name
            existing.source = source
            existing.sort_order = sort_order
            await self.session.flush()
            return existing

        entity_group = EntityGroup(
            id=f"group-{uuid4().hex[:8]}",
            novel_id=novel_id,
            category=category,
            group_name=group_name,
            group_slug=group_slug,
            source=source,
            sort_order=sort_order,
        )
        self.session.add(entity_group)
        await self.session.flush()
        return entity_group
```

In `src/novel_dev/repositories/entity_repo.py`, add classification mutation with validation:

```python
async def update_classification(
    self,
    entity_id: str,
    *,
    system_category: Optional[str] = None,
    system_group_id: Optional[str] = None,
    manual_category: Optional[str] = None,
    manual_group_id: Optional[str] = None,
    classification_reason: Optional[dict] = None,
    classification_confidence: Optional[float] = None,
    system_needs_review: Optional[bool] = None,
) -> Entity:
    entity = await self.get_by_id(entity_id)
    if entity is None:
        raise ValueError(f"Entity not found: {entity_id}")

    if manual_group_id:
        manual_group = await self.session.get(EntityGroup, manual_group_id)
        if manual_group is None or manual_group.category != manual_category:
            raise ValueError("manual_group must belong to manual_category")

    entity.system_category = system_category
    entity.system_group_id = system_group_id
    entity.manual_category = manual_category
    entity.manual_group_id = manual_group_id
    entity.classification_reason = classification_reason
    entity.classification_confidence = classification_confidence
    if system_needs_review is not None:
        entity.system_needs_review = system_needs_review
    await self.session.flush()
    return entity
```

- [ ] **Step 4: Run repository tests to verify they pass**

Run: `pytest tests/test_repositories/test_entity_group_repo.py tests/test_repositories/test_entity_repo.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/repositories/entity_group_repo.py src/novel_dev/repositories/entity_repo.py tests/test_repositories/test_entity_group_repo.py tests/test_repositories/test_entity_repo.py
git commit -m "feat: add entity group registry repository"
```

## Task 3: Add classification service and search-specific embedding refresh

**Files:**
- Create: `src/novel_dev/services/entity_classification_service.py`
- Modify: `src/novel_dev/services/embedding_service.py`
- Modify: `src/novel_dev/services/entity_service.py`
- Test: `tests/test_services/test_entity_classification_service.py`
- Test: `tests/test_services/test_embedding_service_entities.py`
- Test: `tests/test_services/test_entity_service.py`

- [ ] **Step 1: Write the failing service tests**

```python
@pytest.mark.asyncio
async def test_classification_service_marks_other_as_needs_review(async_session):
    service = EntityClassificationService(async_session)
    result = await service.classify(
        novel_id="n1",
        entity_name="无名概念",
        latest_state={"description": "一种模糊设定"},
        relationships=[],
    )

    assert result.system_category == "其他"
    assert result.system_needs_review is True
    assert result.classification_status == "needs_review"


@pytest.mark.asyncio
async def test_index_entity_search_refreshes_search_document(async_session):
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)
    entity = await entity_repo.create("e1", "character", "陆照", novel_id="n1")
    await version_repo.create("e1", 1, {"identity": "道门弟子", "abilities": "剑术"})
    entity.system_category = "人物"
    entity.system_needs_review = False

    mock_embedder = AsyncMock()
    mock_embedder.aembed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    svc = EmbeddingService(async_session, mock_embedder)
    await svc.index_entity_search("e1")

    updated = await entity_repo.get_by_id("e1")
    assert "一级分类：人物" in updated.search_document
    assert updated.search_vector_embedding == [0.1, 0.2, 0.3]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_services/test_entity_classification_service.py tests/test_services/test_embedding_service_entities.py -v`

Expected: FAIL because the new service and `index_entity_search()` do not exist.

- [ ] **Step 3: Implement classification and search-index refresh**

Create `src/novel_dev/services/entity_classification_service.py`:

```python
@dataclass
class EntityClassificationResult:
    system_category: str
    system_group_slug: str | None
    classification_reason: dict
    classification_confidence: float
    system_needs_review: bool
    classification_status: str


class EntityClassificationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def classify(self, novel_id: str, entity_name: str, latest_state: dict, relationships: list[dict]) -> EntityClassificationResult:
        text = "\n".join([entity_name, json.dumps(latest_state, ensure_ascii=False), json.dumps(relationships, ensure_ascii=False)])
        if any(keyword in text for keyword in ("宗门", "门派", "圣地", "世家")):
            return EntityClassificationResult("势力", "zongmen", {"matched_keywords": ["宗门"]}, 0.88, False, "auto")
        if any(keyword in text for keyword in ("功法", "心法", "神通")):
            return EntityClassificationResult("功法", "main-cultivation", {"matched_keywords": ["功法"]}, 0.82, False, "auto")
        return EntityClassificationResult("其他", None, {"matched_keywords": []}, 0.35, True, "needs_review")
```

In `src/novel_dev/services/embedding_service.py`, add search-specific flatten/index:

```python
async def index_entity_search(self, entity_id: str) -> None:
    entity_repo = EntityRepository(self.session)
    version_repo = EntityVersionRepository(self.session)
    entity = await entity_repo.get_by_id(entity_id)
    if not entity:
        return
    version = await version_repo.get_latest(entity_id)
    state = version.state if version else {}
    search_text = self._flatten_entity_search_document(entity, state)
    vector = await self.generate_embedding(search_text)
    entity.search_document = search_text
    entity.search_vector_embedding = vector
    await self.session.flush()


def _flatten_entity_search_document(self, entity: Entity, state: dict) -> str:
    parts = [
        f"名称：{entity.name}",
        f"原始类型：{entity.type}",
        f"一级分类：{entity.manual_category or entity.system_category or ''}",
        f"待确认：{'是' if entity.system_needs_review else '否'}",
    ]
    for key, value in state.items():
        parts.append(f"{key}：{value}")
    return "\n".join(part for part in parts if part).strip()[:8000]
```

In `src/novel_dev/services/entity_service.py`, orchestrate classification + group lookup + search reindex after entity updates:

```python
classification_service = EntityClassificationService(self.session)
classification = await classification_service.classify(novel_id, entity.name, latest_state, relationships)
await self.entity_repo.update_classification(
    entity.id,
    system_category=classification.system_category,
    classification_reason=classification.classification_reason,
    classification_confidence=classification.classification_confidence,
    system_needs_review=classification.system_needs_review,
)
if self.embedding_service:
    await self.embedding_service.index_entity_search(entity.id)
```

- [ ] **Step 4: Run service tests to verify they pass**

Run: `pytest tests/test_services/test_entity_classification_service.py tests/test_services/test_embedding_service_entities.py tests/test_services/test_entity_service.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/entity_classification_service.py src/novel_dev/services/embedding_service.py src/novel_dev/services/entity_service.py tests/test_services/test_entity_classification_service.py tests/test_services/test_embedding_service_entities.py tests/test_services/test_entity_service.py
git commit -m "feat: add entity classification services"
```

## Task 4: Extend API for classification payloads, manual override, and hybrid search

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Modify: `src/novel_dev/repositories/entity_repo.py`
- Test: `tests/test_api/test_encyclopedia_routes.py`

- [ ] **Step 1: Write the failing API tests**

```python
@pytest.mark.asyncio
async def test_update_entity_classification(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    repo = EntityRepository(async_session)
    await repo.create("e1", "character", "陆照", novel_id="n1")
    await async_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/novels/n1/entities/e1/classification",
            json={"manual_category": "人物", "manual_group_slug": "hero-camp"},
        )
        assert resp.status_code == 200
        assert resp.json()["classification_status"] == "manual_override"


@pytest.mark.asyncio
async def test_search_entities_returns_grouped_results(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    repo = EntityRepository(async_session)
    entity = await repo.create("e1", "character", "陆照", novel_id="n_search")
    entity.system_category = "人物"
    entity.search_document = "名称：陆照\n一级分类：人物\n关系：主角阵营"
    entity.search_vector_embedding = [1.0, 0.0]
    await async_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/novels/n_search/entities/search", params={"q": "主角阵营"})
        payload = resp.json()
        assert resp.status_code == 200
        assert payload["items"][0]["entity_id"] == "e1"
        assert payload["items"][0]["match_reason"] in {"名称命中", "语义相关", "关系命中"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api/test_encyclopedia_routes.py -k "classification or search_entities" -v`

Expected: FAIL because the new routes do not exist.

- [ ] **Step 3: Implement API endpoints and hybrid search**

In `src/novel_dev/repositories/entity_repo.py`, add hybrid search helper:

```python
async def search_entities(
    self,
    novel_id: str,
    *,
    query: str,
    query_vector: list[float] | None,
    limit: int = 20,
) -> list[dict]:
    stmt = select(Entity).where(Entity.novel_id == novel_id)
    entities = (await self.session.execute(stmt)).scalars().all()
    scored = []
    lowered = query.lower()
    for entity in entities:
        lexical = 1.0 if lowered in (entity.name or "").lower() else 0.0
        semantic = self._cosine_similarity(query_vector, entity.search_vector_embedding) if query_vector and entity.search_vector_embedding else 0.0
        score = lexical * 2 + semantic
        if score <= 0:
            continue
        match_reason = "名称命中" if lexical else "语义相关"
        scored.append({"entity": entity, "score": score, "match_reason": match_reason})
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]
```

In `src/novel_dev/api/routes.py`, add endpoints:

```python
@router.post("/api/novels/{novel_id}/entities/{entity_id}/classification")
async def update_entity_classification(novel_id: str, entity_id: str, payload: dict, session: AsyncSession = Depends(get_session)):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    service = EntityService(session, embedding_service)
    entity = await service.update_manual_classification(
        novel_id=novel_id,
        entity_id=entity_id,
        manual_category=payload.get("manual_category"),
        manual_group_slug=payload.get("manual_group_slug"),
    )
    await session.commit()
    return entity


@router.get("/api/novels/{novel_id}/entities/search")
async def search_entities(novel_id: str, q: str, session: AsyncSession = Depends(get_session)):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    query_vector = await embedding_service.generate_embedding(q)
    results = await EntityRepository(session).search_entities(novel_id, query=q, query_vector=query_vector)
    return {"items": [serialize_entity_search_result(item) for item in results]}
```

- [ ] **Step 4: Run API tests to verify they pass**

Run: `pytest tests/test_api/test_encyclopedia_routes.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/api/routes.py src/novel_dev/repositories/entity_repo.py tests/test_api/test_encyclopedia_routes.py
git commit -m "feat: expose entity classification api"
```

## Task 5: Refactor frontend data flow for tree/workspace encyclopedia state

**Files:**
- Modify: `src/novel_dev/web/src/api.js`
- Modify: `src/novel_dev/web/src/stores/novel.js`
- Test: manual browser verification

- [ ] **Step 1: Write the failing API/store contract in code**

Add the intended API helpers in `src/novel_dev/web/src/api.js`:

```javascript
export const searchEntities = (id, params) =>
  api.get(`/novels/${id}/entities/search`, { params }).then(r => r.data)

export const updateEntityClassification = (id, entityId, payload) =>
  api.post(`/novels/${id}/entities/${entityId}/classification`, payload).then(r => r.data)
```

Add the intended store state in `src/novel_dev/web/src/stores/novel.js`:

```javascript
state: () => ({
  entityTree: [],
  selectedEntityNode: null,
  entitySearchQuery: '',
  entitySearchResults: [],
  selectedEntityDetail: null,
})
```

- [ ] **Step 2: Run frontend build to verify it currently fails after partial changes**

Run: `npm run build`

Workdir: `src/novel_dev/web`

Expected: FAIL because the new store actions/components are not wired yet.

- [ ] **Step 3: Implement store actions for load/search/update**

In `src/novel_dev/web/src/stores/novel.js`, add these actions:

```javascript
async fetchEntities() {
  const [entities, relationships] = await Promise.all([
    api.getEntities(this.novelId),
    api.getEntityRelationships(this.novelId).catch(() => ({ items: [] })),
  ])
  this.entities = entities.items || []
  this.entityRelationships = relationships.items || []
  this.entityTree = buildEntityTree(this.entities)
},

async searchEntities(query) {
  this.entitySearchQuery = query
  if (!query) {
    this.entitySearchResults = []
    this.entityTree = buildEntityTree(this.entities)
    return
  }
  const res = await api.searchEntities(this.novelId, { q: query })
  this.entitySearchResults = res.items || []
  this.entityTree = buildEntityTree(this.entitySearchResults)
},

async saveEntityClassification(entityId, payload) {
  const updated = await api.updateEntityClassification(this.novelId, entityId, payload)
  await this.fetchEntities()
  this.selectedEntityDetail = updated
},
```

- [ ] **Step 4: Run frontend build to verify it passes**

Run: `npm run build`

Workdir: `src/novel_dev/web`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/web/src/api.js src/novel_dev/web/src/stores/novel.js
git commit -m "feat: add entity encyclopedia store state"
```

## Task 6: Build the left-tree/right-workspace encyclopedia UI

**Files:**
- Create: `src/novel_dev/web/src/components/entities/EntityTree.vue`
- Create: `src/novel_dev/web/src/components/entities/EntityGroupTable.vue`
- Create: `src/novel_dev/web/src/components/entities/EntityDetailPanel.vue`
- Modify: `src/novel_dev/web/src/views/Entities.vue`
- Test: manual browser verification

- [ ] **Step 1: Write the component skeletons**

Create `src/novel_dev/web/src/components/entities/EntityTree.vue`:

```vue
<template>
  <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-3">
    <el-input :model-value="searchQuery" placeholder="搜索实体、别名、关系" @input="$emit('search', $event)" />
    <el-tree class="mt-3" :data="nodes" node-key="id" default-expand-all @node-click="$emit('select', $event)">
      <template #default="{ data }">
        <div class="flex items-center justify-between w-full gap-2">
          <span>{{ data.label }}</span>
          <el-tag v-if="data.badge" size="small">{{ data.badge }}</el-tag>
        </div>
      </template>
    </el-tree>
  </div>
</template>
```

Create `src/novel_dev/web/src/components/entities/EntityGroupTable.vue`:

```vue
<template>
  <el-table :data="items" style="width: 100%">
    <el-table-column prop="name" label="名称" width="180" />
    <el-table-column prop="effective_category" label="分类" width="120" />
    <el-table-column prop="effective_group_name" label="分组" width="160" />
    <el-table-column prop="classification_status" label="状态" width="120" />
    <el-table-column label="操作" width="280">
      <template #default="{ row }">
        <el-button size="small" @click="$emit('open-detail', row)">详情</el-button>
        <el-button size="small" @click="$emit('clear-override', row)">清除覆盖</el-button>
      </template>
    </el-table-column>
  </el-table>
</template>
```

- [ ] **Step 2: Run frontend build to verify the partial UI fails until view wiring is done**

Run: `npm run build`

Workdir: `src/novel_dev/web`

Expected: FAIL because `Entities.vue` still expects the old layout.

- [ ] **Step 3: Replace `Entities.vue` with tree/workspace layout**

In `src/novel_dev/web/src/views/Entities.vue`, switch to the new structure:

```vue
<template>
  <div class="grid gap-4 lg:grid-cols-[320px,minmax(0,1fr)]">
    <EntityTree
      :nodes="store.entityTree"
      :search-query="store.entitySearchQuery"
      @search="store.searchEntities"
      @select="handleSelect"
    />

    <div class="space-y-4">
      <EntityGroupTable
        v-if="workspaceMode === 'group'"
        :items="workspaceItems"
        @open-detail="openDetail"
        @clear-override="clearOverride"
      />
      <EntityDetailPanel
        v-else-if="workspaceMode === 'detail'"
        :entity="store.selectedEntityDetail"
        @save="saveClassification"
        @reclassify="reclassifyEntity"
      />
      <EntityGraph
        v-if="showGraph"
        :entities="store.entities"
        :relationships="store.entityRelationships"
        height="24rem"
        show-fullscreen-action
        @fullscreen="graphFullscreenVisible = true"
      />
    </div>
  </div>
</template>
```

- [ ] **Step 4: Run frontend build and manual smoke check**

Run: `npm run build`

Workdir: `src/novel_dev/web`

Expected: PASS

Manual verification:

- Open the app
- Go to the encyclopedia page
- Confirm the left tree renders category/group/entity nodes
- Click a category node and confirm the group table renders
- Click an entity node and confirm the detail panel renders

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/web/src/views/Entities.vue src/novel_dev/web/src/components/entities/EntityTree.vue src/novel_dev/web/src/components/entities/EntityGroupTable.vue src/novel_dev/web/src/components/entities/EntityDetailPanel.vue
git commit -m "feat: add entity encyclopedia workspace ui"
```

## Task 7: Wire inline editing, search explanation, and regression verification

**Files:**
- Modify: `src/novel_dev/web/src/components/entities/EntityGroupTable.vue`
- Modify: `src/novel_dev/web/src/components/entities/EntityDetailPanel.vue`
- Modify: `src/novel_dev/web/src/views/Entities.vue`
- Modify: `tests/test_api/test_encyclopedia_routes.py`
- Modify: `tests/test_services/test_entity_service.py`

- [ ] **Step 1: Write the failing regression tests**

```python
@pytest.mark.asyncio
async def test_manual_override_status_wins_over_needs_review(async_session):
    repo = EntityRepository(async_session)
    entity = await repo.create("e1", "character", "陆照", novel_id="n1")
    entity.system_category = "其他"
    entity.system_needs_review = True
    entity.manual_category = "人物"
    await async_session.commit()

    payload = serialize_entity(entity, latest_state={})
    assert payload["classification_status"] == "manual_override"
    assert payload["system_needs_review"] is True
```

- [ ] **Step 2: Run the regression tests to verify any remaining state or serialization bug fails**

Run: `pytest tests/test_api/test_encyclopedia_routes.py tests/test_services/test_entity_service.py -k "manual_override_status_wins" -v`

Expected: FAIL if status serialization still derives from `system_needs_review` incorrectly.

- [ ] **Step 3: Finish UI details and serializer logic**

In the entity serializer used by `src/novel_dev/api/routes.py`, compute derived fields:

```python
def build_classification_status(entity: Entity) -> str:
    if entity.manual_category or entity.manual_group_id:
        return "manual_override"
    if entity.system_needs_review:
        return "needs_review"
    return "auto"
```

In `EntityGroupTable.vue`, surface match reason and status tags:

```vue
<el-table-column prop="match_reason" label="命中说明" width="160" />
<el-table-column label="状态" width="140">
  <template #default="{ row }">
    <el-tag :type="row.classification_status === 'manual_override' ? 'success' : row.classification_status === 'needs_review' ? 'warning' : 'info'">
      {{ row.classification_status }}
    </el-tag>
  </template>
</el-table-column>
```

In `EntityDetailPanel.vue`, show the system signal separately:

```vue
<el-alert
  v-if="entity.system_needs_review"
  title="系统建议仍不稳定，建议人工复核"
  type="warning"
  show-icon
  :closable="false"
/>
```

- [ ] **Step 4: Run full verification**

Run backend tests:

`pytest tests/test_repositories/test_entity_repo.py tests/test_repositories/test_entity_group_repo.py tests/test_services/test_entity_classification_service.py tests/test_services/test_embedding_service_entities.py tests/test_services/test_entity_service.py tests/test_api/test_encyclopedia_routes.py -v`

Expected: PASS

Run frontend build:

`npm run build`

Workdir: `src/novel_dev/web`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/api/routes.py src/novel_dev/web/src/components/entities/EntityGroupTable.vue src/novel_dev/web/src/components/entities/EntityDetailPanel.vue src/novel_dev/web/src/views/Entities.vue tests/test_api/test_encyclopedia_routes.py tests/test_services/test_entity_service.py
git commit -m "feat: finish entity encyclopedia classification flow"
```

## Self-Review

### Spec coverage

- Fixed 6-category classification model: Task 1 and Task 3
- Novel-scoped group registry and custom group control: Task 1 and Task 2
- `Entity.type` compatibility with new `effective_*` classification: Task 1 and Task 4
- `manual_override > needs_review > auto` status behavior and `system_needs_review`: Task 3 and Task 7
- Search-specific embedding boundary via `search_document/search_vector_embedding`: Task 1 and Task 3
- Hybrid search API with grouped results and match reasons: Task 4 and Task 7
- Left-tree/right-workspace UI with detail panel and inline edits: Task 5 and Task 6
- Final verification of backend + frontend behavior: Task 7

### Placeholder scan

- No `TODO`, `TBD`, or “implement later” markers remain.
- Every code-changing step includes concrete file paths and code.
- Every verification step includes an exact command and expected outcome.

### Type consistency

- Entity classification fields use `system_category/system_group_id/manual_category/manual_group_id/search_document/search_vector_embedding/system_needs_review` consistently across tasks.
- Group registry scope is consistently `novel_id + category + group_slug`.
- UI state consistently uses `classification_status`, `system_needs_review`, and `match_reason`.

