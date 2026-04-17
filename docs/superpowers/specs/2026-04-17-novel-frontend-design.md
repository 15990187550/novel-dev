# Novel Frontend Design

> **Goal:** Build a single-page web frontend embedded in the FastAPI service, providing model configuration, novel state/progress monitoring, setting management, world encyclopedia (characters/items/locations/timeline/foreshadowings), chapter reading, and full pipeline operation controls.

---

## 1. Architecture Overview

The frontend is a **Vue 3 (Global Build via CDN)** single-page application served directly by FastAPI using `StaticFiles`. It uses **Element Plus (via CDN)** for UI components and **Axios (via CDN)** for HTTP communication.

**Deployment pattern:**
- FastAPI mounts `src/novel_dev/web/` at `/` via `StaticFiles(html=True)`.
- All existing `/api/*` routes remain unchanged.
- SPA routing is handled by a catch-all fallback route returning `index.html` for non-API paths.

**No build step is required.** The entire frontend lives in `src/novel_dev/web/index.html` (plus optional static assets in `src/novel_dev/web/static/`).

---

## 2. File Structure

### New files

| File | Responsibility |
|------|----------------|
| `src/novel_dev/web/index.html` | Vue 3 SPA entry point (inline JS/CSS) |
| `src/novel_dev/api/config_routes.py` | New backend routes for LLM config and API key management |

### Modified files

| File | Change |
|------|--------|
| `src/novel_dev/api/main.py` or `src/novel_dev/api/__init__.py` | Mount `StaticFiles` and register `config_routes.py` |
| `src/novel_dev/api/routes.py` | Add novel list, chapter list, chapter text, entity list, timeline list, spaceline list, foreshadowing list routes |
| `src/novel_dev/db/models.py` | Add `novel_id` columns to `Entity`, `Timeline`, `Spaceline`, `Foreshadowing` |
| `src/novel_dev/repositories/entity_repo.py` | `create()` accepts `novel_id`; add `list_by_novel(novel_id)` |
| `src/novel_dev/repositories/timeline_repo.py` | Add `create_with_novel(novel_id, ...)` and `list_by_novel(novel_id)` |
| `src/novel_dev/repositories/spaceline_repo.py` | Add `create_with_novel(novel_id, ...)` and `list_by_novel(novel_id)` |
| `src/novel_dev/repositories/foreshadowing_repo.py` | Add `create_with_novel(novel_id, ...)` and `list_by_novel(novel_id)` |
| `src/novel_dev/agents/librarian.py` | Pass `novel_id` when persisting entities/timeline/spaceline/foreshadowings |
| `src/novel_dev/agents/context_agent.py` | Pass `novel_id` when creating entities/timeline/spaceline/foreshadowings |
| `pyproject.toml` | Optional: ensure no new deps needed (all frontend via CDN) |
| `migrations/` | Add Alembic migration for `novel_id` columns |

---

## 3. Frontend Layout

### 3.1 Global Sidebar (fixed 200px)

Top section:
- **Novel Selector**: `el-select` (filterable, allow-create) for choosing or typing `novel_id`, plus a "Load" button.

Menu items:
1. **Dashboard** — current phase, stats, quick actions
2. **Documents** — upload, pending approvals, approved documents
3. **World Encyclopedia**
   - Entities (characters, items, others)
   - Timeline
   - Locations (spaceline)
   - Foreshadowings
4. **Chapters** — volume/chapter list, read polished text
5. **Model Config** — LLM YAML form editing + API key management

### 3.2 Main Content Area

- **Header bar**: shows current `novel_id`, current phase (translated to Chinese), current volume/chapter.
- **View switching**: conditional rendering of 5 root view components inside `el-main`.

---

## 4. Page Specifications

### 4.1 Dashboard

**Statistics cards (top row):**
- Current phase: translated badge (e.g., "卷规划", "起草中", "审核中", "已归档")
- Current volume/chapter: `第 X 卷 · 第 Y 章`
- Archived chapters: from `archive_stats.archived_chapter_count`
- Total words: from `archive_stats.total_word_count`

**Current chapter card (middle):**
- Title, status tag, word count
- "View text" button opens a read-only drawer
- If in `reviewing/editing/fast_reviewing`, show `score_overall` and `fast_review_score`

