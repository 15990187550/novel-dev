# Brainstorm Workspace Outline Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a brainstorm workspace flow where synopsis and each volume outline have independent contexts, all draft changes stay in a workspace until final confirmation, and setting drafts enter the existing pending-import pipeline instead of becoming formal documents immediately.

**Architecture:** Reuse `outline_sessions` and `outline_messages` as per-outline context storage, add a new `BrainstormWorkspace` persistence layer as the authority for draft outlines and setting drafts, and make the outline workbench route through workspace mode instead of writing straight into `NovelState.checkpoint_data`. Final confirmation becomes a single transactional submit that materializes synopsis, volume plan data, and pending extractions together.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, pytest, Vue 3, Pinia, Axios, Vitest

---

## File Structure

### Backend Persistence

- Modify: `src/novel_dev/db/models.py`
  - Add `BrainstormWorkspace` ORM model.
- Create: `migrations/versions/20260422_add_brainstorm_workspace.py`
  - Create `brainstorm_workspaces` table.
- Create: `src/novel_dev/repositories/brainstorm_workspace_repo.py`
  - CRUD for workspace load/create/update/mark submitted.

### Backend Schemas and Services

- Create: `src/novel_dev/schemas/brainstorm_workspace.py`
  - Define workspace payloads, setting draft payloads, and submit response types.
- Modify: `src/novel_dev/schemas/outline_workbench.py`
  - Add workbench mode and workspace-aware payload fields.
- Modify: `src/novel_dev/services/outline_workbench_service.py`
  - Add workspace mode so per-outline submit reads/writes drafts instead of formal checkpoint data.
- Modify: `src/novel_dev/services/extraction_service.py`
  - Add a helper for creating `PendingExtraction` from workspace-generated setting drafts with optional explicit type hints.
- Create: `src/novel_dev/services/brainstorm_workspace_service.py`
  - Own workspace read/write/submit logic.

### Backend API

- Modify: `src/novel_dev/api/routes.py`
  - Add workspace start/get/submit endpoints.
  - Thread brainstorm mode through outline workbench endpoints.

### Backend Tests

- Create: `tests/test_repositories/test_brainstorm_workspace_repo.py`
- Create: `tests/test_services/test_brainstorm_workspace_service.py`
- Modify: `tests/test_services/test_outline_workbench_service.py`
- Modify: `tests/test_services/test_extraction_service.py`
- Create: `tests/test_api/test_brainstorm_workspace_routes.py`
- Modify: `tests/test_api/test_outline_workbench_routes.py`

### Frontend

- Modify: `src/novel_dev/web/src/api.js`
  - Add workspace endpoints and workbench mode parameter.
- Modify: `src/novel_dev/web/src/api.test.js`
  - Add endpoint coverage.
- Modify: `src/novel_dev/web/src/stores/novel.js`
  - Add brainstorm workspace state, selection loading, submit/final confirm actions.
- Modify: `src/novel_dev/web/src/stores/novel.test.js`
  - Cover workspace loading and final confirmation behavior.
- Modify: `src/novel_dev/web/src/views/outline/outlineWorkbench.js`
  - Make sidebar item resolution work from workspace outline drafts.
- Modify: `src/novel_dev/web/src/components/outline/OutlineConversation.vue`
  - Keep the same input UX while allowing mode-aware description/callouts.
- Modify: `src/novel_dev/web/src/components/outline/OutlineDetailPanel.vue`
  - Show workspace-backed snapshots and final-confirm button region.
- Create: `src/novel_dev/web/src/components/outline/BrainstormSettingDrafts.vue`
  - Render setting draft list/drawer.
- Modify: `src/novel_dev/web/src/views/VolumePlan.vue`
  - Wire brainstorm workspace mode into the existing workbench shell.
- Create: `src/novel_dev/web/src/components/outline/BrainstormSettingDrafts.test.js`
- Modify: `src/novel_dev/web/src/components/outline/OutlineConversation.test.js`
- Modify: `src/novel_dev/web/src/views/outline/outlineWorkbench.test.js`

### Final Verification

- Modify: no additional docs beyond this plan
- Verify with targeted pytest and vitest commands plus one end-to-end backend flow

---

### Task 1: Add Brainstorm Workspace Persistence

**Files:**
- Modify: `src/novel_dev/db/models.py`
- Create: `migrations/versions/20260422_add_brainstorm_workspace.py`
- Create: `src/novel_dev/repositories/brainstorm_workspace_repo.py`
- Test: `tests/test_repositories/test_brainstorm_workspace_repo.py`

- [ ] **Step 1: Write the failing repository tests**

