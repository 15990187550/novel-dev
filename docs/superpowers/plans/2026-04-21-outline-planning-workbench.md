# Outline Planning Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有“卷规划”页面升级成“`大纲规划`”工作台，支持左侧总纲/卷纲列表、右侧详情展示，以及按大纲项独立上下文的对话式优化。

**Architecture:** 后端新增 `outline_session + outline_message` 持久层与 `OutlineWorkbenchService`，统一负责会话读写、上下文压缩和 agent 路由；API 暴露“大纲列表/详情/消息/提交意见”四组能力。前端在现有 `VolumePlan.vue` 基础上拆出 sidebar/detail/conversation 组件，并通过 store 聚合成统一的大纲工作台状态。

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, Vue 3, Pinia, Element Plus, Vitest, pytest

---

## File Structure

### Backend

- Modify: `src/novel_dev/db/models.py`
  - 新增 `OutlineSession`、`OutlineMessage` ORM 模型
- Create: `migrations/versions/20260421_add_outline_workbench_sessions.py`
  - 创建会话与消息表
- Create: `src/novel_dev/schemas/outline_workbench.py`
  - 定义 `OutlineItemSummary`、`OutlineSessionPayload`、`OutlineMessagePayload`、`OutlineSubmitRequest`
- Create: `src/novel_dev/repositories/outline_session_repo.py`
  - 负责按 `novel_id + outline_type + outline_ref` 读取/创建会话
- Create: `src/novel_dev/repositories/outline_message_repo.py`
  - 负责写入和读取会话消息
- Create: `src/novel_dev/services/outline_workbench_service.py`
  - 负责构建左侧列表、详情快照、上下文摘要、agent 调用和结果写回
- Modify: `src/novel_dev/api/routes.py`
  - 新增大纲工作台相关接口

### Backend Tests

- Create: `tests/test_repositories/test_outline_workbench_repos.py`
- Create: `tests/test_services/test_outline_workbench_service.py`
- Create: `tests/test_api/test_outline_workbench_routes.py`

### Frontend

- Modify: `src/novel_dev/web/src/api.js`
  - 新增 workbench API 方法
- Modify: `src/novel_dev/web/src/api.test.js`
  - 覆盖静默接口与新增 POST 请求
- Modify: `src/novel_dev/web/src/stores/novel.js`
  - 新增 workbench 状态、加载方法、提交方法
- Modify: `src/novel_dev/web/src/stores/novel.test.js`
  - 覆盖大纲列表、详情切换、提交状态
- Create: `src/novel_dev/web/src/views/outline/outlineWorkbench.js`
  - 组装左侧 `outline items` 与右侧详情元数据
- Create: `src/novel_dev/web/src/views/outline/outlineWorkbench.test.js`
- Create: `src/novel_dev/web/src/components/outline/OutlineSidebar.vue`
- Create: `src/novel_dev/web/src/components/outline/OutlineDetailPanel.vue`
- Create: `src/novel_dev/web/src/components/outline/OutlineConversation.vue`
- Create: `src/novel_dev/web/src/components/outline/OutlineEmptyState.vue`
- Create: `src/novel_dev/web/src/components/outline/OutlineSidebar.test.js`
- Create: `src/novel_dev/web/src/components/outline/OutlineConversation.test.js`
- Modify: `src/novel_dev/web/src/views/VolumePlan.vue`
  - 改为 `大纲规划` 左右布局装配页

### Final Verification

- Modify: 无新增文档，最终只跑测试与构建

---

### Task 1: Add Outline Workbench Persistence

**Files:**
- Modify: `src/novel_dev/db/models.py`
- Create: `migrations/versions/20260421_add_outline_workbench_sessions.py`
- Create: `src/novel_dev/repositories/outline_session_repo.py`
- Create: `src/novel_dev/repositories/outline_message_repo.py`
- Test: `tests/test_repositories/test_outline_workbench_repos.py`

- [ ] **Step 1: Write the failing repository test**

