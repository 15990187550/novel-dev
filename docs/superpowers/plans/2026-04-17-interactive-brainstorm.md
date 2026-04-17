# 交互式大纲脑暴 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 BrainstormAgent 改造为 "Claude Code 对话 + Web 实时预览" 的交互模式，同时将 MCP server 迁移到官方 SDK。

**Architecture:** 前端提供一键复制 prompt，用户在 Claude Code 中对话迭代大纲；Claude 通过基于官方 MCP SDK 的 stdio server 调用 tools 读写数据库；前端轮询展示 `pending_synopsis` 结构化预览。

**Tech Stack:** Python 3.9, FastAPI, SQLAlchemy, Vue 3 (Element Plus), official MCP SDK (`mcp>=1.0.0`)

---

## File Map

| File | Responsibility |
|------|----------------|
| `pyproject.toml` | 添加 `mcp` 依赖 |
| `src/novel_dev/mcp_server/__main__.py` | stdio MCP server 入口 (`python -m novel_dev.mcp_server`) |
| `src/novel_dev/mcp_server/server.py` | 基于 `FastMCP` 的 MCP server，注册所有 tools |
| `src/novel_dev/agents/director.py` | 新增 `Phase.BRAINSTORMING`，更新 `VALID_TRANSITIONS` |
| `src/novel_dev/api/routes.py` | 新增 `POST /api/novels/{novel_id}/brainstorm/start` endpoint |
| `src/novel_dev/web/index.html` | 前端脑暴按钮、prompt 复制、轮询预览面板 |
| `tests/test_mcp_server.py` | MCP tools 测试 |
| `tests/test_api/test_brainstorm_routes.py` | 新增 API 测试 |

---

### Task 1: Add MCP dependency

**Files:**
- Modify: `pyproject.toml:23`
- Test: N/A (install only)

- [ ] **Step 1: Add `mcp` to dependencies**

```toml
dependencies = [
    "sqlalchemy[asyncio]>=2.0.0",
    "alembic>=1.13.0",
    "asyncpg>=0.29.0",
    "pgvector>=0.2.0",
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    "python-dotenv>=1.0.0",
    "anthropic>=0.28.0",
    "openai>=1.30.0",
    "tenacity>=8.3.0",
    "pyyaml>=6.0",
    "mcp>=1.0.0",
]
```

- [ ] **Step 2: Install dependency locally**

Run: `pip3 install "mcp>=1.0.0"`
Expected: Installs successfully.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add official mcp sdk"
```

---

### Task 2: Create MCP stdio server entry point

**Files:**
- Create: `src/novel_dev/mcp_server/__main__.py`
- Modify: `src/novel_dev/mcp_server/server.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing test for stdio server entry**

Create `tests/test_mcp_server_stdio.py`:

```python
import pytest
from novel_dev.mcp_server.server import mcp


def test_mcp_server_is_fastmcp_instance():
    from mcp.server.fastmcp import FastMCP
    assert isinstance(mcp, FastMCP)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_server_stdio.py -v`
Expected: FAIL with `ImportError: cannot import name 'FastMCP'` or assertion error.

- [ ] **Step 3: Rewrite server.py with FastMCP and create __main__.py**

Create `src/novel_dev/mcp_server/__main__.py`:

```python
from novel_dev.mcp_server.server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

Modify `src/novel_dev/mcp_server/server.py` (replace the entire file, keeping all existing tool logic):

```python
from mcp.server.fastmcp import FastMCP
from typing import Optional

from novel_dev.db.engine import async_session_maker
from novel_dev.services.entity_service import EntityService
from novel_dev.services.extraction_service import ExtractionService
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.style_profiler import StyleProfilerAgent
from novel_dev.agents.context_agent import ContextAgent
from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.agents.director import NovelDirector
from novel_dev.agents.brainstorm_agent import BrainstormAgent
from novel_dev.agents.volume_planner import VolumePlannerAgent
from novel_dev.schemas.context import ChapterContext
from novel_dev.schemas.outline import VolumePlan
from novel_dev.services.export_service import ExportService
from novel_dev.config import Settings

mcp = FastMCP("novel-dev")


@mcp.tool()
async def query_entity(entity_id: str) -> dict:
    async with async_session_maker() as session:
        svc = EntityService(session)
        state = await svc.get_latest_state(entity_id)
        return {"entity_id": entity_id, "state": state}


@mcp.tool()
async def get_active_foreshadowings() -> list:
    async with async_session_maker() as session:
        repo = ForeshadowingRepository(session)
        items = await repo.list_active()
        return [
            {
                "id": fs.id,
                "content": fs.content,
                "回收条件": fs.回收条件,
            }
            for fs in items
        ]