**Action buttons (bottom, dynamically enabled):**
- `brainstorm` — enabled when `current_phase == "volume_planning"` AND no synopsis exists
- `volume_plan` — enabled when `current_phase == "volume_planning"` AND synopsis exists
- `context` — enabled when `current_phase == "context_preparation"`
- `draft` — enabled when `current_phase == "drafting"`
- `advance` — enabled when `current_phase` is `"reviewing"`, `"editing"`, or `"fast_reviewing"`
- `librarian` — enabled when `current_phase == "librarian"`
- `export` — always enabled

Each button shows loading state (`el-button :loading="true"`) during the async call and disables itself. After success, the dashboard refreshes `state` and `archive_stats`.

### 4.2 Documents

**Upload area:**
- `el-upload` with `auto-upload="false"` and `accept=".txt,.md"`.
- On file selection, `FileReader.readAsText()` extracts content, then `POST /api/novels/{novel_id}/documents/upload` is called with `{"filename": file.name, "content": text}`.

**Pending list:**
- Fetched from `GET /api/novels/{novel_id}/documents/pending`.
- Table columns: type, status, created time.
- Action: "Approve" button calls `POST /api/novels/{novel_id}/documents/pending/approve` with `pending_id`.
- After approval, both pending list and approved list refresh.

**Approved documents:**
- Fetched from `DocumentRepository.get_by_type(novel_id, doc_type)` via a new internal helper or existing routes.
- Grouped by doc_type: worldview, setting, concept, style_profile, synopsis, volume_plan.
- Each doc is a collapsible `el-card` showing title, updated time, and full content.

### 4.3 World Encyclopedia

**Entities:**
- Fetched from `GET /api/novels/{novel_id}/entities`.
- `el-tabs`: Characters / Items / Others.
- Table columns: name, current version, created chapter, latest state (first 100 chars of JSON preview).
- Click row to expand a JSON viewer showing the full `latest_state`.

**Timeline:**
- Fetched from `GET /api/novels/{novel_id}/timelines`.
- Vertical `el-timeline` component.
- Each node shows `tick`, narrative, anchor chapter/event.

**Locations:**
- Fetched from `GET /api/novels/{novel_id}/spacelines`.
- `el-table` with `row-key="id"` and `tree-props` for parent-child rendering.
- Columns: name, narrative preview. Click row to see full chain path.

**Foreshadowings:**
- Fetched from `GET /api/novels/{novel_id}/foreshadowings`.
- Table columns: content, 埋下 chapter, 回收状态 (colored tag: `pending`=warning, `recovered`=success), 回收条件.

### 4.4 Chapters

**Data source:** `GET /api/novels/{novel_id}/chapters` returns merged data from `checkpoint_data.current_volume_plan` and the `chapters` table.

**Table columns:**
- Volume number
- Chapter number
- Title
- Status tag (colored: pending=info, drafted=primary, edited=success, archived=purple custom class)
- Word count (length of `polished_text` if present, else `raw_draft`)
- Actions: "View text"

**Filters:**
- Volume select dropdown
- Status tag filters

**View text drawer:**
- Width 60%.
- Read-only `el-scrollbar` container with 16px font, 1.8 line-height.
- If `polished_text` exists, display it; otherwise display `raw_draft`.
- Top toolbar shows chapter title and word count.

### 4.5 Model Config

**Layout:** two-column `el-row`.

**Left column (LLM Config Form):**
- Global defaults collapsible panel: provider, model, base_url, timeout, retries, temperature, max_tokens.
- Agent list (BrainstormAgent, VolumePlannerAgent, WriterAgent, CriticAgent, EditorAgent, FastReviewAgent, LibrarianAgent, ContextAgent).
- Each agent is an `el-collapse-item` containing the same field set.
- Fallback is a nested collapsible inside each agent panel.
- "Save Config" button calls `POST /api/config/llm`. On success, `ElMessage.success('配置已保存')`.

**Right column (API Keys):**
- Form fields: `anthropic_api_key`, `openai_api_key`, `moonshot_api_key`, `minimax_api_key`, `zhipu_api_key`.
- All fields use plain text `<el-input>` (as requested).
- "Save Keys" button calls `POST /api/config/env`. On success, `ElMessage.success('API Key 已保存')`.