```python
async def test_outline_session_repo_creates_and_reuses_session(async_session):
    repo = OutlineSessionRepository(async_session)

    first = await repo.get_or_create(
        novel_id="novel-1",
        outline_type="synopsis",
        outline_ref="synopsis",
    )
    second = await repo.get_or_create(
        novel_id="novel-1",
        outline_type="synopsis",
        outline_ref="synopsis",
    )

    assert first.id == second.id
    assert first.status == "idle"


async def test_outline_message_repo_lists_latest_messages(async_session):
    session_repo = OutlineSessionRepository(async_session)
    message_repo = OutlineMessageRepository(async_session)
    session = await session_repo.get_or_create(
        novel_id="novel-1",
        outline_type="volume",
        outline_ref="1",
    )

    await message_repo.create(session.id, role="user", message_type="instruction", content="强化冲突")
    await message_repo.create(session.id, role="assistant", message_type="result", content="已强化第一卷冲突")
    await async_session.commit()

    messages = await message_repo.list_recent(session.id, limit=10)
    assert [message.role for message in messages] == ["user", "assistant"]
```

- [ ] **Step 2: Run the repository test to verify it fails**

Run: `pytest tests/test_repositories/test_outline_workbench_repos.py -v`

Expected: FAIL with import error for `OutlineSessionRepository` / `OutlineMessageRepository`

- [ ] **Step 3: Add ORM models and migration**

```python
class OutlineSession(Base):
    __tablename__ = "outline_sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    outline_type: Mapped[str] = mapped_column(Text, nullable=False)
    outline_ref: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="idle")
    conversation_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_result_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


class OutlineMessage(Base):
    __tablename__ = "outline_messages"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("outline_sessions.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
```

```python
def upgrade() -> None:
    op.create_table(
        "outline_sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("outline_type", sa.Text(), nullable=False),
        sa.Column("outline_ref", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("conversation_summary", sa.Text(), nullable=True),
        sa.Column("last_result_snapshot", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False),
    )
    op.create_index("ix_outline_sessions_lookup", "outline_sessions", ["novel_id", "outline_type", "outline_ref"], unique=True)

    op.create_table(
        "outline_messages",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("session_id", sa.Text(), sa.ForeignKey("outline_sessions.id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("message_type", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False),
    )
    op.create_index("ix_outline_messages_session_id", "outline_messages", ["session_id"], unique=False)
```

- [ ] **Step 4: Add repository methods with minimal behavior**

```python
class OutlineSessionRepository:
    async def get_or_create(self, novel_id: str, outline_type: str, outline_ref: str) -> OutlineSession:
        stmt = select(OutlineSession).where(
            OutlineSession.novel_id == novel_id,
            OutlineSession.outline_type == outline_type,
            OutlineSession.outline_ref == outline_ref,
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing

        item = OutlineSession(
            id=f"{novel_id}:{outline_type}:{outline_ref}",
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            status="idle",
        )
        self.session.add(item)
        await self.session.flush()
        return item
```

```python
class OutlineMessageRepository:
    async def create(self, session_id: str, role: str, message_type: str, content: str, meta: dict | None = None) -> OutlineMessage:
        item = OutlineMessage(
            id=f"{session_id}:{uuid4().hex}",
            session_id=session_id,
            role=role,
            message_type=message_type,
            content=content,
            meta=meta or {},
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_recent(self, session_id: str, limit: int = 20) -> list[OutlineMessage]:
        stmt = (
            select(OutlineMessage)
            .where(OutlineMessage.session_id == session_id)
            .order_by(OutlineMessage.created_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())
```

- [ ] **Step 5: Run repository tests and migration-facing tests**

Run: `pytest tests/test_repositories/test_outline_workbench_repos.py -v`