@mcp.tool()
async def get_timeline() -> dict:
    async with async_session_maker() as session:
        repo = TimelineRepository(session)
        tick = await repo.get_current_tick()
        return {"current_tick": tick}


@mcp.tool()
async def get_spaceline_chain(location_id: str) -> list:
    async with async_session_maker() as session:
        repo = SpacelineRepository(session)
        chain = await repo.get_chain(location_id)
        return [{"id": node.id, "name": node.name} for node in chain]


@mcp.tool()
async def get_novel_state(novel_id: str) -> dict:
    async with async_session_maker() as session:
        repo = NovelStateRepository(session)
        state = await repo.get_state(novel_id)
        if not state:
            return {"error": "not found"}
        return {
            "novel_id": state.novel_id,
            "current_phase": state.current_phase,
            "checkpoint_data": state.checkpoint_data,
        }


@mcp.tool()
async def get_novel_documents(novel_id: str, doc_type: str) -> list:
    async with async_session_maker() as session:
        repo = DocumentRepository(session)
        docs = await repo.get_by_type(novel_id, doc_type)
        return [{"id": d.id, "title": d.title, "content": d.content[:500]} for d in docs]


@mcp.tool()
async def upload_document(novel_id: str, filename: str, content: str) -> dict:
    async with async_session_maker() as session:
        svc = ExtractionService(session)
        pe = await svc.process_upload(novel_id, filename, content)
        await session.commit()
        return {
            "id": pe.id,
            "extraction_type": pe.extraction_type,
            "status": pe.status,
            "created_at": pe.created_at.isoformat(),
        }


@mcp.tool()
async def get_pending_documents(novel_id: str) -> list:
    async with async_session_maker() as session:
        repo = PendingExtractionRepository(session)
        items = await repo.list_by_novel(novel_id)
        return [
            {
                "id": i.id,
                "extraction_type": i.extraction_type,
                "status": i.status,
                "raw_result": i.raw_result,
                "proposed_entities": i.proposed_entities,
                "created_at": i.created_at.isoformat(),
            }
            for i in items
        ]


@mcp.tool()
async def approve_pending_documents(pending_id: str) -> dict:
    async with async_session_maker() as session:
        svc = ExtractionService(session)
        docs = await svc.approve_pending(pending_id)
        await session.commit()
        return {
            "documents": [
                {
                    "id": d.id,
                    "doc_type": d.doc_type,
                    "title": d.title,
                    "content": d.content[:500],
                    "version": d.version,
                }
                for d in docs
            ]
        }


@mcp.tool()
async def list_style_profile_versions(novel_id: str) -> list:
    async with async_session_maker() as session:
        repo = DocumentRepository(session)
        docs = await repo.get_by_type(novel_id, "style_profile")
        return [
            {
                "version": d.version,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                "title": d.title,
            }
            for d in docs
        ]


@mcp.tool()
async def rollback_style_profile(novel_id: str, version: int) -> dict:
    try:
        async with async_session_maker() as session:
            svc = ExtractionService(session)
            await svc.rollback_style_profile(novel_id, version)
            await session.commit()
            return {"rolled_back_to_version": version}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def analyze_style_from_text(text: str) -> dict:
    try:
        agent = StyleProfilerAgent()
        profile = await agent.profile(text)
        return profile.model_dump()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def prepare_chapter_context(novel_id: str, chapter_id: str) -> dict:
    async with async_session_maker() as session:
        agent = ContextAgent(session)
        try:
            context = await agent.assemble(novel_id, chapter_id)
            await session.commit()
            return {
                "success": True,
                "chapter_plan_title": context.chapter_plan.title,
                "active_entities_count": len(context.active_entities),
                "pending_foreshadowings_count": len(context.pending_foreshadowings),
            }
        except ValueError as e:
            return {"success": False, "error": str(e)}


@mcp.tool()
async def generate_chapter_draft(novel_id: str, chapter_id: str) -> dict:
    async with async_session_maker() as session:
        state_repo = NovelStateRepository(session)
        state = await state_repo.get_state(novel_id)
        if not state:
            return {"error": "Novel state not found"}
        checkpoint = state.checkpoint_data or {}
        context_data = checkpoint.get("chapter_context")
        if not context_data:
            return {"error": "Chapter context not prepared"}
        context = ChapterContext.model_validate(context_data)
        agent = WriterAgent(session)
        try:
            metadata = await agent.write(novel_id, context, chapter_id)
            await session.commit()
            return metadata.model_dump()
        except Exception as e:
            return {"error": str(e)}