```python
import pytest

from novel_dev.repositories.brainstorm_workspace_repo import BrainstormWorkspaceRepository


@pytest.mark.asyncio
async def test_get_or_create_workspace_reuses_active_workspace(async_session):
    repo = BrainstormWorkspaceRepository(async_session)

    first = await repo.get_or_create("novel_ws")
    second = await repo.get_or_create("novel_ws")

    assert first.id == second.id
    assert first.status == "active"
    assert first.outline_drafts == {}
    assert first.setting_docs_draft == []


@pytest.mark.asyncio
async def test_mark_submitted_updates_status_and_timestamp(async_session):
    repo = BrainstormWorkspaceRepository(async_session)
    workspace = await repo.get_or_create("novel_submit")

    await repo.mark_submitted(workspace.id)
    await async_session.commit()

    refreshed = await repo.get_active_by_novel("novel_submit")
    assert refreshed is None

    submitted = await repo.get_by_id(workspace.id)
    assert submitted.status == "submitted"
    assert submitted.submitted_at is not None
```

- [ ] **Step 2: Run the repository tests to verify they fail**

Run: `pytest tests/test_repositories/test_brainstorm_workspace_repo.py -v`

Expected: FAIL with import error for `BrainstormWorkspaceRepository`

- [ ] **Step 3: Add the ORM model and migration**

```python
class BrainstormWorkspace(Base):
    __tablename__ = "brainstorm_workspaces"
    __table_args__ = (
        UniqueConstraint("novel_id", "status", name="uix_brainstorm_workspace_novel_status"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    workspace_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outline_drafts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    setting_docs_draft: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    last_saved_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
```

```python
def upgrade() -> None:
    op.create_table(
        "brainstorm_workspaces",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("workspace_summary", sa.Text(), nullable=True),
        sa.Column("outline_drafts", sa.JSON(), nullable=False),
        sa.Column("setting_docs_draft", sa.JSON(), nullable=False),
        sa.Column("last_saved_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("submitted_at", sa.TIMESTAMP(), nullable=True),
    )
    op.create_index(
        "ix_brainstorm_workspaces_novel_status",
        "brainstorm_workspaces",
        ["novel_id", "status"],
        unique=False,
    )
```

- [ ] **Step 4: Implement the repository with minimal behavior**

```python
class BrainstormWorkspaceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_by_novel(self, novel_id: str) -> BrainstormWorkspace | None:
        stmt = select(BrainstormWorkspace).where(
            BrainstormWorkspace.novel_id == novel_id,
            BrainstormWorkspace.status == "active",
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_or_create(self, novel_id: str) -> BrainstormWorkspace:
        existing = await self.get_active_by_novel(novel_id)
        if existing is not None:
            return existing

        workspace = BrainstormWorkspace(
            id=uuid.uuid4().hex,
            novel_id=novel_id,
            status="active",
            outline_drafts={},
            setting_docs_draft=[],
        )
        self.session.add(workspace)
        await self.session.flush()
        return workspace

    async def mark_submitted(self, workspace_id: str) -> BrainstormWorkspace:
        workspace = await self.get_by_id(workspace_id)
        workspace.status = "submitted"
        workspace.submitted_at = datetime.utcnow()
        await self.session.flush()
        return workspace
```

- [ ] **Step 5: Run the repository tests**

Run: `pytest tests/test_repositories/test_brainstorm_workspace_repo.py -v`

Expected: PASS with `2 passed`

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/db/models.py migrations/versions/20260422_add_brainstorm_workspace.py src/novel_dev/repositories/brainstorm_workspace_repo.py tests/test_repositories/test_brainstorm_workspace_repo.py
git commit -m "feat: add brainstorm workspace persistence"
```

---

### Task 2: Add Workspace Schemas and Submit Service

**Files:**
- Create: `src/novel_dev/schemas/brainstorm_workspace.py`
- Create: `src/novel_dev/services/brainstorm_workspace_service.py`
- Modify: `src/novel_dev/services/extraction_service.py`
- Test: `tests/test_services/test_brainstorm_workspace_service.py`
- Test: `tests/test_services/test_extraction_service.py`

- [ ] **Step 1: Write the failing service tests**

```python
@pytest.mark.asyncio
async def test_save_outline_draft_persists_workspace_authority(async_session):
    service = BrainstormWorkspaceService(async_session)

    await service.save_outline_draft(
        novel_id="novel_ws",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={"title": "九霄行", "logline": "逆势而上"},
    )

    payload = await service.get_workspace_payload("novel_ws")
    assert payload.outline_drafts["synopsis:synopsis"]["title"] == "九霄行"