Expected: PASS with `2 passed`

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/db/models.py migrations/versions/20260421_add_outline_workbench_sessions.py src/novel_dev/repositories/outline_session_repo.py src/novel_dev/repositories/outline_message_repo.py tests/test_repositories/test_outline_workbench_repos.py
git commit -m "feat: add outline workbench persistence"
```

---

### Task 2: Add Outline Workbench Service and Context Compression

**Files:**
- Create: `src/novel_dev/schemas/outline_workbench.py`
- Create: `src/novel_dev/services/outline_workbench_service.py`
- Test: `tests/test_services/test_outline_workbench_service.py`

- [ ] **Step 1: Write the failing service test**

```python
async def test_build_outline_items_includes_synopsis_and_missing_volumes(async_session):
    service = OutlineWorkbenchService(async_session)

    payload = await service.build_workbench(novel_id="novel-1")

    assert payload.items[0].outline_type == "synopsis"
    assert payload.items[0].title == "总纲"
    assert any(item.outline_type == "volume" and item.status == "missing" for item in payload.items)


async def test_submit_feedback_routes_to_volume_planner(async_session, monkeypatch):
    called = {}

    async def fake_optimize_volume(**kwargs):
        called["outline_type"] = kwargs["outline_type"]
        return {
            "result_snapshot": {"volume_number": 1, "title": "第一卷", "summary": "强化后摘要"},
            "assistant_message": "已强化第一卷冲突",
            "summary": "用户要求强化第一卷冲突",
        }

    service = OutlineWorkbenchService(async_session)
    monkeypatch.setattr(service, "_optimize_outline", fake_optimize_volume)

    response = await service.submit_feedback(
        novel_id="novel-1",
        outline_type="volume",
        outline_ref="1",
        content="强化第一卷冲突",
    )

    assert called["outline_type"] == "volume"
    assert response.assistant_message == "已强化第一卷冲突"
```

- [ ] **Step 2: Run the service test to verify it fails**

Run: `pytest tests/test_services/test_outline_workbench_service.py -v`

Expected: FAIL with import error for `OutlineWorkbenchService`

- [ ] **Step 3: Add service-facing schemas**

```python
class OutlineItemSummary(BaseModel):
    outline_type: Literal["synopsis", "volume"]
    outline_ref: str
    title: str
    status: Literal["ready", "missing", "generating", "updating", "error"]
    updated_at: datetime | None = None
    message_count: int = 0
    summary_hint: str = ""
    is_current: bool = False


class OutlineSubmitResponse(BaseModel):
    outline_type: Literal["synopsis", "volume"]
    outline_ref: str
    assistant_message: str
    conversation_summary: str
    result_snapshot: dict
```

- [ ] **Step 4: Implement workbench assembly and context helpers**

```python
class OutlineWorkbenchService:
    async def build_outline_items(self, novel_id: str) -> list[OutlineItemSummary]:
        state = await NovelStateRepository(self.session).get(novel_id)
        synopsis_data = (state.checkpoint_data or {}).get("synopsis_data") or {}
        current_plan = (state.checkpoint_data or {}).get("current_volume_plan") or {}
        estimated_volumes = synopsis_data.get("estimated_volumes") or 1

        items = [
            OutlineItemSummary(
                outline_type="synopsis",
                outline_ref="synopsis",
                title="总纲",
                status="ready" if synopsis_data else "missing",
                summary_hint=synopsis_data.get("logline", ""),
            )
        ]
        for volume_number in range(1, estimated_volumes + 1):
            is_current = current_plan.get("volume_number") == volume_number
            items.append(
                OutlineItemSummary(
                    outline_type="volume",
                    outline_ref=str(volume_number),
                    title=f"第 {volume_number} 卷",
                    status="ready" if is_current and current_plan else "missing",
                    summary_hint=(current_plan.get("summary") if is_current else "尚未生成卷纲") or "尚未生成卷纲",
                )
            )
        return items

    def _build_context_window(self, last_result_snapshot: dict | None, conversation_summary: str | None, recent_messages: list[OutlineMessage]) -> dict:
        return {
            "last_result_snapshot": last_result_snapshot or {},
            "conversation_summary": conversation_summary or "",
            "recent_messages": [
                {"role": message.role, "content": message.content}
                for message in recent_messages[-6:]
            ],
        }