@mcp.tool()
async def get_chapter_draft_status(novel_id: str, chapter_id: str) -> dict:
    async with async_session_maker() as session:
        repo = ChapterRepository(session)
        ch = await repo.get_by_id(chapter_id)
        state_repo = NovelStateRepository(session)
        state = await state_repo.get_state(novel_id)
        if not state:
            return {"error": "Novel state not found"}
        checkpoint = state.checkpoint_data if state else {}
        return {
            "chapter_id": chapter_id,
            "status": ch.status if ch else None,
            "raw_draft": ch.raw_draft if ch else None,
            "drafting_progress": checkpoint.get("drafting_progress"),
            "draft_metadata": checkpoint.get("draft_metadata"),
        }


@mcp.tool()
async def advance_novel(novel_id: str) -> dict:
    async with async_session_maker() as session:
        director = NovelDirector(session)
        try:
            state = await director.advance(novel_id)
            await session.commit()
            return {
                "novel_id": state.novel_id,
                "current_phase": state.current_phase,
                "checkpoint_data": state.checkpoint_data,
            }
        except ValueError as e:
            return {"error": str(e)}
        except RuntimeError as e:
            return {"error": str(e)}


@mcp.tool()
async def get_review_result(novel_id: str) -> dict:
    async with async_session_maker() as session:
        state_repo = NovelStateRepository(session)
        state = await state_repo.get_state(novel_id)
        if not state:
            return {"error": "Novel state not found"}
        if not state.current_chapter_id:
            return {"error": "Current chapter not set"}
        repo = ChapterRepository(session)
        ch = await repo.get_by_id(state.current_chapter_id)
        if not ch:
            return {"error": "Chapter not found"}
        return {
            "score_overall": ch.score_overall,
            "score_breakdown": ch.score_breakdown,
            "review_feedback": ch.review_feedback,
        }


@mcp.tool()
async def get_fast_review_result(novel_id: str) -> dict:
    async with async_session_maker() as session:
        state_repo = NovelStateRepository(session)
        state = await state_repo.get_state(novel_id)
        if not state:
            return {"error": "Novel state not found"}
        if not state.current_chapter_id:
            return {"error": "Current chapter not set"}
        repo = ChapterRepository(session)
        ch = await repo.get_by_id(state.current_chapter_id)
        if not ch:
            return {"error": "Chapter not found"}
        return {
            "fast_review_score": ch.fast_review_score,
            "fast_review_feedback": ch.fast_review_feedback,
        }


@mcp.tool()
async def brainstorm_novel(novel_id: str) -> dict:
    async with async_session_maker() as session:
        agent = BrainstormAgent(session)
        try:
            synopsis_data = await agent.brainstorm(novel_id)
            await session.commit()
            return {
                "title": synopsis_data.title,
                "logline": synopsis_data.logline,
                "estimated_volumes": synopsis_data.estimated_volumes,
                "estimated_total_chapters": synopsis_data.estimated_total_chapters,
            }
        except ValueError as e:
            return {"error": str(e)}


@mcp.tool()
async def plan_volume(novel_id: str, volume_number: Optional[int] = None) -> dict:
    async with async_session_maker() as session:
        agent = VolumePlannerAgent(session)
        try:
            plan = await agent.plan(novel_id, volume_number)
            await session.commit()
            return {
                "volume_id": plan.volume_id,
                "volume_number": plan.volume_number,
                "title": plan.title,
                "total_chapters": plan.total_chapters,
                "chapters": [
                    {
                        "chapter_id": ch.chapter_id,
                        "chapter_number": ch.chapter_number,
                        "title": ch.title,
                        "summary": ch.summary,
                    }
                    for ch in plan.chapters
                ],
            }
        except ValueError as e:
            return {"error": str(e)}


@mcp.tool()
async def get_synopsis(novel_id: str) -> dict:
    try:
        async with async_session_maker() as session:
            repo = DocumentRepository(session)
            state_repo = NovelStateRepository(session)
            docs = await repo.get_by_type(novel_id, "synopsis")
            if not docs:
                return {"error": "Synopsis not found"}
            state = await state_repo.get_state(novel_id)
            synopsis_data = {}
            if state and state.checkpoint_data:
                synopsis_data = state.checkpoint_data.get("synopsis_data", {})
            return {
                "content": docs[0].content,
                "synopsis_data": synopsis_data,
            }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def get_volume_plan(novel_id: str) -> dict:
    try:
        async with async_session_maker() as session:
            state_repo = NovelStateRepository(session)
            state = await state_repo.get_state(novel_id)
            if not state or not state.checkpoint_data.get("current_volume_plan"):
                return {"error": "Volume plan not found"}
            plan = VolumePlan.model_validate(state.checkpoint_data["current_volume_plan"])
            return {
                "volume_id": plan.volume_id,
                "volume_number": plan.volume_number,
                "title": plan.title,
                "total_chapters": plan.total_chapters,
                "chapters": [
                    {
                        "chapter_id": ch.chapter_id,
                        "chapter_number": ch.chapter_number,
                        "title": ch.title,
                        "summary": ch.summary,
                    }
                    for ch in plan.chapters
                ],
            }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def run_librarian(novel_id: str) -> dict:
    async with async_session_maker() as session:
        director = NovelDirector(session)
        try:
            state = await director.run_librarian(novel_id)
            await session.commit()
            return {
                "novel_id": state.novel_id,
                "current_phase": state.current_phase,
                "checkpoint_data": state.checkpoint_data,
            }
        except ValueError as e:
            return {"error": str(e)}
        except RuntimeError as e:
            return {"error": str(e)}


