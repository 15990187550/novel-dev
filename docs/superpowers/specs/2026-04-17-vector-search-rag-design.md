# Vector Search & RAG 设计文档

**日期:** 2026-04-17  
**范围:** Phase 1 — NovelDocument 向量检索闭环  
**后续阶段:** Phase 2 (Entity), Phase 3 (Chapter)

---

## 1. 背景与目标

### 1.1 当前状态

- `pgvector>=0.2.0` 已在 `pyproject.toml` 中声明
- `NovelDocument` 模型已有 `vector_embedding` 列（`VectorCompat(1536)`）
- `DocumentRepository.create()` 接受 `vector_embedding` 参数，但**从未被调用方传入非 None 值**
- 现有 `VectorCompat` 在 PostgreSQL 下使用 `pgvector.Vector`，在 SQLite 下退化为 `JSON`
- 所有 Agent 上下文组装依赖**精确查询**（`get_by_type`, `find_by_names`），没有语义检索能力

### 1.2 目标

为 `NovelDocument` 建立完整的嵌入-索引-检索闭环：

1. 文档创建/更新时自动生成 embedding
2. Agent 可通过语义搜索找到与当前章节最相关的文档
3. 语义搜索作为精确查询的**补充**，不替代现有行为
4. 测试覆盖 PostgreSQL 向量查询路径和 SQLite 退化路径

---

## 2. 架构设计

### 2.1 新增组件

```
novel_dev/
  llm/
    embedder.py          # BaseEmbedder + OpenAIEmbedder
  services/
    embedding_service.py  # EmbeddingService
  schemas/
    similar_document.py   # SimilarDocument Pydantic model
```

### 2.2 修改组件

```
novel_dev/
  llm/
    factory.py            # 新增 get_embedder()
    models.py             # 新增 EmbeddingConfig
  repositories/
    document_repo.py      # 删除 vector_embedding 参数，新增 similarity_search()
  schemas/
    context.py            # ChapterContext 新增 relevant_documents
  agents/
    context_agent.py      # 集成语义搜索
  api/routes.py           # 创建 ContextAgent 时注入 EmbeddingService
  mcp_server/server.py    # 同上
  llm_config.yaml         # 新增 embedding 配置段
```

---

## 3. 组件设计

### 3.1 Embedding 配置模型

```python
# llm/models.py

class EmbeddingConfig(BaseModel):
    provider: str                    # "openai_compatible" (唯一支持)
    model: str                       # e.g. "text-embedding-3-small"
    base_url: Optional[str] = None
    timeout: int = 30
    retries: int = 3
    dimensions: int = 1536
```

### 3.2 BaseEmbedder 接口

```python
# llm/embedder.py

class BaseEmbedder(ABC):
    @abstractmethod
    async def aembed(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入文本，返回等长的向量列表。"""
        ...

class OpenAIEmbedder(BaseEmbedder):
    def __init__(self, client: AsyncOpenAI, model: str, dimensions: int):
        self.client = client
        self.model = model
        self.dimensions = dimensions

    async def aembed(self, texts: List[str]) -> List[List[float]]:
        resp = await self.client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions,
        )
        return [item.embedding for item in resp.data]
```

**设计理由：**
- Anthropic 没有文本 embedding API，不能放在 `BaseDriver` 中
- 批量 `aembed(texts)` 比单条循环调用效率高
- 维度截断由 `dimensions` 参数控制，与数据库列一致

### 3.3 LLMFactory 扩展

```python
# llm/factory.py

class LLMFactory:
    ...

    def get_embedder(self) -> BaseEmbedder:
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

### 3.4 llm_config.yaml 配置

```yaml
defaults:
  provider: openai_compatible
  timeout: 30
  retries: 2
  temperature: 0.7

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

### 3.5 SimilarDocument Schema

```python
# schemas/similar_document.py

class SimilarDocument(BaseModel):
    doc_id: str
    doc_type: str
    title: str
    content_preview: str          # 前 200 字符
    similarity_score: float       # cosine similarity, 0-1
```

### 3.6 DocumentRepository 变更

**删除：** `create()` 方法的 `vector_embedding` 参数（从未被使用，删除以消除误导）

**新增：** `similarity_search()` 方法