```

- [ ] **Step 5: Implement submission flow and write-back**

```python
async def submit_feedback(self, novel_id: str, outline_type: str, outline_ref: str, content: str) -> OutlineSubmitResponse:
    session = await self.session_repo.get_or_create(novel_id, outline_type, outline_ref)
    recent_messages = await self.message_repo.list_recent(session.id, limit=12)
    context_window = self._build_context_window(session.last_result_snapshot, session.conversation_summary, recent_messages)

    await self.message_repo.create(session.id, role="user", message_type="instruction", content=content)
    result = await self._optimize_outline(
        novel_id=novel_id,
        outline_type=outline_type,
        outline_ref=outline_ref,
        content=content,
        context_window=context_window,
    )

    session.status = "idle"
    session.last_result_snapshot = result["result_snapshot"]
    session.conversation_summary = result["summary"]
    await self.message_repo.create(session.id, role="assistant", message_type="result", content=result["assistant_message"])
    await self._write_result_snapshot(novel_id, outline_type, result["result_snapshot"])
    await self.session.commit()

    return OutlineSubmitResponse(
        outline_type=outline_type,
        outline_ref=outline_ref,
        assistant_message=result["assistant_message"],
        conversation_summary=result["summary"],
        result_snapshot=result["result_snapshot"],
    )
```

- [ ] **Step 6: Run service tests**

Run: `pytest tests/test_services/test_outline_workbench_service.py -v`

Expected: PASS with `2 passed`

- [ ] **Step 7: Commit**

```bash
git add src/novel_dev/schemas/outline_workbench.py src/novel_dev/services/outline_workbench_service.py tests/test_services/test_outline_workbench_service.py
git commit -m "feat: add outline workbench service"
```

---

### Task 3: Add Outline Workbench API Endpoints

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Test: `tests/test_api/test_outline_workbench_routes.py`

- [ ] **Step 1: Write the failing API test**

```python
@pytest.mark.asyncio
async def test_get_outline_workbench_returns_sidebar_items(async_session, test_client):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel-outline",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={
            "synopsis_data": {
                "title": "测试小说",
                "logline": "主角复仇",
                "estimated_volumes": 3,
                "estimated_total_chapters": 90,
                "estimated_total_words": 900000,
            }
        },
        volume_id=None,
        chapter_id=None,
    )
    await async_session.commit()

    async with test_client as client:
        resp = await client.get("/api/novels/novel-outline/outline_workbench")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"][0]["title"] == "总纲"
        assert data["items"][1]["title"] == "第 1 卷"


@pytest.mark.asyncio
async def test_submit_outline_feedback_returns_updated_snapshot(async_session, test_client, monkeypatch):
    async def fake_submit_feedback(self, novel_id, outline_type, outline_ref, content):
        return OutlineSubmitResponse(
            outline_type=outline_type,
            outline_ref=outline_ref,
            assistant_message="已强化冲突",
            conversation_summary="用户要求强化冲突",
            result_snapshot={"title": "测试小说", "logline": "更强冲突"},
        )

    monkeypatch.setattr(OutlineWorkbenchService, "submit_feedback", fake_submit_feedback)

    async with test_client as client:
        resp = await client.post(
            "/api/novels/novel-outline/outline_workbench/submit",
            json={"outline_type": "synopsis", "outline_ref": "synopsis", "content": "强化冲突"},
        )
        assert resp.status_code == 200
        assert resp.json()["assistant_message"] == "已强化冲突"
```

- [ ] **Step 2: Run the API test to verify it fails**

Run: `pytest tests/test_api/test_outline_workbench_routes.py -v`

Expected: FAIL with 404 for `/outline_workbench`

- [ ] **Step 3: Add request model and GET endpoints**

```python
class OutlineWorkbenchSubmitRequest(BaseModel):
    outline_type: str
    outline_ref: str
    content: str = Field(min_length=1)


@router.get("/api/novels/{novel_id}/outline_workbench")
async def get_outline_workbench(novel_id: str, session: AsyncSession = Depends(get_session)):
    service = OutlineWorkbenchService(session)
    return await service.build_workbench(novel_id)