---

## 5. Backend API Additions

### 5.1 Config Routes (`src/novel_dev/api/config_routes.py`)

```python
from fastapi import APIRouter
from pydantic import BaseModel
from novel_dev.config import settings

router = APIRouter()

class LLMConfigPayload(BaseModel):
    config: dict

class EnvConfigPayload(BaseModel):
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    moonshot_api_key: str | None = None
    minimax_api_key: str | None = None
    zhipu_api_key: str | None = None

@router.get("/api/config/llm")
async def get_llm_config():
    import yaml
    with open(settings.llm_config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data

@router.post("/api/config/llm")
async def save_llm_config(payload: LLMConfigPayload):
    from novel_dev.llm.models import TaskConfig
    # Validate structure by trying to build a TaskConfig from defaults
    defaults = payload.config.get("defaults", {})
    TaskConfig(**defaults)
    import yaml
    with open(settings.llm_config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload.config, f, allow_unicode=True, sort_keys=False)
    return {"saved": True}

@router.get("/api/config/env")
async def get_env_config():
    return {
        "anthropic_api_key": settings.anthropic_api_key or "",
        "openai_api_key": settings.openai_api_key or "",
        "moonshot_api_key": settings.moonshot_api_key or "",
        "minimax_api_key": settings.minimax_api_key or "",
        "zhipu_api_key": settings.zhipu_api_key or "",
    }

@router.post("/api/config/env")
async def save_env_config(payload: EnvConfigPayload):
    from dotenv import set_key, find_dotenv
    env_path = find_dotenv() or ".env"
    for key, value in payload.model_dump().items():
        if value is not None:
            set_key(env_path, key.upper(), value)
            # Update in-memory settings immediately
            setattr(settings, key, value)
    return {"saved": True}
```

*Note: `python-dotenv` must be added to `pyproject.toml` dependencies if not already present.*

### 5.2 Novel List Route

Add to `src/novel_dev/api/routes.py`:

```python
@router.get("/api/novels")
async def list_novels(session: AsyncSession = Depends(get_session)):
    from sqlalchemy import select
    from novel_dev.db.models import NovelState
    result = await session.execute(
        select(NovelState.novel_id, NovelState.current_phase, NovelState.last_updated)
        .order_by(NovelState.last_updated.desc())
    )
    rows = result.all()
    return {
        "items": [
            {
                "novel_id": r.novel_id,
                "current_phase": r.current_phase,
                "last_updated": r.last_updated.isoformat() if r.last_updated else None,
            }
            for r in rows
        ]
    }
```

### 5.3 Chapter List Route

Add to `src/novel_dev/api/routes.py`:

```python
@router.get("/api/novels/{novel_id}/chapters")
async def list_chapters(novel_id: str, session: AsyncSession = Depends(get_session)):
    state_repo = NovelStateRepository(session)
    state = await state_repo.get_state(novel_id)
    plan_chapters = []
    if state and state.checkpoint_data:
        volume_plan = state.checkpoint_data.get("current_volume_plan", {})
        plan_chapters = volume_plan.get("chapters", [])

    ch_repo = ChapterRepository(session)
    # Collect all chapter_ids from plan
    chapter_ids = [c.get("chapter_id") for c in plan_chapters if c.get("chapter_id")]
    # Batch fetch chapters
    db_chapters = {}
    if chapter_ids:
        from sqlalchemy import select
        from novel_dev.db.models import Chapter
        result = await session.execute(select(Chapter).where(Chapter.id.in_(chapter_ids)))
        for ch in result.scalars().all():
            db_chapters[ch.id] = ch

    items = []
    for pc in plan_chapters:
        cid = pc.get("chapter_id")
        ch = db_chapters.get(cid)
        word_count = 0
        if ch:
            word_count = len(ch.polished_text or ch.raw_draft or "")
        items.append({
            "chapter_id": cid,
            "volume_id": pc.get("volume_id") or (ch.volume_id if ch else None),
            "volume_number": pc.get("volume_number", 1),
            "chapter_number": pc.get("chapter_number"),
            "title": pc.get("title"),
            "summary": pc.get("summary"),
            "status": ch.status if ch else "pending",
            "word_count": word_count,
        })
    return {"items": items}
```

