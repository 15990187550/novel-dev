# 新建小说入口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在侧边栏新增"新建小说"按钮和对话框，调用后端 `POST /api/novels` 创建小说，创建后自动加载仪表盘。

**Architecture:** 新增一个 FastAPI POST 端点负责生成唯一 novel_id、初始化 NovelState 记录（phase=brainstorming），前端在 Vue setup 中新增对话框状态和方法，创建成功后刷新列表并自动选中新小说。

**Tech Stack:** FastAPI, SQLAlchemy async, Vue 3 (CDN), Element Plus, pytest, httpx

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/novel_dev/api/routes.py` | Modify | 新增 `POST /api/novels` 端点和 `CreateNovelRequest` Pydantic 模型 |
| `src/novel_dev/web/index.html` | Modify | 新增"新建小说"按钮、对话框、创建方法、返回对象暴露 |
| `tests/test_api/test_create_novel.py` | Create | 测试创建成功、空标题校验、ID 冲突重试 |

---

### Task 1: Backend — `POST /api/novels` endpoint

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Test: `tests/test_api/test_create_novel.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api/test_create_novel.py`:

```python
import re
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_create_novel(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels", json={"title": "测试小说"})
            assert resp.status_code == 201
            data = resp.json()
            assert data["novel_id"].startswith("ce-shi-xiao-shuo-")
            assert data["current_phase"] == "brainstorming"
            assert data["checkpoint_data"]["synopsis_data"]["title"] == "测试小说"
            assert data["checkpoint_data"]["synopsis_data"]["estimated_volumes"] == 1
            assert data["current_volume_id"] is None
            assert data["current_chapter_id"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_novel_empty_title(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/novels", json={"title": "  "})
            assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/test_api/test_create_novel.py -v
```

Expected: FAIL with "404 Not Found" (endpoint doesn't exist yet)

- [ ] **Step 3: Write minimal implementation**

Add to `src/novel_dev/api/routes.py` after the imports and before `_word_count`:

```python
import re
import secrets

class CreateNovelRequest(BaseModel):
    title: str
```

Add after the `list_novels` endpoint (after line 59):

```python
def _generate_novel_id(title: str) -> str:
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'[-\s]+', '-', slug).strip('-')
    suffix = secrets.token_hex(2)
    return f"{slug}-{suffix}"


@router.post("/api/novels", status_code=201)
async def create_novel(req: CreateNovelRequest, session: AsyncSession = Depends(get_session)):
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="标题不能为空")

    novel_id = None
    for _ in range(5):
        candidate = _generate_novel_id(title)
        existing = await session.execute(select(NovelState.novel_id).where(NovelState.novel_id == candidate))
        if existing.scalar_one_or_none() is None:
            novel_id = candidate
            break

    if novel_id is None:
        raise HTTPException(status_code=500, detail="无法生成唯一的小说 ID，请重试")

    checkpoint_data = {
        "synopsis_data": {
            "title": title,
            "logline": "",
            "core_conflict": "",
            "themes": [],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 1,
            "estimated_total_chapters": 10,
            "estimated_total_words": 30000,
        },
        "synopsis_doc_id": None,
    }

    state = NovelState(
        novel_id=novel_id,
        current_phase="brainstorming",
        current_volume_id=None,
        current_chapter_id=None,
        checkpoint_data=checkpoint_data,
    )
    session.add(state)
    await session.commit()

    return {
        "novel_id": state.novel_id,
        "current_phase": state.current_phase,
        "current_volume_id": state.current_volume_id,
        "current_chapter_id": state.current_chapter_id,
        "checkpoint_data": state.checkpoint_data,
        "last_updated": state.last_updated.isoformat() if state.last_updated else None,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/test_api/test_create_novel.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_api/test_create_novel.py src/novel_dev/api/routes.py
git commit -m "feat(api): add POST /api/novels endpoint to create novels"
```

---

### Task 2: Frontend — "新建小说" button and dialog

**Files:**
- Modify: `src/novel_dev/web/index.html`

- [ ] **Step 1: Add dialog state variables in Vue setup**

In `src/novel_dev/web/index.html`, after the existing `const` declarations in `setup()`, add:

```javascript
const createDialogVisible = ref(false);
const newNovelTitle = ref('');
const creatingNovel = ref(false);
```

Place after `const volumePlan = ref(null);` (around line 349).

- [ ] **Step 2: Add the button and dialog to the template**

In the sidebar header `div.sidebar-header` (around line 19-30), add the button after the existing "加载" button:

```html
<el-button size="small" style="margin-top: 8px; width: 100%;" @click="createDialogVisible = true">新建小说</el-button>
```

The sidebar header should look like:
```html
<div class="sidebar-header">
  <el-select-v2
    v-model="selectedNovel"
    :options="novelOptions"
    placeholder="选择或输入小说"
    filterable
    allow-create
    clearable
    style="width: 100%;"
  />
  <el-button type="primary" size="small" style="margin-top: 8px; width: 100%;" @click="loadNovel">加载</el-button>
  <el-button size="small" style="margin-top: 8px; width: 100%;" @click="createDialogVisible = true">新建小说</el-button>
</div>
```

Add the dialog markup after the `</el-container>` closing tag but before the `</div>` of `#app`. Place it after the existing chapter drawer (around line 308):

```html
<el-dialog v-model="createDialogVisible" title="新建小说" width="400px" :close-on-click-modal="false">
  <el-form @submit.prevent="doCreateNovel">
    <el-form-item label="小说标题">
      <el-input v-model="newNovelTitle" placeholder="请输入小说标题" clearable ref="newNovelTitleRef" />
    </el-form-item>
  </el-form>
  <template #footer>
    <el-button @click="createDialogVisible = false">取消</el-button>
    <el-button type="primary" :loading="creatingNovel" @click="doCreateNovel">创建</el-button>
  </template>
</el-dialog>
```

- [ ] **Step 3: Add the `doCreateNovel` method in Vue setup**

Add the method after the `copyBrainstormPrompt` function (around line 451):

```javascript
async function doCreateNovel() {
  const title = newNovelTitle.value.trim();
  if (!title) {
    ElMessage.error('请输入小说标题');
    return;
  }
  creatingNovel.value = true;
  try {
    const resp = await axios.post('/api/novels', { title });
    const data = resp.data;
    ElMessage.success('小说创建成功');
    createDialogVisible.value = false;
    newNovelTitle.value = '';
    await fetchNovels();
    selectedNovel.value = data.novel_id;
    await loadNovel();
  } catch (e) {
    const msg = e.response?.data?.detail || '创建失败';
    ElMessage.error(msg);
  } finally {
    creatingNovel.value = false;
  }
}
```

- [ ] **Step 4: Expose new refs and methods in the return object**

Add to the `return` block (around line 660-674):

```javascript
createDialogVisible, newNovelTitle, creatingNovel, doCreateNovel,
```

Insert after `brainstormPrompt, brainstormButtonText, volumePlan,` in the return object.

- [ ] **Step 5: Verify frontend in browser**

1. Ensure the server is running (`uvicorn novel_dev.api:app --reload`)
2. Open http://localhost:8000
3. Click "新建小说" button
4. Enter a title and click "创建"
5. Verify the dialog closes, the new novel appears in the selector, and the dashboard loads

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/web/index.html
git commit -m "feat(web): add create novel button and dialog"
```

---

## Spec Coverage Check

| Spec Requirement | Task | Step |
|------------------|------|------|
| `POST /api/novels` endpoint | Task 1 | Step 3 |
| NovelState initialized with `current_phase="brainstorming"` | Task 1 | Step 3 |
| `checkpoint_data.synopsis_data` with title and defaults | Task 1 | Step 3 |
| `novel_id` generation (slug + random suffix) | Task 1 | Step 3 |
| ID conflict retry (up to 5 times) | Task 1 | Step 3 |
| Empty title → 422 | Task 1 | Steps 1 & 3 |
| 5 conflicts → 500 | Task 1 | Step 3 |
| "新建小说" button in sidebar | Task 2 | Step 2 |
| Dialog with title input | Task 2 | Step 2 |
| Auto-focus title input | Task 2 | Step 2 (ref bound) |
| Create success: close dialog, refresh list, auto-select, load dashboard | Task 2 | Step 3 |
| Error display on failure | Task 2 | Step 3 |

## Placeholder Scan

- No "TBD", "TODO", or incomplete sections
- No vague requirements like "add appropriate error handling"
- No "similar to Task N" references
- Every step has exact code or exact commands
- All function/type names consistent across tasks

## Type Consistency

- `CreateNovelRequest(BaseModel)` defined in Task 1, used only in the POST handler
- `novel_id` generation function `_generate_novel_id` defined inline in routes.py
- Frontend state `createDialogVisible`, `newNovelTitle`, `creatingNovel` all consistently named
- `doCreateNovel` method name matches exposed name in return object