@router.get("/api/novels/{novel_id}/outline_workbench/messages")
async def get_outline_workbench_messages(
    novel_id: str,
    outline_type: str,
    outline_ref: str,
    session: AsyncSession = Depends(get_session),
):
    service = OutlineWorkbenchService(session)
    return await service.get_messages(novel_id, outline_type, outline_ref)
```

- [ ] **Step 4: Add submit endpoint**

```python
@router.post("/api/novels/{novel_id}/outline_workbench/submit")
async def submit_outline_feedback(
    novel_id: str,
    req: OutlineWorkbenchSubmitRequest,
    session: AsyncSession = Depends(get_session),
):
    service = OutlineWorkbenchService(session)
    return await service.submit_feedback(
        novel_id=novel_id,
        outline_type=req.outline_type,
        outline_ref=req.outline_ref,
        content=req.content.strip(),
    )
```

- [ ] **Step 5: Run API tests**

Run: `pytest tests/test_api/test_outline_workbench_routes.py tests/test_api/test_outline_routes.py -v`

Expected: PASS and no regression in existing synopsis / volume plan routes

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_outline_workbench_routes.py
git commit -m "feat: add outline workbench api"
```

---

### Task 4: Add Frontend API, Store, and Derived View Model

**Files:**
- Modify: `src/novel_dev/web/src/api.js`
- Modify: `src/novel_dev/web/src/api.test.js`
- Modify: `src/novel_dev/web/src/stores/novel.js`
- Modify: `src/novel_dev/web/src/stores/novel.test.js`
- Create: `src/novel_dev/web/src/views/outline/outlineWorkbench.js`
- Create: `src/novel_dev/web/src/views/outline/outlineWorkbench.test.js`

- [ ] **Step 1: Write the failing frontend helper/store tests**

```javascript
it('buildOutlineSelection normalizes synopsis and volume items', () => {
  const result = buildOutlineSelection({
    items: [
      { outline_type: 'synopsis', outline_ref: 'synopsis', title: '总纲', status: 'ready', summary_hint: '主线冲突' },
      { outline_type: 'volume', outline_ref: '1', title: '第 1 卷', status: 'missing', summary_hint: '尚未生成卷纲' },
    ],
    currentSelection: { outlineType: 'synopsis', outlineRef: 'synopsis' },
  })

  expect(result[0].isCurrent).toBe(true)
  expect(result[1].statusLabel).toBe('待生成')
})


it('refreshOutlineWorkbench stores items and selects synopsis by default', async () => {
  api.getOutlineWorkbench.mockResolvedValue({
    items: [{ outline_type: 'synopsis', outline_ref: 'synopsis', title: '总纲', status: 'ready', summary_hint: '主线冲突' }],
    detail: { outline_type: 'synopsis', outline_ref: 'synopsis', snapshot: { title: '测试小说' } },
  })
  api.getOutlineWorkbenchMessages.mockResolvedValue({ items: [] })

  const store = useNovelStore()
  store.novelId = 'novel-1'
  await store.refreshOutlineWorkbench()

  expect(store.outlineWorkbench.items).toHaveLength(1)
  expect(store.outlineWorkbench.selection.outlineType).toBe('synopsis')
})
```

- [ ] **Step 2: Run the frontend tests to verify they fail**

Run: `cd src/novel_dev/web && npm run test -- src/views/outline/outlineWorkbench.test.js src/stores/novel.test.js`

Expected: FAIL with missing exports `getOutlineWorkbench` / `refreshOutlineWorkbench`

- [ ] **Step 3: Add API methods and helper builder**

```javascript
export const getOutlineWorkbench = (id, params = {}) =>
  api.get(`/novels/${id}/outline_workbench`, { params }).then((r) => r.data)

export const getOutlineWorkbenchMessages = (id, params) =>
  api.get(`/novels/${id}/outline_workbench/messages`, { params }).then((r) => r.data)

export const submitOutlineFeedback = (id, payload) =>
  api.post(`/novels/${id}/outline_workbench/submit`, payload).then((r) => r.data)
```