### 5.4 Chapter Text Route

Add to `src/novel_dev/api/routes.py`:

```python
@router.get("/api/novels/{novel_id}/chapters/{chapter_id}/text")
async def get_chapter_text(novel_id: str, chapter_id: str, session: AsyncSession = Depends(get_session)):
    repo = ChapterRepository(session)
    ch = await repo.get_by_id(chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {
        "chapter_id": ch.id,
        "title": ch.title,
        "status": ch.status,
        "raw_draft": ch.raw_draft,
        "polished_text": ch.polished_text,
        "word_count": len(ch.polished_text or ch.raw_draft or ""),
    }
```

### 5.5 World Encyclopedia List Routes

Add to `src/novel_dev/api/routes.py`:

```python
@router.get("/api/novels/{novel_id}/entities")
async def list_entities(novel_id: str, session: AsyncSession = Depends(get_session)):
    from sqlalchemy import select
    from novel_dev.db.models import Entity
    result = await session.execute(
        select(Entity).where(Entity.novel_id == novel_id).order_by(Entity.name)
    )
    svc = EntityService(session)
    items = []
    for ent in result.scalars().all():
        state = await svc.get_latest_state(ent.id)
        items.append({
            "entity_id": ent.id,
            "type": ent.type,
            "name": ent.name,
            "current_version": ent.current_version,
            "created_at_chapter_id": ent.created_at_chapter_id,
            "latest_state": state,
        })
    return {"items": items}

@router.get("/api/novels/{novel_id}/timelines")
async def list_timelines(novel_id: str, session: AsyncSession = Depends(get_session)):
    from sqlalchemy import select
    from novel_dev.db.models import Timeline
    result = await session.execute(
        select(Timeline).where(Timeline.novel_id == novel_id).order_by(Timeline.tick)
    )
    items = [
        {
            "id": t.id,
            "tick": t.tick,
            "narrative": t.narrative,
            "anchor_chapter_id": t.anchor_chapter_id,
            "anchor_event_id": t.anchor_event_id,
        }
        for t in result.scalars().all()
    ]
    return {"items": items}

@router.get("/api/novels/{novel_id}/spacelines")
async def list_spacelines(novel_id: str, session: AsyncSession = Depends(get_session)):
    from sqlalchemy import select
    from novel_dev.db.models import Spaceline
    result = await session.execute(
        select(Spaceline).where(Spaceline.novel_id == novel_id).order_by(Spaceline.name)
    )
    items = [
        {
            "id": s.id,
            "name": s.name,
            "parent_id": s.parent_id,
            "narrative": s.narrative,
            "meta": s.meta,
        }
        for s in result.scalars().all()
    ]
    return {"items": items}

@router.get("/api/novels/{novel_id}/foreshadowings")
async def list_foreshadowings(novel_id: str, session: AsyncSession = Depends(get_session)):
    from sqlalchemy import select
    from novel_dev.db.models import Foreshadowing
    result = await session.execute(
        select(Foreshadowing).where(Foreshadowing.novel_id == novel_id).order_by(Foreshadowing.id)
    )
    items = [
        {
            "id": f.id,
            "content": f.content,
            "埋下_chapter_id": f.埋下_chapter_id,
            "埋下_time_tick": f.埋下_time_tick,
            "回收状态": f.回收状态,
            "回收条件": f.回收条件,
            "recovered_chapter_id": f.recovered_chapter_id,
        }
        for f in result.scalars().all()
    ]
    return {"items": items}
```

---

## 6. Database Schema Changes

An Alembic migration must add `novel_id` to four tables.

```python
# migration script (auto-generated and manually reviewed)
from alembic import op
import sqlalchemy as sa

revision = "..."
down_revision = "..."

def upgrade():
    op.add_column("entities", sa.Column("novel_id", sa.Text(), nullable=True))
    op.add_column("timeline", sa.Column("novel_id", sa.Text(), nullable=True))
    op.add_column("spaceline", sa.Column("novel_id", sa.Text(), nullable=True))
    op.add_column("foreshadowings", sa.Column("novel_id", sa.Text(), nullable=True))

def downgrade():
    op.drop_column("entities", "novel_id")
    op.drop_column("timeline", "novel_id")
    op.drop_column("spaceline", "novel_id")
    op.drop_column("foreshadowings", "novel_id")
```