@mcp.tool()
async def export_novel(novel_id: str, format: str = "md") -> dict:
    settings = Settings()
    async with async_session_maker() as session:
        svc = ExportService(session, settings.markdown_output_dir)
        try:
            path = await svc.export_novel(novel_id, format=format)
            return {"exported_path": path, "format": format}
        except ValueError as e:
            return {"error": str(e)}


@mcp.tool()
async def get_archive_stats(novel_id: str) -> dict:
    async with async_session_maker() as session:
        repo = NovelStateRepository(session)
        state = await repo.get_state(novel_id)
        if not state:
            return {"error": "Novel state not found"}
        stats = state.checkpoint_data.get("archive_stats", {})
        return {
            "total_word_count": stats.get("total_word_count", 0),
            "archived_chapter_count": stats.get("archived_chapter_count", 0),
            "avg_word_count": stats.get("avg_word_count", 0),
        }
```

- [ ] **Step 4: Update existing tests to use `mcp._tools` instead of `mcp.tools`**

Modify `tests/test_mcp_server.py:7`:

```python
def test_mcp_server_has_tools():
    expected = {
        "query_entity",
        "get_active_foreshadowings",
        "get_timeline",
        "get_spaceline_chain",
        "get_novel_state",
        "get_novel_documents",
        "upload_document",
        "get_pending_documents",
        "approve_pending_documents",
        "list_style_profile_versions",
        "rollback_style_profile",
        "analyze_style_from_text",
        "prepare_chapter_context",
        "generate_chapter_draft",
        "get_chapter_draft_status",
        "advance_novel",
        "get_review_result",
        "get_fast_review_result",
        "brainstorm_novel",
        "plan_volume",
        "get_synopsis",
        "get_volume_plan",
        "run_librarian",
        "export_novel",
        "get_archive_stats",
    }
    assert set(mcp._tools.keys()) == expected
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_mcp_server.py::test_mcp_server_has_tools tests/test_mcp_server_stdio.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/mcp_server/__main__.py src/novel_dev/mcp_server/server.py tests/test_mcp_server.py tests/test_mcp_server_stdio.py
git commit -m "feat(mcp): migrate NovelDevMCPServer to official FastMCP SDK"
```

---

### Task 3: Add BRAINSTORMING phase and state transitions

**Files:**
- Modify: `src/novel_dev/agents/director.py:10-30`
- Test: `tests/test_agents/test_director.py` (or create if missing)

- [ ] **Step 1: Write failing test for new phase**

Create `tests/test_agents/test_director.py` if it doesn't exist:

```python
from novel_dev.agents.director import Phase, VALID_TRANSITIONS


def test_brainstorming_phase_exists():
    assert Phase.BRAINSTORMING.value == "brainstorming"


def test_valid_transitions_include_brainstorming():
    assert Phase.VOLUME_PLANNING in VALID_TRANSITIONS
    assert Phase.BRAINSTORMING in VALID_TRANSITIONS[Phase.VOLUME_PLANNING]
    assert Phase.VOLUME_PLANNING in VALID_TRANSITIONS[Phase.BRAINSTORMING]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agents/test_director.py -v`
Expected: FAIL with `AttributeError: BRAINSTORMING` or assertion error.

- [ ] **Step 3: Add BRAINSTORMING phase**

Modify `src/novel_dev/agents/director.py`:

```python
class Phase(str, Enum):
    BRAINSTORMING = "brainstorming"
    VOLUME_PLANNING = "volume_planning"
    CONTEXT_PREPARATION = "context_preparation"
    DRAFTING = "drafting"
    REVIEWING = "reviewing"
    EDITING = "editing"
    FAST_REVIEWING = "fast_reviewing"
    LIBRARIAN = "librarian"
    COMPLETED = "completed"