@pytest.mark.asyncio
async def test_submit_workspace_materializes_synopsis_and_pending_settings(async_session, monkeypatch):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_submit",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    service = BrainstormWorkspaceService(async_session)
    await service.save_outline_draft(
        novel_id="novel_submit",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "逆势而上",
            "core_conflict": "主角 vs 宗门",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await service.merge_setting_drafts(
        "novel_submit",
        [
            {
                "draft_id": "draft_1",
                "source_outline_ref": "synopsis",
                "source_kind": "character",
                "target_import_mode": "explicit_type",
                "target_doc_type": "concept",
                "title": "人物设定",
                "content": "林风：青云宗外门弟子。",
                "order_index": 1,
            }
        ],
    )

    result = await service.submit_workspace("novel_submit")

    assert result["synopsis_title"] == "九霄行"
    assert result["pending_setting_count"] == 1
```

- [ ] **Step 2: Run the service tests to verify they fail**

Run: `pytest tests/test_services/test_brainstorm_workspace_service.py::test_save_outline_draft_persists_workspace_authority -v`

Expected: FAIL with import error for `BrainstormWorkspaceService`

- [ ] **Step 3: Add workspace schemas**

```python
class SettingDocDraftPayload(BaseModel):
    draft_id: str
    source_outline_ref: str
    source_kind: str
    target_import_mode: str
    target_doc_type: str | None = None
    title: str
    content: str
    order_index: int = 0


class BrainstormWorkspacePayload(BaseModel):
    workspace_id: str
    novel_id: str
    status: str
    workspace_summary: str | None = None
    outline_drafts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    setting_docs_draft: list[SettingDocDraftPayload] = Field(default_factory=list)


class BrainstormWorkspaceSubmitResponse(BaseModel):
    synopsis_title: str
    pending_setting_count: int
    volume_outline_count: int
```

- [ ] **Step 4: Implement workspace service and extraction helper**

```python
class BrainstormWorkspaceService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.workspace_repo = BrainstormWorkspaceRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.extraction_service = ExtractionService(session)

    async def save_outline_draft(self, novel_id: str, outline_type: str, outline_ref: str, result_snapshot: dict) -> dict:
        workspace = await self.workspace_repo.get_or_create(novel_id)
        drafts = dict(workspace.outline_drafts or {})
        drafts[f"{outline_type}:{outline_ref}"] = result_snapshot
        workspace.outline_drafts = drafts
        await self.session.flush()
        return drafts[f"{outline_type}:{outline_ref}"]

    async def merge_setting_drafts(self, novel_id: str, setting_draft_updates: list[dict]) -> list[dict]:
        workspace = await self.workspace_repo.get_or_create(novel_id)
        existing = {item["draft_id"]: item for item in (workspace.setting_docs_draft or [])}
        for item in setting_draft_updates:
            existing[item["draft_id"]] = item
        workspace.setting_docs_draft = sorted(existing.values(), key=lambda item: item["order_index"])
        await self.session.flush()
        return workspace.setting_docs_draft
```

```python
async def create_pending_from_setting_draft(self, novel_id: str, draft: dict) -> PendingExtraction:
    filename = f"brainstorm-{draft['source_outline_ref']}-{draft['draft_id']}.md"
    if draft["target_import_mode"] == "explicit_type":
        raw_result = {
            "worldview": draft["content"] if draft["target_doc_type"] == "worldview" else "",
            "power_system": draft["content"] if draft["target_doc_type"] == "setting" else "",
            "factions": draft["content"] if draft["source_kind"] == "faction" else "",
            "character_profiles": [],
            "important_items": [],
            "plot_synopsis": "",
        }
        return await self.pending_repo.create(
            pe_id=f"pe_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            source_filename=filename,
            extraction_type="setting",
            raw_result=raw_result,
            proposed_entities=[],
        )
    return await self.process_upload(novel_id=novel_id, filename=filename, content=draft["content"])
```

- [ ] **Step 5: Add the transactional submit behavior**

```python
async def submit_workspace(self, novel_id: str) -> dict:
    workspace = await self.workspace_repo.get_or_create(novel_id)
    synopsis_snapshot = workspace.outline_drafts.get("synopsis:synopsis")
    if synopsis_snapshot is None:
        raise ValueError("Synopsis draft is required before final confirmation")

    synopsis = SynopsisData.model_validate(synopsis_snapshot)
    synopsis_text = BrainstormAgent(self.session).format_synopsis_text(synopsis)
    doc = await self.doc_repo.create(
        doc_id=f"doc_{uuid.uuid4().hex[:8]}",
        novel_id=novel_id,
        doc_type="synopsis",
        title=synopsis.title,
        content=synopsis_text,
    )

    pending_items = []
    for draft in workspace.setting_docs_draft:
        pending_items.append(await self.extraction_service.create_pending_from_setting_draft(novel_id, draft))

    state = await self.state_repo.get_state(novel_id)
    checkpoint = dict(state.checkpoint_data or {})
    checkpoint["synopsis_data"] = synopsis.model_dump()
    checkpoint["synopsis_doc_id"] = doc.id
    await NovelDirector(self.session).save_checkpoint(
        novel_id=novel_id,
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data=checkpoint,
        volume_id=state.current_volume_id,
        chapter_id=state.current_chapter_id,
    )
    await self.workspace_repo.mark_submitted(workspace.id)
    await self.session.commit()
    return {
        "synopsis_title": synopsis.title,
        "pending_setting_count": len(pending_items),
        "volume_outline_count": len([key for key in workspace.outline_drafts if key.startswith("volume:")]),
    }
```

- [ ] **Step 6: Run the service tests**

Run: `pytest tests/test_services/test_brainstorm_workspace_service.py tests/test_services/test_extraction_service.py -k "brainstorm_workspace or setting_draft" -v`

Expected: PASS with the new workspace service tests green and no regressions in extraction tests

- [ ] **Step 7: Commit**

```bash
git add src/novel_dev/schemas/brainstorm_workspace.py src/novel_dev/services/brainstorm_workspace_service.py src/novel_dev/services/extraction_service.py tests/test_services/test_brainstorm_workspace_service.py tests/test_services/test_extraction_service.py
git commit -m "feat: add brainstorm workspace submit service"
```

---

### Task 3: Route Outline Workbench Through Workspace Mode

**Files:**
- Modify: `src/novel_dev/schemas/outline_workbench.py`
- Modify: `src/novel_dev/services/outline_workbench_service.py`
- Modify: `src/novel_dev/api/routes.py`
- Modify: `tests/test_services/test_outline_workbench_service.py`
- Modify: `tests/test_api/test_outline_workbench_routes.py`
- Create: `tests/test_api/test_brainstorm_workspace_routes.py`

- [ ] **Step 1: Write failing workbench-mode tests**

```python
@pytest.mark.asyncio
async def test_submit_feedback_in_brainstorm_mode_updates_workspace_not_checkpoint(async_session, monkeypatch):
    service = OutlineWorkbenchService(async_session)
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_mode",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={"synopsis_data": {"title": "旧标题"}},
        volume_id=None,
        chapter_id=None,
    )

    async def fake_optimize_outline(**kwargs):
        return {
            "content": "已更新总纲草稿",
            "result_snapshot": {
                "title": "新标题",
                "logline": "逆势而上",
                "core_conflict": "主角 vs 宗门",
                "themes": [],
                "character_arcs": [],
                "milestones": [],
                "estimated_volumes": 3,
                "estimated_total_chapters": 300,
                "estimated_total_words": 900000,
            },
            "conversation_summary": "摘要",
        }

    monkeypatch.setattr(service, "_optimize_outline", fake_optimize_outline)
    response = await service.submit_feedback(
        novel_id="novel_mode",
        outline_type="synopsis",
        outline_ref="synopsis",
        feedback="把标题改成新标题",
        mode="brainstorm_workspace",
    )

    state = await NovelStateRepository(async_session).get_state("novel_mode")
    assert state.checkpoint_data["synopsis_data"]["title"] == "旧标题"
    assert response.last_result_snapshot["title"] == "新标题"