```python
async def similarity_search(
    self,
    novel_id: str,
    query_vector: List[float],
    limit: int = 5,
    doc_type_filter: Optional[str] = None,
) -> List[SimilarDocument]:
    """按向量相似度搜索文档。PostgreSQL 用 pgvector 运算符，SQLite 退化到 Python 计算。"""
    ...
```

**PostgreSQL 路径：**

```sql
SELECT id, doc_type, title, content,
       1 - (vector_embedding <=> :query_vector) AS similarity
FROM novel_documents
WHERE novel_id = :novel_id
  AND vector_embedding IS NOT NULL
  [AND doc_type = :doc_type_filter]
ORDER BY vector_embedding <=> :query_vector
LIMIT :limit
```

**SQLite 退化路径：**

1. 查询 `novel_documents` 中 `novel_id = :novel_id AND vector_embedding IS NOT NULL`
2. Python 侧反序列化 JSON 向量
3. 计算 cosine similarity
4. 排序返回 top-k

### 3.7 EmbeddingService

```python
class EmbeddingService:
    def __init__(
        self,
        session: AsyncSession,
        embedder: BaseEmbedder,
        max_query_length: int = 8000,   # 字符数上限，约对应 2000 tokens 安全余量
    ):
        self.session = session
        self.embedder = embedder
        self.max_query_length = max_query_length

    async def generate_embedding(self, text: str) -> List[float]:
        """生成单条文本的 embedding。超长文本按字符数截断。"""
        truncated = text[:self.max_query_length]
        vectors = await self.embedder.aembed([truncated])
        return vectors[0]

    async def index_document(self, doc_id: str) -> None:
        """
        为指定文档生成 embedding 并写回数据库。
        使用独立 session，失败不抛异常（日志记录）。
        """
        ...

    async def search_similar(
        self,
        novel_id: str,
        query_text: str,
        limit: int = 5,
        doc_type_filter: Optional[str] = None,
    ) -> List[SimilarDocument]:
        """query_text → embedding → similarity_search。"""
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
        """直接用向量搜索（Agent 预生成 query embedding 后调用）。"""
        repo = DocumentRepository(self.session)
        return await repo.similarity_search(
            novel_id, query_vector, limit, doc_type_filter
        )
```

**`index_document` 事务策略：**

```python
async def index_document(self, doc_id: str) -> None:
    # 1. 读文档内容（新 session）
    doc = await DocumentRepository(self.session).get_by_id(doc_id)
    if not doc or not doc.content:
        return

    # 2. 调用 embedding API
    try:
        vector = await self.generate_embedding(doc.content)
    except Exception as exc:
        logger.warning("embedding_generation_failed", extra={"doc_id": doc_id, "error": str(exc)})
        return

    # 3. 写回数据库（复用 session，因为 caller 已在外部管理）
    doc.vector_embedding = vector
    await self.session.flush()
```

**调用时机：** `DocumentService` 创建/更新文档后，通过 `asyncio.create_task(embedding_service.index_document(doc_id))` 异步触发。

### 3.8 ContextAgent 集成

**构造函数变更：**

```python
class ContextAgent:
    def __init__(
        self,
        session: AsyncSession,
        embedding_service: Optional[EmbeddingService] = None,
    ):
        ...
        self.embedding_service = embedding_service
```

**assemble() 新增语义检索：**

```python
async def assemble(self, novel_id: str, chapter_id: str) -> ChapterContext:
    ...
    worldview_doc = await self.doc_repo.get_latest_by_type(novel_id, "worldview")
    worldview_summary = worldview_doc.content if worldview_doc else ""

    # 新增：语义搜索补充
    relevant_docs: List[SimilarDocument] = []
    if self.embedding_service:
        query_text = self._build_search_query(chapter_plan)
        try:
            results = await self.embedding_service.search_similar(
                novel_id=novel_id,
                query_text=query_text,
                limit=3,
            )
            # 过滤已精确查询到的 worldview_doc
            exclude_id = worldview_doc.id if worldview_doc else None
            relevant_docs = [r for r in results if r.doc_id != exclude_id]
        except Exception as exc:
            logger.warning("semantic_search_failed", extra={"novel_id": novel_id, "error": str(exc)})

    ...
    context = ChapterContext(
        ...
        worldview_summary=worldview_summary,
        relevant_documents=relevant_docs,
        ...
    )
    ...
```

**Query 构建策略：**