VALID_TRANSITIONS = {
    Phase.BRAINSTORMING: [Phase.VOLUME_PLANNING],
    Phase.VOLUME_PLANNING: [Phase.BRAINSTORMING, Phase.CONTEXT_PREPARATION],
    Phase.CONTEXT_PREPARATION: [Phase.DRAFTING],
    Phase.DRAFTING: [Phase.REVIEWING],
    Phase.REVIEWING: [Phase.EDITING, Phase.DRAFTING],
    Phase.EDITING: [Phase.FAST_REVIEWING],
    Phase.FAST_REVIEWING: [Phase.LIBRARIAN, Phase.DRAFTING, Phase.EDITING],
    Phase.LIBRARIAN: [Phase.COMPLETED],
    Phase.COMPLETED: [Phase.CONTEXT_PREPARATION, Phase.VOLUME_PLANNING],
}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_agents/test_director.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/director.py tests/test_agents/test_director.py
git commit -m "feat(director): add BRAINSTORMING phase and transitions"
```

---

### Task 4: Add brainstorm start API

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Create: `tests/test_api/test_brainstorm_routes.py`

- [ ] **Step 1: Write failing test for start endpoint**

Create `tests/test_api/test_brainstorm_routes.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from novel_dev.api.routes import router, get_session
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.agents.director import NovelDirector, Phase

app = FastAPI()
app.include_router(router)