```javascript
export function buildOutlineSelection({ items = [], currentSelection = null } = {}) {
  return items.map((item) => ({
    ...item,
    isCurrent:
      item.outline_type === currentSelection?.outlineType &&
      item.outline_ref === currentSelection?.outlineRef,
    statusLabel:
      item.status === 'missing' ? '待生成' :
      item.status === 'updating' ? '优化中' :
      item.status === 'error' ? '失败' : '可用',
  }))
}
```

- [ ] **Step 4: Add store state and actions**

```javascript
outlineWorkbench: {
  loading: false,
  items: [],
  detail: null,
  messages: [],
  selection: { outlineType: 'synopsis', outlineRef: 'synopsis' },
  submitting: false,
  error: '',
},
```

```javascript
async refreshOutlineWorkbench(selection = this.outlineWorkbench.selection) {
  if (!this.novelId) return
  this.outlineWorkbench.loading = true
  try {
    const data = await api.getOutlineWorkbench(this.novelId, {
      outline_type: selection?.outlineType,
      outline_ref: selection?.outlineRef,
    })
    this.outlineWorkbench.items = data.items
    this.outlineWorkbench.detail = data.detail
    this.outlineWorkbench.selection = {
      outlineType: data.detail?.outline_type || 'synopsis',
      outlineRef: data.detail?.outline_ref || 'synopsis',
    }
    const messages = await api.getOutlineWorkbenchMessages(this.novelId, {
      outline_type: this.outlineWorkbench.selection.outlineType,
      outline_ref: this.outlineWorkbench.selection.outlineRef,
    })
    this.outlineWorkbench.messages = messages.items || []
  } finally {
    this.outlineWorkbench.loading = false
  }
}
```

- [ ] **Step 5: Add submit action**

```javascript
async submitOutlineFeedback(content) {
  this.outlineWorkbench.submitting = true
  try {
    const { outlineType, outlineRef } = this.outlineWorkbench.selection
    const response = await api.submitOutlineFeedback(this.novelId, {
      outline_type: outlineType,
      outline_ref: outlineRef,
      content,
    })
    await this.refreshOutlineWorkbench({ outlineType, outlineRef })
    return response
  } finally {
    this.outlineWorkbench.submitting = false
  }
}
```

- [ ] **Step 6: Run frontend helper and store tests**

Run: `cd src/novel_dev/web && npm run test -- src/views/outline/outlineWorkbench.test.js src/stores/novel.test.js src/api.test.js`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/novel_dev/web/src/api.js src/novel_dev/web/src/api.test.js src/novel_dev/web/src/stores/novel.js src/novel_dev/web/src/stores/novel.test.js src/novel_dev/web/src/views/outline/outlineWorkbench.js src/novel_dev/web/src/views/outline/outlineWorkbench.test.js
git commit -m "feat: add outline workbench frontend data flow"
```

---

### Task 5: Build Outline Workbench Components and Page Layout

**Files:**
- Create: `src/novel_dev/web/src/components/outline/OutlineSidebar.vue`
- Create: `src/novel_dev/web/src/components/outline/OutlineDetailPanel.vue`
- Create: `src/novel_dev/web/src/components/outline/OutlineConversation.vue`
- Create: `src/novel_dev/web/src/components/outline/OutlineEmptyState.vue`
- Create: `src/novel_dev/web/src/components/outline/OutlineSidebar.test.js`
- Create: `src/novel_dev/web/src/components/outline/OutlineConversation.test.js`
- Modify: `src/novel_dev/web/src/views/VolumePlan.vue`

- [ ] **Step 1: Write the failing component tests**

```javascript
it('renders synopsis and volume items in the sidebar', () => {
  const wrapper = mount(OutlineSidebar, {
    props: {
      items: [
        { outline_type: 'synopsis', outline_ref: 'synopsis', title: '总纲', statusLabel: '可用', isCurrent: true },
        { outline_type: 'volume', outline_ref: '1', title: '第 1 卷', statusLabel: '待生成', isCurrent: false },
      ],
    },
  })

  expect(wrapper.text()).toContain('总纲')
  expect(wrapper.text()).toContain('第 1 卷')
  expect(wrapper.text()).toContain('待生成')
})