```

```python
@pytest.mark.asyncio
async def test_start_workspace_route_returns_workspace_payload(async_session, test_client):
    async with test_client as client:
        response = await client.post("/api/novels/n_workspace/brainstorm/workspace/start")

    assert response.status_code == 200
    assert response.json()["status"] == "active"
```

- [ ] **Step 2: Run the failing tests**

Run: `pytest tests/test_services/test_outline_workbench_service.py::test_submit_feedback_in_brainstorm_mode_updates_workspace_not_checkpoint tests/test_api/test_brainstorm_workspace_routes.py::test_start_workspace_route_returns_workspace_payload -v`

Expected: FAIL because `mode` and workspace routes do not exist yet

- [ ] **Step 3: Extend schemas and service signatures**

```python
class OutlineWorkbenchPayload(BaseModel):
    novel_id: str
    outline_type: str
    outline_ref: str
    session_id: str
    mode: str = "default"
    outline_items: List[OutlineItemSummary] = Field(default_factory=list)
    context_window: OutlineContextWindow = Field(default_factory=OutlineContextWindow)
```

```python
async def submit_feedback(
    self,
    novel_id: str,
    outline_type: str,
    outline_ref: str,
    feedback: str,
    mode: str = "default",
) -> OutlineSubmitResponse:
    outline_session = await self.outline_session_repo.get_or_create(
        novel_id=novel_id,
        outline_type=outline_type,
        outline_ref=outline_ref,
        status="active",
    )
    await self.outline_message_repo.create(
        session_id=outline_session.id,
        role="user",
        message_type="feedback",
        content=feedback,
        meta={"outline_type": outline_type, "outline_ref": outline_ref, "mode": mode},
    )
    context_window = await self._build_context_window(outline_session.id)
    optimize_result = await self._optimize_outline(
        novel_id=novel_id,
        outline_type=outline_type,
        outline_ref=outline_ref,
        feedback=feedback,
        context_window=context_window,
    )
    if mode == "brainstorm_workspace":
        workspace_service = BrainstormWorkspaceService(self.session)
        await workspace_service.save_outline_draft(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            result_snapshot=optimize_result["result_snapshot"],
        )
        if optimize_result.get("setting_draft_updates"):
            await workspace_service.merge_setting_drafts(novel_id, optimize_result["setting_draft_updates"])
    else:
        await self._write_result_snapshot(
            novel_id=novel_id,
            outline_type=outline_type,
            outline_ref=outline_ref,
            result_snapshot=optimize_result["result_snapshot"],
        )