Corresponding `db/models.py` updates:

```python
class Entity(Base):
    # ... existing fields ...
    novel_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

class Timeline(Base):
    # ... existing fields ...
    novel_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

class Spaceline(Base):
    # ... existing fields ...
    novel_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

class Foreshadowing(Base):
    # ... existing fields ...
    novel_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

Repository methods (`create` or dedicated `create_with_novel`) must accept `novel_id` and store it. Agents that write these records (`LibrarianAgent`, `ContextAgent`) must pass `novel_id` obtained from the current `NovelState`.

---

## 7. FastAPI Static Files & SPA Fallback

In the FastAPI application entry point (where `app = FastAPI()` is created):

```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")

app.mount("/static", StaticFiles(directory=os.path.join(WEB_DIR, "static")), name="static")

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # Exclude API paths
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(os.path.join(WEB_DIR, "index.html"))
```

*Note: if the project currently creates `app` inside `routes.py`, it should be moved to a dedicated `main.py` or `app.py`, or the fallback route should be registered after all API routes.*

---

## 8. Key User Flows

### 8.1 Upload Setting → Generate Outline
1. User navigates to **Documents**.
2. Clicks upload, selects `.txt`/`.md` file.
3. Frontend reads text via `FileReader`, calls `POST /api/novels/{id}/documents/upload`.
4. File appears in Pending list.
5. User clicks **Approve**.
6. Document moves to Approved list.
7. User navigates to **Dashboard**, clicks **brainstorm** button.
8. `BrainstormAgent` consumes all `worldview`/`setting`/`concept` docs and generates synopsis.

### 8.2 Write a Chapter End-to-End
1. Dashboard shows `current_phase`. User clicks the enabled action button sequentially:
   - `volume_plan` → `context` → `draft` → `advance` → `advance` → `advance` → `librarian`
2. After each call, dashboard refreshes state and updates enabled buttons.
3. User can open **Chapters** at any time to read current or archived chapter text.

### 8.3 Configure a New Model
1. User navigates to **Model Config**.
2. Edits agent-level fields (e.g., changes `WriterAgent` model to `kimi-k2.5`).
3. Clicks **Save Config** — backend validates schema and writes `llm_config.yaml`.
4. Edits API Key fields.
5. Clicks **Save Keys** — backend writes `.env` and updates in-memory `Settings`.

---

## 9. Error Handling

- **HTTP 4xx/5xx**: Axios response interceptor calls `ElMessage.error(detail)`.
- **Button loading**: All action buttons bind `:loading="loadingKey === 'brainstorm'"` and disable themselves.
- **Phase mismatch**: Buttons are automatically disabled via computed properties derived from `current_phase`.
- **Network failure**: Global Axios catch shows "网络请求失败，请检查后端服务是否运行".

---

## 10. Dependencies

### Frontend (all via CDN, no build)
- Vue 3: `https://unpkg.com/vue@3/dist/vue.global.js`
- Element Plus: `https://unpkg.com/element-plus/dist/index.full.js` + CSS
- Axios: `https://unpkg.com/axios/dist/axios.min.js`

### Backend
- `python-dotenv` (for `.env` writing in `POST /api/config/env`) — add to `pyproject.toml` if absent.

---

## 11. Testing Strategy

### Backend
- Unit tests for each new repository `list_by_novel` method.
- API tests for `/api/novels`, `/api/novels/{id}/chapters`, `/api/novels/{id}/entities`, `/api/novels/{id}/timelines`, `/api/novels/{id}/spacelines`, `/api/novels/{id}/foreshadowings`, `/api/novels/{id}/chapters/{cid}/text`.
- Config route tests: `GET/POST /api/config/llm` and `GET/POST /api/config/env` (mock filesystem/env).
- Migration smoke test: verify `novel_id` columns exist after migration.

### Frontend (manual)
- Load `http://localhost:8000/`, select a novel, verify dashboard renders.
- Upload a `.txt` setting file, approve it, verify brainstorm succeeds.
- Advance through a full chapter pipeline and verify button states update correctly.
- Open a chapter drawer and verify polished text is readable.

---