```python
def _build_search_query(self, chapter_plan: ChapterPlan) -> str:
    parts = []
    if chapter_plan.title:
        parts.append(chapter_plan.title)
    # beats 前两个的 summary 拼接，提供足够的语义信号
    for beat in chapter_plan.beats[:2]:
        parts.append(beat.summary)
    return "\n".join(parts)[:8000]  # 截断到安全长度
```

**ChapterContext 变更：**

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

**为什么新增字段 backward compatible：**
- Pydantic v2 缺失字段自动用默认值填充
- 旧 checkpoint 数据反序列化时 `relevant_documents=[]`

### 3.9 WriterAgent Prompt 改造

`relevant_documents` 必须通过显式引导语让 LLM 使用，否则会被淹没在巨大的 JSON 上下文中。

**`writer_agent.py` `_generate_beat` 方法变更：**

```python
async def _generate_beat(self, beat: BeatPlan, context: ChapterContext, previous_text: str) -> str:
    relevant_docs_text = ""
    if context.relevant_documents:
        docs_block = "\n\n".join(
            f"[{d.doc_type}] {d.title}\n{d.content_preview}"
            for d in context.relevant_documents
        )
        relevant_docs_text = (
            f"\n\n### 相关设定补充（与本节拍高度相关，写作时请优先参考）\n"
            f"{docs_block}\n"
        )

    prompt = (
        "你是一位小说创作助手。请根据以下节拍计划和上下文，生成该节拍的正文。"
        "要求：只返回正文内容，不添加解释。\n\n"
        f"### 节拍计划\n{beat.model_dump_json()}\n\n"
        f"### 章节上下文\n{context.model_dump_json()}\n\n"
        f"{relevant_docs_text}"
        f"### 已写文本\n{previous_text}\n\n"
        "请生成正文："
    )
    ...
```

**设计要点：**
- `relevant_docs_text` 放在 `章节上下文` 之后、`已写文本` 之前，形成"计划 → 背景 → 补充设定 → 已写内容"的信息流
- 引导语明确指示"与本节拍高度相关，写作时请优先参考"
- 只取 `content_preview`（前 200 字），避免单个文档占用过多 token
- 如果 `relevant_documents` 为空，该区块不出现，prompt 长度不膨胀

**`_rewrite_angle` 方法同步改造：**

扩写时同样需要相关设定补充，复用相同的 `relevant_docs_text` 构建逻辑。

### 3.10 生产代码调用点变更

**api/routes.py:342**

```python
@router.post("/api/novels/{novel_id}/chapters/{chapter_id}/context")
async def prepare_chapter_context(...):
    embedder = llm_factory.get_embedder()
    embedding_service = EmbeddingService(session, embedder)
    agent = ContextAgent(session, embedding_service)
    ...
```

**mcp_server/server.py:183**

```python
async def prepare_chapter_context(novel_id: str, chapter_id: str) -> dict:
    async with async_session_maker() as session:
        embedder = llm_factory.get_embedder()
        embedding_service = EmbeddingService(session, embedder)
        agent = ContextAgent(session, embedding_service)
        ...
```

---

## 4. 数据库变更

### 4.1 现有列

`NovelDocument.vector_embedding`（`VectorCompat(1536)`）已存在，无需新增列。

### 4.2 需要的新 Migration