it('emits submit when sending conversation input', async () => {
  const wrapper = mount(OutlineConversation, {
    props: {
      messages: [],
      submitting: false,
    },
  })

  await wrapper.find('textarea').setValue('强化第二卷冲突')
  await wrapper.find('button').trigger('click')

  expect(wrapper.emitted('submit-feedback')[0]).toEqual(['强化第二卷冲突'])
})
```

- [ ] **Step 2: Run the component tests to verify they fail**

Run: `cd src/novel_dev/web && npm run test -- src/components/outline/OutlineSidebar.test.js src/components/outline/OutlineConversation.test.js`

Expected: FAIL with missing components

- [ ] **Step 3: Implement sidebar and detail components**

```vue
<template>
  <aside class="w-full lg:w-72 rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
    <div class="mb-3 text-lg font-bold">大纲规划</div>
    <button
      v-for="item in items"
      :key="`${item.outline_type}:${item.outline_ref}`"
      class="mb-2 w-full rounded-lg border px-3 py-3 text-left"
      :class="item.isCurrent ? 'border-blue-500 bg-blue-50' : 'border-gray-200 bg-white'"
      @click="$emit('select', item)"
    >
      <div class="font-medium">{{ item.title }}</div>
      <div class="mt-1 text-xs text-gray-500">{{ item.summary_hint }}</div>
      <div class="mt-2 text-xs text-gray-400">{{ item.statusLabel }}</div>
    </button>
  </aside>
</template>
```

```vue
<template>
  <section class="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
    <div v-if="detail?.outline_type === 'synopsis'">
      <h3 class="text-2xl font-bold">{{ detail.snapshot.title }}</h3>
      <p class="mt-2 whitespace-pre-wrap text-gray-600">{{ detail.snapshot.logline }}</p>
    </div>
    <OutlineEmptyState
      v-else-if="detail?.status === 'missing'"
      title="当前卷尚未生成卷纲"
      description="可以直接在下方输入修改意见或要求先生成本卷卷纲。"
    />
  </section>
</template>
```

- [ ] **Step 4: Implement conversation component and page assembly**

```vue
<template>
  <section class="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
    <div class="max-h-80 space-y-3 overflow-auto">
      <div v-for="message in messages" :key="message.id" class="rounded-lg px-3 py-2" :class="message.role === 'user' ? 'bg-gray-100' : 'bg-blue-50'">
        <div class="text-xs text-gray-400">{{ message.role === 'user' ? '你' : '系统' }}</div>
        <div class="mt-1 whitespace-pre-wrap text-sm">{{ message.content }}</div>
      </div>
    </div>
    <el-input v-model="draft" type="textarea" :rows="4" class="mt-4" />
    <div class="mt-3 flex justify-end">
      <el-button type="primary" :loading="submitting" @click="submit">发送修改意见</el-button>
    </div>
  </section>
</template>
```

```vue
<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-bold">大纲规划</h2>
    </div>
    <div v-if="!store.novelId" class="py-10 text-center text-gray-400">请先选择小说</div>
    <div v-else class="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <OutlineSidebar :items="sidebarItems" @select="handleSelect" />
      <div class="space-y-4">
        <OutlineDetailPanel :detail="store.outlineWorkbench.detail" />
        <OutlineConversation :messages="store.outlineWorkbench.messages" :submitting="store.outlineWorkbench.submitting" @submit-feedback="handleSubmit" />
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 5: Run component and page tests**