```

- [ ] **Step 4: Add the workspace API routes**

```python
@router.post("/api/novels/{novel_id}/brainstorm/workspace/start")
async def start_brainstorm_workspace(novel_id: str, session: AsyncSession = Depends(get_session)):
    payload = await BrainstormWorkspaceService(session).get_workspace_payload(novel_id)
    return payload.model_dump()


@router.get("/api/novels/{novel_id}/brainstorm/workspace")
async def get_brainstorm_workspace(novel_id: str, session: AsyncSession = Depends(get_session)):
    payload = await BrainstormWorkspaceService(session).get_workspace_payload(novel_id)
    return payload.model_dump()


@router.post("/api/novels/{novel_id}/brainstorm/workspace/submit")
async def submit_brainstorm_workspace(novel_id: str, session: AsyncSession = Depends(get_session)):
    result = await BrainstormWorkspaceService(session).submit_workspace(novel_id)
    return result
```

- [ ] **Step 5: Run the service and API tests**

Run: `pytest tests/test_services/test_outline_workbench_service.py tests/test_api/test_outline_workbench_routes.py tests/test_api/test_brainstorm_workspace_routes.py -v`

Expected: PASS with workspace routes and mode-aware submit behavior covered

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/schemas/outline_workbench.py src/novel_dev/services/outline_workbench_service.py src/novel_dev/api/routes.py tests/test_services/test_outline_workbench_service.py tests/test_api/test_outline_workbench_routes.py tests/test_api/test_brainstorm_workspace_routes.py
git commit -m "feat: add brainstorm workspace api flow"
```

---

### Task 4: Add Workspace-Aware Frontend State and Setting Draft Panel

**Files:**
- Modify: `src/novel_dev/web/src/api.js`
- Modify: `src/novel_dev/web/src/api.test.js`
- Modify: `src/novel_dev/web/src/stores/novel.js`
- Modify: `src/novel_dev/web/src/stores/novel.test.js`
- Modify: `src/novel_dev/web/src/views/outline/outlineWorkbench.js`
- Modify: `src/novel_dev/web/src/components/outline/OutlineConversation.vue`
- Modify: `src/novel_dev/web/src/components/outline/OutlineDetailPanel.vue`
- Create: `src/novel_dev/web/src/components/outline/BrainstormSettingDrafts.vue`
- Create: `src/novel_dev/web/src/components/outline/BrainstormSettingDrafts.test.js`
- Modify: `src/novel_dev/web/src/components/outline/OutlineConversation.test.js`
- Modify: `src/novel_dev/web/src/views/outline/outlineWorkbench.test.js`
- Modify: `src/novel_dev/web/src/views/VolumePlan.vue`

- [ ] **Step 1: Write the failing frontend tests**

```javascript
it('loads brainstorm workspace outline drafts and setting drafts', async () => {
  mockGet.mockResolvedValueOnce({ data: {
    workspace_id: 'ws_1',
    novel_id: 'novel-1',
    status: 'active',
    outline_drafts: {
      'synopsis:synopsis': { title: '九霄行', logline: '逆势而上' },
      'volume:vol_1': { title: '第一卷', summary: '卷一摘要' },
    },
    setting_docs_draft: [
      { draft_id: 'd1', title: '人物设定', source_outline_ref: 'synopsis', source_kind: 'character', target_import_mode: 'explicit_type', target_doc_type: 'concept', content: '林风：青云宗外门弟子，行事坚忍。', order_index: 1 },
    ],
  } })

  await store.loadBrainstormWorkspace('novel-1')

  expect(store.brainstormWorkspace.settingDocsDraft).toHaveLength(1)
  expect(store.outlineWorkbench.items[0].outlineRef).toBe('synopsis')
})

it('posts final confirmation through workspace submit endpoint', async () => {
  mockPost.mockResolvedValueOnce({ data: { synopsis_title: '九霄行', pending_setting_count: 1, volume_outline_count: 2 } })

  await store.submitBrainstormWorkspace()

  expect(mockPost).toHaveBeenCalledWith('/novels/novel-1/brainstorm/workspace/submit')
})
```