@pytest.fixture
def test_client(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_brainstorm_start_success(async_session, test_client):
    await DocumentRepository(async_session).create(
        "d1", "n_brain", "worldview", "WV", "天玄大陆"
    )
    await async_session.commit()

    async with test_client as client:
        resp = await client.post("/api/novels/n_brain/brainstorm/start")
        assert resp.status_code == 200
        data = resp.json()
        assert "prompt" in data
        assert "n_brain" in data["prompt"]

        state = await NovelDirector(session=async_session).resume("n_brain")
        assert state.current_phase == Phase.BRAINSTORMING.value


@pytest.mark.asyncio
async def test_brainstorm_start_no_documents(async_session, test_client):
    async with test_client as client:
        resp = await client.post("/api/novels/n_empty/brainstorm/start")
        assert resp.status_code == 400
        assert "文档" in resp.json()["detail"] or "document" in resp.json()["detail"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_brainstorm_routes.py -v`
Expected: FAIL with 404 or `AttributeError` because endpoint doesn't exist.

- [ ] **Step 3: Implement start endpoint**

Modify `src/novel_dev/api/routes.py`, add after the existing `/brainstorm` endpoint (around line 475):

```python
@router.post("/api/novels/{novel_id}/brainstorm/start")
async def start_brainstorm(novel_id: str, session: AsyncSession = Depends(get_session)):
    doc_repo = DocumentRepository(session)
    docs = (
        await doc_repo.get_by_type(novel_id, "worldview")
        + await doc_repo.get_by_type(novel_id, "setting")
        + await doc_repo.get_by_type(novel_id, "concept")
    )
    if not docs:
        raise HTTPException(status_code=400, detail="请先上传世界观或设定文档")

    director = NovelDirector(session)
    state = await director.resume(novel_id)
    checkpoint = dict(state.checkpoint_data or {}) if state else {}
    await director.save_checkpoint(
        novel_id,
        phase=Phase.BRAINSTORMING,
        checkpoint_data=checkpoint,
        volume_id=state.current_volume_id if state else None,
        chapter_id=state.current_chapter_id if state else None,
    )

    doc_list = "\n".join(f"- [{d.doc_type}] {d.title} (doc_id={d.id})" for d in docs)
    prompt = (
        f'请为小说 "{novel_id}" 脑暴一份大纲。\n\n'
        f"已上传的设定文档列表如下，你可以调用 get_novel_document_full 获取完整内容：\n"
        f"{doc_list}\n\n"
        f"请基于这些文档生成大纲。每次修改后请调用 save_brainstorm_draft 保存。\n"
        f'当我确认满意后，调用 confirm_brainstorm 完成脑暴。'
    )
    return {"prompt": prompt}
```

Also add `Phase` to the import list in `src/novel_dev/api/routes.py`:

```python
from novel_dev.agents.director import NovelDirector, Phase
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api/test_brainstorm_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_brainstorm_routes.py
git commit -m "feat(api): add POST /brainstorm/start endpoint"
```

---

### Task 5: Add new MCP tools for brainstorm interaction

**Files:**
- Modify: `src/novel_dev/mcp_server/server.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing tests for new tools**

Append to `tests/test_mcp_server.py`:

```python
@pytest.mark.asyncio
async def test_mcp_get_novel_document_full():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_doc_full_{suffix}"
    content = "a" * 2000

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        doc = await DocumentRepository(session).create(
            f"d_{suffix}", novel_id, "worldview", "WV", content
        )
        await session.commit()

    result = await mcp._tools["get_novel_document_full"](novel_id=novel_id, doc_id=doc.id)
    assert result["content"] == content
    assert result["doc_type"] == "worldview"


@pytest.mark.asyncio
async def test_mcp_save_brainstorm_draft():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.outline import SynopsisData

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_draft_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        await director.save_checkpoint(
            novel_id,
            phase=Phase.BRAINSTORMING,
            checkpoint_data={},
            volume_id=None,
            chapter_id=None,
        )
        await session.commit()

    synopsis = SynopsisData(
        title="T",
        logline="L",
        core_conflict="C",
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=3000,
    )
    result = await mcp._tools["save_brainstorm_draft"](
        novel_id=novel_id, synopsis_data=synopsis.model_dump()
    )
    assert result["saved"] is True

    async with async_session_local() as session:
        director = NovelDirector(session=session)
        state = await director.resume(novel_id)
        assert state.checkpoint_data["pending_synopsis"]["title"] == "T"


@pytest.mark.asyncio
async def test_mcp_confirm_brainstorm():
    from novel_dev.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from novel_dev.agents.director import NovelDirector, Phase
    from novel_dev.schemas.outline import SynopsisData
    from novel_dev.repositories.document_repo import DocumentRepository

    suffix = uuid.uuid4().hex[:8]
    novel_id = f"n_confirm_{suffix}"

    async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_local() as session:
        director = NovelDirector(session=session)
        await director.save_checkpoint(
            novel_id,
            phase=Phase.BRAINSTORMING,
            checkpoint_data={},
            volume_id=None,
            chapter_id=None,
        )
        await session.commit()

    synopsis = SynopsisData(
        title="T2",
        logline="L2",
        core_conflict="C2",
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=3000,
    )
    await mcp._tools["save_brainstorm_draft"](
        novel_id=novel_id, synopsis_data=synopsis.model_dump()
    )

    result = await mcp._tools["confirm_brainstorm"](novel_id=novel_id)
    assert result["confirmed"] is True

    async with async_session_local() as session:
        director = NovelDirector(session=session)
        state = await director.resume(novel_id)
        assert state.current_phase == Phase.VOLUME_PLANNING.value
        assert "pending_synopsis" not in state.checkpoint_data
        docs = await DocumentRepository(session).get_by_type(novel_id, "synopsis")
        assert any(d.title == "T2" for d in docs)
```

Also update the `expected` set in `test_mcp_server_has_tools` to include the 3 new tools:

```python
"get_novel_document_full",
"save_brainstorm_draft",
"confirm_brainstorm",
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py::test_mcp_get_novel_document_full tests/test_mcp_server.py::test_mcp_save_brainstorm_draft tests/test_mcp_server.py::test_mcp_confirm_brainstorm -v`
Expected: FAIL with `KeyError` because tools don't exist yet.

- [ ] **Step 3: Implement the 3 new MCP tools**

Append to `src/novel_dev/mcp_server/server.py` before the final blank line:

```python
@mcp.tool()
async def get_novel_document_full(novel_id: str, doc_id: str) -> dict:
    async with async_session_maker() as session:
        repo = DocumentRepository(session)
        docs = await repo.get_by_type(novel_id, "")
        # get_by_type doesn't support empty string well; use direct query
        from sqlalchemy import select
        from novel_dev.db.models import NovelDocument
        result = await session.execute(
            select(NovelDocument).where(NovelDocument.novel_id == novel_id, NovelDocument.id == doc_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            return {"error": "Document not found"}
        return {
            "id": doc.id,
            "title": doc.title,
            "content": doc.content,
            "doc_type": doc.doc_type,
        }


@mcp.tool()
async def save_brainstorm_draft(novel_id: str, synopsis_data: dict) -> dict:
    from novel_dev.schemas.outline import SynopsisData
    async with async_session_maker() as session:
        state_repo = NovelStateRepository(session)
        state = await state_repo.get_state(novel_id)
        if not state or state.current_phase != Phase.BRAINSTORMING.value:
            return {"error": "Novel is not in brainstorming phase"}
        synopsis = SynopsisData.model_validate(synopsis_data)
        checkpoint = dict(state.checkpoint_data or {})
        checkpoint["pending_synopsis"] = synopsis.model_dump()
        director = NovelDirector(session)
        await director.save_checkpoint(
            novel_id,
            phase=Phase.BRAINSTORMING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )
        await session.commit()
        return {"saved": True}


@mcp.tool()
async def confirm_brainstorm(novel_id: str) -> dict:
    import uuid as uuid_mod
    from novel_dev.schemas.outline import SynopsisData
    async with async_session_maker() as session:
        state_repo = NovelStateRepository(session)
        state = await state_repo.get_state(novel_id)
        if not state or state.current_phase != Phase.BRAINSTORMING.value:
            return {"error": "Novel is not in brainstorming phase"}
        checkpoint = dict(state.checkpoint_data or {})
        pending = checkpoint.get("pending_synopsis")
        if not pending:
            return {"error": "No pending synopsis found"}
        synopsis = SynopsisData.model_validate(pending)
        agent = BrainstormAgent(session)
        synopsis_text = agent._format_synopsis_text(synopsis, "")
        doc_repo = DocumentRepository(session)
        await doc_repo.create(
            doc_id=f"doc_{uuid_mod.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type="synopsis",
            title=synopsis.title,
            content=synopsis_text,
        )
        checkpoint["synopsis_data"] = synopsis.model_dump()
        checkpoint.pop("pending_synopsis", None)
        director = NovelDirector(session)
        await director.save_checkpoint(
            novel_id,
            phase=Phase.VOLUME_PLANNING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )
        await session.commit()
        return {"confirmed": True}
```

Note: We need to import `Phase` in `server.py`. Add to existing imports:

```python
from novel_dev.agents.director import NovelDirector, Phase
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/mcp_server/server.py tests/test_mcp_server.py
git commit -m "feat(mcp): add brainstorm interaction tools"
```

---

### Task 6: Update frontend for brainstorm interaction

**Files:**
- Modify: `src/novel_dev/web/index.html`
- Test: Manual browser verification

- [ ] **Step 1: Modify Vue template for brainstorm button and prompt display**

In `src/novel_dev/web/index.html`, locate the operations card (around line 82-91). Replace it with:

```html
<el-card style="margin-top: 16px;">
  <template #header><span>操作</span></template>
  <div v-if="novelState.current_phase === 'brainstorming'" style="margin-bottom: 12px;">
    <el-alert type="info" :closable="false">
      <div>请在 Claude Code 中粘贴以下 prompt 继续脑暴：</div>
      <pre style="margin-top: 8px; white-space: pre-wrap; background: #f5f7fa; padding: 8px; border-radius: 4px;">{{ brainstormPrompt }}</pre>
      <el-button size="small" style="margin-top: 8px;" @click="copyBrainstormPrompt">复制 prompt</el-button>
    </el-alert>
  </div>
  <el-button type="primary" :loading="loadingAction === 'brainstorm'" :disabled="!canBrainstorm" @click="doAction('brainstorm')">{{ brainstormButtonText }}</el-button>
  <el-button type="primary" :loading="loadingAction === 'volume_plan'" :disabled="!canVolumePlan" @click="doAction('volume_plan')">卷规划</el-button>
  <el-button type="primary" :loading="loadingAction === 'context'" :disabled="!canContext" @click="doAction('context')">准备上下文</el-button>
  <el-button type="primary" :loading="loadingAction === 'draft'" :disabled="!canDraft" @click="doAction('draft')">生成草稿</el-button>
  <el-button type="primary" :loading="loadingAction === 'advance'" :disabled="!canAdvance" @click="doAction('advance')">推进</el-button>
  <el-button type="primary" :loading="loadingAction === 'librarian'" :disabled="!canLibrarian" @click="doAction('librarian')">归档</el-button>
  <el-button :loading="loadingAction === 'export'" @click="doAction('export')">导出小说</el-button>
</el-card>
```

- [ ] **Step 2: Add Vue state and computed properties for brainstorm**

In the `<script>` setup section, add:

```javascript
const brainstormPrompt = ref('');
const brainstormButtonText = computed(() => {
  return novelState.value.current_phase === 'brainstorming' ? '脑暴中...' : '生成大纲';
});
```

Update `canBrainstorm` to allow starting from `brainstorming` as well (though button will be visually disabled when in brainstorming):

```javascript
const canBrainstorm = computed(() => ['volume_planning', 'brainstorming'].includes(novelState.value.current_phase));
```

Actually keep it simple — the button text changes but we want it clickable only when not brainstorming:

```javascript
const canBrainstorm = computed(() => novelState.value.current_phase === 'volume_planning');
```

Add copy method:

```javascript
async function copyBrainstormPrompt() {
  try {
    await navigator.clipboard.writeText(brainstormPrompt.value);
    ElMessage.success('已复制到剪贴板');
  } catch (e) {
    ElMessage.error('复制失败');
  }
}
```

- [ ] **Step 3: Modify doAction for brainstorm to call start endpoint**

In `doAction`, update the brainstorm branch:

```javascript
if (action === 'brainstorm') {
  url = `/api/novels/${novelId.value}/brainstorm/start`;
  const resp = await axios.post(url);
  brainstormPrompt.value = resp.data.prompt;
  ElMessage.success('已生成脑暴 prompt，请复制到 Claude Code');
  await refreshDashboard();
  loadingAction.value = '';
  return;
}
```

- [ ] **Step 4: Add brainstorm preview panel with polling**

Add a new computed and polling logic. After `filteredEntities` or similar, add:

```javascript
const pendingSynopsis = computed(() => novelState.value.checkpoint_data?.pending_synopsis);
let brainstormPollInterval = null;

function startBrainstormPolling() {
  if (brainstormPollInterval) return;
  brainstormPollInterval = setInterval(async () => {
    if (novelState.value.current_phase !== 'brainstorming') {
      stopBrainstormPolling();
      return;
    }
    await refreshDashboard();
  }, 3000);
}

function stopBrainstormPolling() {
  if (brainstormPollInterval) {
    clearInterval(brainstormPollInterval);
    brainstormPollInterval = null;
  }
}
```

Watch for phase change to start/stop polling:

```javascript
watch(() => novelState.value.current_phase, (phase) => {
  if (phase === 'brainstorming') {
    startBrainstormPolling();
  } else {
    stopBrainstormPolling();
  }
});
```

Add the preview panel HTML in the documents section (around line 116-126), inside the approved docs card or as a separate card:

```html
<el-card v-if="pendingSynopsis" style="margin-top: 16px;">
  <template #header><span>脑暴预览</span></template>
  <div style="margin-bottom: 8px;"><strong>标题：</strong>{{ pendingSynopsis.title }}</div>
  <div style="margin-bottom: 8px;"><strong>梗概：</strong>{{ pendingSynopsis.logline }}</div>
  <div style="margin-bottom: 8px;"><strong>核心冲突：</strong>{{ pendingSynopsis.core_conflict }}</div>
  <div style="margin-bottom: 8px;"><strong>预计卷数/章数/字数：</strong>{{ pendingSynopsis.estimated_volumes }} / {{ pendingSynopsis.estimated_total_chapters }} / {{ pendingSynopsis.estimated_total_words }}</div>
  <el-collapse style="margin-top: 8px;">
    <el-collapse-item title="人物弧光" name="arcs">
      <div v-for="(arc, idx) in pendingSynopsis.character_arcs" :key="idx" style="margin-bottom: 8px;">
        <div><strong>{{ arc.name }}</strong>：{{ arc.arc_summary }}</div>
        <ul><li v-for="(tp, tidx) in arc.key_turning_points" :key="tidx">{{ tp }}</li></ul>
      </div>
    </el-collapse-item>
    <el-collapse-item title="剧情里程碑" name="milestones">
      <div v-for="(ms, idx) in pendingSynopsis.milestones" :key="idx" style="margin-bottom: 8px;">
        <div><strong>{{ ms.act }}</strong>：{{ ms.summary }}</div>
        <div v-if="ms.climax_event">高潮：{{ ms.climax_event }}</div>
      </div>
    </el-collapse-item>
  </el-collapse>
</el-card>
```

- [ ] **Step 5: Update phaseMap to include brainstorming label**

```javascript
const phaseMap = {
  brainstorming: '脑暴中',
  volume_planning: '卷规划',
  context_preparation: '上下文准备',
  drafting: '起草中',
  reviewing: '审核中',
  editing: '编辑中',
  fast_reviewing: '速审中',
  librarian: '归档中',
  completed: '已完成',
};
```

- [ ] **Step 6: Manual verification**

Start the dev server: `uvicorn novel_dev.main:app --reload`
Open browser at `http://localhost:8000`

Verify:
1. Create/select a novel, upload a worldview doc.
2. Click "生成大纲" — should show alert with prompt and copy button.
3. State should change to "脑暴中".
4. Stop server.

- [ ] **Step 7: Commit**

```bash
git add src/novel_dev/web/index.html
git commit -m "feat(web): add brainstorm prompt copy and pending synopsis preview"
```

---

### Task 7: Run full test suite

- [ ] **Step 1: Run all tests**

Run: `python3 -m pytest tests/ --tb=short`
Expected: All tests pass.

- [ ] **Step 2: Fix any regressions**

If failures, fix inline.

- [ ] **Step 3: Final commit**

```bash
git commit -m "test: verify full suite passes after brainstorm interaction feature"
```

---

## Spec Coverage Check

| Spec Section | Covered By |
|--------------|-----------|
| 3.1 API: `/brainstorm/start` | Task 4 |
| 3.2 MCP: `get_novel_document_full` | Task 5 |
| 3.2 MCP: `save_brainstorm_draft` | Task 5 |
| 3.2 MCP: `confirm_brainstorm` | Task 5 |
| 3.3 Phase: `BRAINSTORMING` | Task 3 |
| 3.4 Frontend: button + prompt copy | Task 6 |
| 3.4 Frontend: polling preview panel | Task 6 |
| 5. Error handling (MCP state checks) | Task 5 |
| 6. Tests | All tasks |
| 7. MCP SDK migration | Task 2 |

## Placeholder Scan

- No TBD/TODO/fill-in-details found.
- All code snippets are complete.
- All file paths are exact.
- All test commands have expected outputs.

## Type Consistency Check

- `Phase.BRAINSTORMING` used consistently.
- `pending_synopsis` key used consistently across API, MCP tools, and frontend.
- `SynopsisData.model_dump()` / `model_validate()` patterns match existing codebase.
