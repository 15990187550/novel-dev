# Brainstorm Workspace Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the brainstorm workspace flow so outline workbench edits stay in workspace drafts during `brainstorming`, expose explicit workspace APIs, and let the frontend review setting drafts plus perform final confirmation.

**Architecture:** Keep `outline_sessions` / `outline_messages` as the per-outline conversation layer, but branch behavior by novel phase: during `brainstorming`, `OutlineWorkbenchService` reads and writes through `BrainstormWorkspaceService`; outside it, keep the existing checkpoint-backed behavior. Add explicit workspace endpoints for start/get/submit and extend the frontend store/view to load workspace payload, show setting drafts, and submit the final confirmation action.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, Vue 3, Pinia, Vitest, Pytest

---

### Task 1: Backend workspace-aware workbench tests

**Files:**
- Modify: `tests/test_services/test_outline_workbench_service.py`
- Modify: `tests/test_api/test_routes.py` or create a new focused brainstorm-workspace route test file if route coverage is missing

- [ ] Add a failing service test proving `build_workbench()` uses `BrainstormWorkspace.outline_drafts` instead of `checkpoint_data` when the novel is in `brainstorming`.
- [ ] Run the focused pytest command and confirm the new test fails for the expected reason.
- [ ] Add a failing service test proving `submit_feedback()` in `brainstorming` updates workspace drafts and session snapshots without mutating formal checkpoint data.
- [ ] Run the focused pytest command and confirm the new test fails for the expected reason.
- [ ] Add failing route tests for `POST /api/novels/{id}/brainstorm/workspace/start`, `GET /api/novels/{id}/brainstorm/workspace`, and `POST /api/novels/{id}/brainstorm/workspace/submit`.
- [ ] Run the route-focused pytest command and confirm the new tests fail before implementation.

### Task 2: Backend workspace-aware workbench implementation

**Files:**
- Modify: `src/novel_dev/services/outline_workbench_service.py`
- Modify: `src/novel_dev/api/routes.py`
- Modify: `src/novel_dev/schemas/outline_workbench.py`
- Modify: `src/novel_dev/schemas/brainstorm_workspace.py` if additional response fields are needed

- [ ] Inject `BrainstormWorkspaceService` into `OutlineWorkbenchService`.
- [ ] Make `build_workbench()` detect `brainstorming` phase and build outline items from workspace drafts plus placeholders derived from the draft synopsis volume count.
- [ ] Make `submit_feedback()` branch by phase:
  - `brainstorming`: update session messages/snapshot, persist workspace draft, keep formal checkpoint unchanged.
  - other phases: preserve existing formal checkpoint behavior.
- [ ] Extend the optimize result shape to carry `setting_draft_updates`, even if current generators return an empty list, and merge them through `BrainstormWorkspaceService` in brainstorming mode.
- [ ] Add explicit workspace routes:
  - `POST /api/novels/{novel_id}/brainstorm/workspace/start`
  - `GET /api/novels/{novel_id}/brainstorm/workspace`
  - `POST /api/novels/{novel_id}/brainstorm/workspace/submit`
- [ ] Return appropriate HTTP 404/409/400 responses for missing state, wrong phase, and duplicate submission cases.
- [ ] Re-run the focused backend pytest commands until green.

### Task 3: Frontend workspace integration tests

**Files:**
- Modify: `src/novel_dev/web/src/stores/novel.test.js`
- Modify: `src/novel_dev/web/src/views/VolumePlan.test.js`
- Modify: `src/novel_dev/web/src/api.test.js`

- [ ] Add a failing store test proving `refreshOutlineWorkbench()` also loads brainstorm workspace data during `brainstorming`.
- [ ] Add a failing store test proving final confirmation calls the workspace submit API and refreshes novel/workbench state.
- [ ] Add a failing `VolumePlan` test proving the page renders a final-confirmation action and a setting-drafts section when workspace data exists.
- [ ] Add a failing API test for the new workspace endpoints.
- [ ] Run the focused Vitest commands and confirm the new tests fail before UI/store implementation.

### Task 4: Frontend workspace integration implementation

**Files:**
- Modify: `src/novel_dev/web/src/api.js`
- Modify: `src/novel_dev/web/src/stores/novel.js`
- Modify: `src/novel_dev/web/src/views/VolumePlan.vue`
- Optionally create: `src/novel_dev/web/src/components/outline/SettingDraftPanel.vue`

- [ ] Add API helpers for workspace `start`, `get`, and `submit`.
- [ ] Extend Pinia state with brainstorm workspace payload/loading/submitting state.
- [ ] Load workspace payload alongside outline workbench when the novel phase is `brainstorming`.
- [ ] Expose a store action for final confirmation that calls the new submit endpoint and refreshes state/workbench/workspace.
- [ ] Render a “最终确认” button in `VolumePlan.vue` only during brainstorm workspace mode.
- [ ] Render a setting-drafts panel or drawer using `setting_docs_draft` from workspace payload.
- [ ] Keep existing non-brainstorming behavior unchanged.
- [ ] Re-run the focused Vitest commands until green.

### Task 5: Verification

**Files:**
- No code changes expected

- [ ] Run `PYTHONPATH=src python3.11 -m pytest tests/test_services/test_brainstorm_workspace_service.py tests/test_services/test_outline_workbench_service.py tests/test_api/test_routes.py -q`
- [ ] Run `cd src/novel_dev/web && npm run test -- src/api.test.js src/stores/novel.test.js src/views/VolumePlan.test.js`
- [ ] Run `cd src/novel_dev/web && npm run build`
- [ ] Review outputs for failures or unexpected warnings and fix anything blocking the new flow.