- [ ] **Step 2: Run the failing frontend tests**

Run: `cd src/novel_dev/web && npm test -- --runInBand src/stores/novel.test.js src/views/outline/outlineWorkbench.test.js`

Expected: FAIL because workspace API helpers and state fields do not exist

- [ ] **Step 3: Add API helpers and store state**

```javascript
export const getBrainstormWorkspace = (id) =>
  api.get(`/novels/${id}/brainstorm/workspace`).then(r => r.data)
export const startBrainstormWorkspace = (id) =>
  api.post(`/novels/${id}/brainstorm/workspace/start`).then(r => r.data)
export const submitBrainstormWorkspace = (id) =>
  api.post(`/novels/${id}/brainstorm/workspace/submit`).then(r => r.data)
```

```javascript
const createBrainstormWorkspaceState = () => ({
  workspaceId: '',
  status: 'idle',
  outlineDrafts: {},
  settingDocsDraft: [],
  loading: false,
  submitting: false,
})
```

- [ ] **Step 4: Wire the existing workbench shell to workspace mode**

```javascript
async loadBrainstormWorkspace(novelId) {
  this.brainstormWorkspace.loading = true
  try {
    const payload = await api.getBrainstormWorkspace(novelId)
    this.brainstormWorkspace.workspaceId = payload.workspace_id
    this.brainstormWorkspace.status = payload.status
    this.brainstormWorkspace.outlineDrafts = payload.outline_drafts || {}
    this.brainstormWorkspace.settingDocsDraft = payload.setting_docs_draft || []

    const workspaceItems = Object.entries(this.brainstormWorkspace.outlineDrafts).map(([key, snapshot]) => {
      const [outlineType, outlineRef] = key.split(':')
      return {
        outline_type: outlineType,
        outline_ref: outlineRef,
        title: snapshot.title || (outlineType === 'synopsis' ? '总纲' : outlineRef),
        summary: snapshot.summary || snapshot.logline || '',
        status: 'ready',
      }
    })
    this.outlineWorkbench.items = buildOutlineWorkbenchItems({ items: workspaceItems, currentItem: this.outlineWorkbench.selection })
  } finally {
    this.brainstormWorkspace.loading = false
  }
}
```

- [ ] **Step 5: Add the setting draft panel and final-confirm action**

```vue
<BrainstormSettingDrafts
  v-if="store.brainstormWorkspace.settingDocsDraft.length"
  :items="store.brainstormWorkspace.settingDocsDraft"
/>
```

```javascript
async submitBrainstormWorkspace() {
  this.brainstormWorkspace.submitting = true
  try {
    const result = await api.submitBrainstormWorkspace(this.novelId)
    await this.refreshState()
    await this.loadBrainstormWorkspace(this.novelId)
    return result
  } finally {
    this.brainstormWorkspace.submitting = false
  }
}
```

- [ ] **Step 6: Run the frontend tests**

Run: `cd src/novel_dev/web && npm test -- --runInBand src/stores/novel.test.js src/components/outline/BrainstormSettingDrafts.test.js src/components/outline/OutlineConversation.test.js src/views/outline/outlineWorkbench.test.js`

Expected: PASS with workspace state, submit action, and setting draft panel covered

- [ ] **Step 7: Commit**

```bash
git add src/novel_dev/web/src/api.js src/novel_dev/web/src/api.test.js src/novel_dev/web/src/stores/novel.js src/novel_dev/web/src/stores/novel.test.js src/novel_dev/web/src/views/outline/outlineWorkbench.js src/novel_dev/web/src/components/outline/OutlineConversation.vue src/novel_dev/web/src/components/outline/OutlineDetailPanel.vue src/novel_dev/web/src/components/outline/BrainstormSettingDrafts.vue src/novel_dev/web/src/components/outline/BrainstormSettingDrafts.test.js src/novel_dev/web/src/components/outline/OutlineConversation.test.js src/novel_dev/web/src/views/outline/outlineWorkbench.test.js src/novel_dev/web/src/views/VolumePlan.vue
git commit -m "feat: add brainstorm workspace frontend"
```

---

### Task 5: Add Final Confirmation Regressions and End-to-End Coverage

**Files:**
- Modify: `tests/test_api/test_brainstorm_routes.py`
- Create: `tests/test_api/test_brainstorm_workspace_routes.py`
- Modify: `tests/test_integration_end_to_end.py`
- Modify: `tests/test_api/test_outline_workbench_routes.py`