Run: `cd src/novel_dev/web && npm run test -- src/components/outline/OutlineSidebar.test.js src/components/outline/OutlineConversation.test.js`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/web/src/components/outline/OutlineSidebar.vue src/novel_dev/web/src/components/outline/OutlineDetailPanel.vue src/novel_dev/web/src/components/outline/OutlineConversation.vue src/novel_dev/web/src/components/outline/OutlineEmptyState.vue src/novel_dev/web/src/components/outline/OutlineSidebar.test.js src/novel_dev/web/src/components/outline/OutlineConversation.test.js src/novel_dev/web/src/views/VolumePlan.vue
git commit -m "feat: build outline planning workbench ui"
```

---

### Task 6: Integrate Loading Lifecycle and Run Full Verification

**Files:**
- Modify: `src/novel_dev/web/src/views/VolumePlan.vue`
- Modify: `src/novel_dev/web/src/stores/novel.js`
- Test: `tests/test_api/test_outline_workbench_routes.py`
- Test: `src/novel_dev/web/src/stores/novel.test.js`
- Test: `src/novel_dev/web/src/views/outline/outlineWorkbench.test.js`

- [ ] **Step 1: Add page lifecycle coverage**

```javascript
it('loads outline workbench when novel id changes', async () => {
  const store = useNovelStore()
  store.novelId = 'novel-1'
  store.refreshOutlineWorkbench = vi.fn().mockResolvedValue()

  mount(VolumePlan, {
    global: {
      plugins: [createPinia()],
    },
  })

  expect(store.refreshOutlineWorkbench).toHaveBeenCalled()
})
```

- [ ] **Step 2: Run the new lifecycle test to verify it fails**

Run: `cd src/novel_dev/web && npm run test -- src/stores/novel.test.js src/views/outline/outlineWorkbench.test.js`

Expected: FAIL until `VolumePlan.vue` wires `onMounted` / `watch`

- [ ] **Step 3: Wire page lifecycle and selection refresh**

```javascript
watch(
  () => store.novelId,
  async (novelId) => {
    if (!novelId) return
    await store.refreshOutlineWorkbench()
  },
  { immediate: true }
)

async function handleSelect(item) {
  await store.refreshOutlineWorkbench({
    outlineType: item.outline_type,
    outlineRef: item.outline_ref,
  })
}

async function handleSubmit(content) {
  await store.submitOutlineFeedback(content)
}
```

- [ ] **Step 4: Run backend and frontend targeted verification**

Run: `pytest tests/test_repositories/test_outline_workbench_repos.py tests/test_services/test_outline_workbench_service.py tests/test_api/test_outline_workbench_routes.py tests/test_api/test_outline_routes.py -v`

Expected: PASS

Run: `cd src/novel_dev/web && npm run test -- src/api.test.js src/stores/novel.test.js src/views/outline/outlineWorkbench.test.js src/components/outline/OutlineSidebar.test.js src/components/outline/OutlineConversation.test.js`

Expected: PASS

- [ ] **Step 5: Run frontend build**

Run: `cd src/novel_dev/web && npm run build`

Expected: build succeeds without new errors

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/web/src/views/VolumePlan.vue src/novel_dev/web/src/stores/novel.js
git commit -m "feat: integrate outline planning workbench"
```

---

## Self-Review

### Spec Coverage

- 页面名称改成 `大纲规划`
  - Covered by Task 5 and Task 6
- 左侧列表 + 右侧详情
  - Covered by Task 4 and Task 5
- 总纲与卷纲独立会话
  - Covered by Task 1, Task 2, Task 3
- 页面内对话式修改
  - Covered by Task 3, Task 4, Task 5
- 按项调用 `BrainstormAgent` / `VolumePlannerAgent`
  - Covered by Task 2 and Task 3
- 上下文优化落在后端
  - Covered by Task 2

无缺口。

### Placeholder Scan

- 未使用 `TODO`、`TBD`、`similar to`
- 每个任务都列了具体文件、测试命令和最小代码骨架

### Type Consistency

- 后端统一使用 `outline_type + outline_ref`
- 前端 selection 统一使用 `outlineType + outlineRef`
- API 提交接口统一为 `content`

---

Plan complete and saved to `docs/superpowers/plans/2026-04-21-outline-planning-workbench.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