**启用 pgvector 扩展（PostgreSQL 环境）：**

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
```

**创建向量索引（可选，Phase 1 可延后）：**

```sql
CREATE INDEX idx_novel_documents_vector
ON novel_documents
USING hnsw (vector_embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

HNSW 索引在文档量 < 10k 时收益不明显，可放在 Phase 1 之后按需添加。

---

## 5. 测试策略

### 5.1 新增测试文件

| 文件 | 覆盖范围 |
|------|----------|
| `tests/llm/test_embedder.py` | `OpenAIEmbedder.aembed()` 批量调用、维度截断、异常映射 |
| `tests/llm/test_factory_embedder.py` | `LLMFactory.get_embedder()` 配置解析、缺失配置抛错 |
| `tests/test_repositories/test_document_repo_similarity.py` | `similarity_search()` SQLite 退化路径 |
| `tests/test_services/test_embedding_service.py` | `generate_embedding`, `index_document`, `search_similar` |
| `tests/test_agents/test_context_agent_semantic.py` | `ContextAgent` 传入 mock `EmbeddingService`，验证 `relevant_documents` |

### 5.2 PostgreSQL 路径测试

现有测试全部跑在 SQLite 上，无法执行 `<=>` 向量运算符。为 `DocumentRepository.similarity_search()` 的 PostgreSQL 路径写 mock 测试：

```python
@pytest.mark.asyncio
async def test_similarity_search_postgres_sql():
    """Mock PostgreSQL dialect，验证 SQL 生成正确。"""
    ...
```

### 5.3 集成测试

`test_integration_end_to_end.py` 已有多章节端到端测试。验证：
- 文档创建后 `vector_embedding` 被异步填充（或至少接口被调用）
- `ContextAgent.assemble()` 在 `EmbeddingService` 可用时返回 `relevant_documents`

### 5.4 现有测试保护

- `test_context_agent.py` 的 3 个测试保持 `ContextAgent(async_session)`（不传 embedding_service），验证语义搜索静默跳过
- 所有 203 个现有测试必须继续通过

---

## 6. 错误处理

| 场景 | 行为 |
|------|------|
| Embedding API 失败 | `index_document` 日志 warning，不抛异常，不影响文档创建 |
| 语义搜索失败 | `ContextAgent.assemble()` 日志 warning，`relevant_documents=[]`，不影响主流程 |
| `llm_config.yaml` 缺少 embedding 配置 | `LLMFactory.get_embedder()` 抛 `LLMConfigError`，启动时即发现 |
| 数据库中无 embedding 数据 | `similarity_search` 返回 `[]` |
| SQLite 环境 | 自动退化到 Python 侧 cosine 计算 |

---

## 7. Phase 规划

### Phase 1: NovelDocument 闭环（本文档范围）

- LLMFactory `get_embedder()` + `BaseEmbedder` + `OpenAIEmbedder`
- `DocumentRepository.similarity_search()`（PG + SQLite 双路径）
- `EmbeddingService`
- `ContextAgent` 集成语义搜索
- 完整测试覆盖

### Phase 2: Entity 语义检索

- `Entity` 表新增 `vector_embedding` 列
- `EntityRepository.similarity_search()`
- `ContextAgent._load_active_entities()` 增强：除精确 name 匹配外，补充语义相似实体

### Phase 3: Chapter 语义检索

- `Chapter` 表新增 `vector_embedding` 列（存储 polished_text 或摘要的 embedding）
- `ChapterRepository.similarity_search()`
- WriterAgent 可检索"风格/主题相似的过往章节"

---

## 8. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Embedding API 调用慢，阻塞 API 响应 | 中 | 高 | `index_document` 用 `asyncio.create_task()` 异步触发；语义搜索在 `ContextAgent` 中同步调用但 limit=3，单次调用 |
| pgvector 扩展未在 PostgreSQL 中启用 | 中 | 高 | Migration 执行 `CREATE EXTENSION IF NOT EXISTS vector`；运行时检查 |
| 向量维度与模型不匹配 | 低 | 高 | `EmbeddingConfig.dimensions` 必须与 `VectorCompat` 一致；配置校验 |
| SQLite 测试无法覆盖 PG 向量路径 | 高 | 中 | mock dialect 测试 SQL 生成；CI 可配置 PostgreSQL 集成测试 |
| API key 成本 | 低 | 低 | `text-embedding-3-small` 成本极低；批量嵌入降低调用次数 |

---

## 9. 决策记录

1. **为什么 embedding 不放在 `BaseDriver` 中？** Anthropic 没有文本 embedding API，部分实现会破坏抽象完整性。Embedding 是独立能力，用独立接口更诚实。
2. **为什么 `DocumentRepository.create()` 删除 `vector_embedding` 参数？** 从未被使用，存在即误导。Embedding 生成与文档创建解耦，各走各的事务。
3. **为什么 SQLite 退化到 Python 计算？** `VectorCompat` 在 SQLite 下存 JSON，无法使用 pgvector 运算符。Python 侧计算保证测试环境可用。
4. **为什么语义搜索不替代精确查询？** worldview 等核心文档必须取最新精确版本，语义搜索可能返回过时碎片。两者互补。
5. **为什么 ContextAgent 加可选参数而不是重构 DI？** 项目当前没有 DI 容器，加可选参数是最小侵入的改动。仅 2 个生产代码调用点需要修改。