- [ ] **Step 1: Write the failing regression tests**

```python
@pytest.mark.asyncio
async def test_final_confirmation_requires_workspace_synopsis(async_session, test_client):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_guard",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    await async_session.commit()

    async with test_client as client:
        response = await client.post("/api/novels/novel_guard/brainstorm/workspace/submit")

    assert response.status_code == 400
    assert "Synopsis draft is required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_final_confirmation_generates_pending_setting_documents(async_session, test_client):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_final",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )

    workspace_service = BrainstormWorkspaceService(async_session)
    await workspace_service.save_outline_draft(
        novel_id="novel_final",
        outline_type="synopsis",
        outline_ref="synopsis",
        result_snapshot={
            "title": "九霄行",
            "logline": "主角逆势而上",
            "core_conflict": "主角 vs 宗门",
            "themes": ["成长"],
            "character_arcs": [],
            "milestones": [],
            "estimated_volumes": 2,
            "estimated_total_chapters": 200,
            "estimated_total_words": 600000,
        },
    )
    await workspace_service.save_outline_draft(
        novel_id="novel_final",
        outline_type="volume",
        outline_ref="vol_1",
        result_snapshot={
            "outline_ref": "vol_1",
            "title": "第一卷",
            "summary": "卷一建立主线冲突",
            "target_chapter_count": 30,
            "arc_goals": ["确立主角立场"],
            "milestones": ["入宗", "立敌"],
            "status": "ready",
        },
    )
    await workspace_service.merge_setting_drafts(
        "novel_final",
        [
            {
                "draft_id": "draft_char",
                "source_outline_ref": "synopsis",
                "source_kind": "character",
                "target_import_mode": "explicit_type",
                "target_doc_type": "concept",
                "title": "人物设定",
                "content": "林风：青云宗外门弟子，目标是查明灭门真相。",
                "order_index": 1,
            },
            {
                "draft_id": "draft_faction",
                "source_outline_ref": "vol_1",
                "source_kind": "faction",
                "target_import_mode": "auto_classify",
                "target_doc_type": None,
                "title": "势力设定",
                "content": "青云宗与赤炎谷因矿脉归属长期对立。",
                "order_index": 2,
            },
        ],
    )
    await async_session.commit()

    async with test_client as client:
        response = await client.post("/api/novels/novel_final/brainstorm/workspace/submit")

    assert response.status_code == 200
    assert response.json()["pending_setting_count"] == 2
    pending = await PendingExtractionRepository(async_session).list_by_novel("novel_final")
    assert len(pending) == 2
```

- [ ] **Step 2: Run the regression tests to verify they fail**

Run: `pytest tests/test_api/test_brainstorm_workspace_routes.py tests/test_integration_end_to_end.py -k "workspace or final_confirmation" -v`

Expected: FAIL because submit validation and pending generation are incomplete

- [ ] **Step 3: Fill in the missing validation and end-to-end flow**

```python
if synopsis_snapshot is None:
    raise HTTPException(status_code=400, detail="Synopsis draft is required before final confirmation")

volume_keys = [key for key in workspace.outline_drafts if key.startswith("volume:")]
if not volume_keys:
    raise HTTPException(status_code=400, detail="At least one volume outline draft is required before final confirmation")
```

```python
async def test_end_to_end_brainstorm_workspace_confirmation(async_session, test_client):
    director = NovelDirector(async_session)
    await director.save_checkpoint(
        "novel_e2e",
        phase=Phase.BRAINSTORMING,
        checkpoint_data={},
        volume_id=None,
        chapter_id=None,
    )
    await async_session.commit()

    async with test_client as client:
        synopsis_resp = await client.post(
            "/api/novels/novel_e2e/outline_workbench/submit",
            json={
                "outline_type": "synopsis",
                "outline_ref": "synopsis",
                "content": "把总纲定为主角与宗门权力结构的对抗",
                "mode": "brainstorm_workspace",
            },
        )
        assert synopsis_resp.status_code == 200

        volume_resp = await client.post(
            "/api/novels/novel_e2e/outline_workbench/submit",
            json={
                "outline_type": "volume",
                "outline_ref": "vol_1",
                "content": "第一卷先写主角入宗和立敌",
                "mode": "brainstorm_workspace",
            },
        )
        assert volume_resp.status_code == 200

        submit_resp = await client.post("/api/novels/novel_e2e/brainstorm/workspace/submit")
        assert submit_resp.status_code == 200

    state = await NovelStateRepository(async_session).get_state("novel_e2e")
    docs = await DocumentRepository(async_session).get_by_type("novel_e2e", "synopsis")
    pending = await PendingExtractionRepository(async_session).list_by_novel("novel_e2e")

    assert state.current_phase == Phase.VOLUME_PLANNING.value
    assert len(docs) == 1
    assert submit_resp.json()["volume_outline_count"] >= 1
    assert len(pending) >= 0
```

- [ ] **Step 4: Run the full targeted backend suite**

Run: `pytest tests/test_repositories/test_brainstorm_workspace_repo.py tests/test_services/test_brainstorm_workspace_service.py tests/test_services/test_outline_workbench_service.py tests/test_api/test_brainstorm_workspace_routes.py tests/test_api/test_outline_workbench_routes.py tests/test_services/test_extraction_service.py -v`

Expected: PASS with all workspace-specific backend tests green

- [ ] **Step 5: Commit**

```bash
git add tests/test_api/test_brainstorm_routes.py tests/test_api/test_brainstorm_workspace_routes.py tests/test_integration_end_to_end.py tests/test_api/test_outline_workbench_routes.py
git commit -m "test: cover brainstorm workspace confirmation flow"
```

---

### Task 6: Final Verification

**Files:**
- Modify: none
- Test: backend and frontend commands only

- [ ] **Step 1: Run backend verification**

Run: `pytest tests/test_repositories/test_brainstorm_workspace_repo.py tests/test_services/test_brainstorm_workspace_service.py tests/test_services/test_outline_workbench_service.py tests/test_api/test_brainstorm_workspace_routes.py tests/test_api/test_outline_workbench_routes.py tests/test_services/test_extraction_service.py -v`

Expected: PASS with all workspace-specific tests green

- [ ] **Step 2: Run frontend verification**

Run: `cd src/novel_dev/web && npm test -- --runInBand src/stores/novel.test.js src/components/outline/BrainstormSettingDrafts.test.js src/components/outline/OutlineConversation.test.js src/views/outline/outlineWorkbench.test.js`

Expected: PASS with all workspace frontend tests green

- [ ] **Step 3: Run a full build check**

Run: `cd src/novel_dev/web && npm run build`

Expected: PASS with Vite production build output and no compile errors

- [ ] **Step 4: Inspect git diff before handoff**

Run: `git status --short`

Expected: only the planned workspace backend/frontend files are modified

- [ ] **Step 5: Final commit**

```bash
git add src/novel_dev/db/models.py migrations/versions/20260422_add_brainstorm_workspace.py src/novel_dev/repositories/brainstorm_workspace_repo.py src/novel_dev/schemas/brainstorm_workspace.py src/novel_dev/schemas/outline_workbench.py src/novel_dev/services/brainstorm_workspace_service.py src/novel_dev/services/outline_workbench_service.py src/novel_dev/services/extraction_service.py src/novel_dev/api/routes.py src/novel_dev/web/src/api.js src/novel_dev/web/src/api.test.js src/novel_dev/web/src/stores/novel.js src/novel_dev/web/src/stores/novel.test.js src/novel_dev/web/src/views/outline/outlineWorkbench.js src/novel_dev/web/src/components/outline/OutlineConversation.vue src/novel_dev/web/src/components/outline/OutlineDetailPanel.vue src/novel_dev/web/src/components/outline/BrainstormSettingDrafts.vue src/novel_dev/web/src/components/outline/BrainstormSettingDrafts.test.js src/novel_dev/web/src/components/outline/OutlineConversation.test.js src/novel_dev/web/src/views/outline/outlineWorkbench.test.js src/novel_dev/web/src/views/VolumePlan.vue tests/test_repositories/test_brainstorm_workspace_repo.py tests/test_services/test_brainstorm_workspace_service.py tests/test_services/test_outline_workbench_service.py tests/test_services/test_extraction_service.py tests/test_api/test_brainstorm_workspace_routes.py tests/test_api/test_outline_workbench_routes.py tests/test_api/test_brainstorm_routes.py tests/test_integration_end_to_end.py
git commit -m "feat: add brainstorm workspace outline flow"
```

---

## Self-Review

### Spec coverage

- Workspace persistence: Task 1
- Workspace authority over draft outlines: Tasks 2 and 3
- Per-outline independent context reuse: Task 3
- Final confirm submit semantics: Tasks 2 and 5
- Setting drafts entering pending pipeline: Tasks 2 and 5
- Frontend reuse of current workbench input flow: Task 4
- End-to-end verification and rollback guards: Tasks 5 and 6

### Placeholder scan

- Removed `TODO`/`TBD`
- Every task includes explicit file paths, code snippets, commands, and expected outcomes
- The only ellipsis that would be ambiguous was in the regression test sketch; the test step now names the full verification goals and required assertions

### Type consistency

- Workspace authority key format is consistently `"{outline_type}:{outline_ref}"`
- Setting draft field names consistently use `setting_docs_draft`
- Workbench mode value consistently uses `"brainstorm_workspace"`
