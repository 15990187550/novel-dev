# Setting Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-click setting consolidation flow that turns approved settings plus user-selected pending records into an auditable review batch, then archives old scattered content only after approval.

**Architecture:** Reuse the setting workbench and existing background `generation_jobs` infrastructure. Add explicit setting review batches/changes, a consolidation service that snapshots inputs before calling AI, and archive metadata on formal documents, entities, and relationships. The frontend starts a consolidation job from the setting workbench, polls the job, and renders the resulting grouped review record.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic, Pydantic v2, existing LLM factory/helpers, Vue 3, Pinia, Element Plus, Vitest, pytest.

---

## File Structure

- Modify `src/novel_dev/db/models.py`: add `SettingReviewBatch`, `SettingReviewChange`, AI source fields, and archive metadata fields.
- Create `migrations/versions/20260504_add_setting_consolidation_review.py`: add review tables and archive/source columns. This migration should revise `20260504_setting_sessions`, which exists in the current working tree.
- Modify `src/novel_dev/schemas/setting_workbench.py`: add consolidation request/response schemas, review batch/change schemas, conflict resolution schemas, and approval schemas.
- Modify `src/novel_dev/repositories/setting_workbench_repo.py`: add review batch/change CRUD and archive-aware list helpers.
- Create `src/novel_dev/agents/setting_consolidation_agent.py`: build the LLM prompt and parse structured consolidation output.
- Create `src/novel_dev/services/setting_consolidation_service.py`: snapshot inputs, run consolidation, create review changes, apply approved changes, and enforce conflict rules.
- Modify `src/novel_dev/services/generation_job_service.py`: route `setting_consolidation` jobs to `SettingConsolidationService`.
- Modify `src/novel_dev/api/routes.py`: add consolidation start/list/detail/approve/conflict routes and serializers.
- Modify `src/novel_dev/services/novel_deletion_service.py`: include review batches and changes in novel deletion.
- Modify `src/novel_dev/web/src/api.js`: add setting consolidation and review API calls.
- Modify `src/novel_dev/web/src/stores/novel.js`: add setting consolidation state, actions, and job polling.
- Modify `src/novel_dev/web/src/views/SettingWorkbench.vue`: add the one-click entry, source selection dialog, job status, and grouped review detail.
- Modify `src/novel_dev/web/src/views/Documents.vue`: rename review language from import-only to unified **审核记录** where existing pending records are displayed.
- Modify `src/novel_dev/web/src/views/Entities.vue` and `src/novel_dev/web/src/components/EntityGraph.vue`: hide archived entities/relationships by default and expose an archive filter.
- Add tests in `tests/test_repositories/test_setting_workbench_repo.py`, `tests/test_services/test_setting_consolidation_service.py`, `tests/test_api/test_setting_consolidation_routes.py`, `src/novel_dev/web/src/views/SettingWorkbench.test.js`, `src/novel_dev/web/src/stores/novel.test.js`, and `src/novel_dev/web/src/api.test.js`.

## Task 1: Persistence For Review Batches And Archive Metadata

**Files:**
- Modify: `src/novel_dev/db/models.py`
- Create: `migrations/versions/20260504_add_setting_consolidation_review.py`
- Test: `tests/test_repositories/test_setting_workbench_repo.py`

- [ ] **Step 1: Add failing repository coverage for review batches and archive metadata**

Append these tests to `tests/test_repositories/test_setting_workbench_repo.py`:

```python
async def test_setting_workbench_repo_creates_consolidation_batch_and_changes(async_session):
    repo = SettingWorkbenchRepository(async_session)

    batch = await repo.create_review_batch(
        novel_id="novel-setting",
        source_type="consolidation",
        summary="整合 2 条设定，发现 1 个冲突",
        input_snapshot={"documents": [{"id": "doc-1", "title": "旧修炼体系"}]},
        job_id="job_consolidate_1",
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={
            "doc_type": "setting",
            "title": "修炼体系总览",
            "content": "炼气、筑基、金丹三境。",
        },
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="archive",
        target_id="doc-1",
        before_snapshot={"title": "旧修炼体系"},
        conflict_hints=[],
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="conflict",
        operation="resolve",
        after_snapshot={
            "title": "境界冲突",
            "options": [
                {"key": "a", "content": "炼气九层"},
                {"key": "b", "content": "炼气十二层"},
            ],
        },
        conflict_hints=[{"reason": "同一境界层数不一致"}],
    )
    await async_session.commit()

    batches = await repo.list_review_batches("novel-setting")
    changes = await repo.list_review_changes(batch.id)

    assert batches[0].source_type == "consolidation"
    assert batches[0].status == "pending"
    assert batches[0].input_snapshot["documents"][0]["id"] == "doc-1"
    assert [change.operation for change in changes] == ["create", "archive", "resolve"]
    assert changes[2].target_type == "conflict"
    assert changes[2].status == "pending"
```

- [ ] **Step 2: Run the repository test and confirm it fails for missing review APIs**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_setting_workbench_repo.py::test_setting_workbench_repo_creates_consolidation_batch_and_changes -q
```

Expected: FAIL with `AttributeError: 'SettingWorkbenchRepository' object has no attribute 'create_review_batch'`.

- [ ] **Step 3: Add ORM fields and review models**

Modify `src/novel_dev/db/models.py`.

Add these fields to `Entity`, `EntityRelationship`, and `NovelDocument`:

```python
    source_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_session_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_review_batch_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_review_change_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    archive_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    archived_by_consolidation_batch_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    archived_by_consolidation_change_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

Add these models after `SettingGenerationMessage`:

```python
class SettingReviewBatch(Base):
    __tablename__ = "setting_review_batches"
    __table_args__ = (
        Index("ix_setting_review_batches_novel_status", "novel_id", "status"),
        Index("ix_setting_review_batches_source_session", "source_session_id"),
        Index("ix_setting_review_batches_job", "job_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_file: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_session_id: Mapped[Optional[str]] = mapped_column(ForeignKey("setting_generation_sessions.id"), nullable=True)
    job_id: Mapped[Optional[str]] = mapped_column(ForeignKey("generation_jobs.id"), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    changes: Mapped[List["SettingReviewChange"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="SettingReviewChange.created_at",
    )


class SettingReviewChange(Base):
    __tablename__ = "setting_review_changes"
    __table_args__ = (
        Index("ix_setting_review_changes_batch_status", "batch_id", "status"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("setting_review_batches.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    before_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    conflict_hints: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_session_id: Mapped[Optional[str]] = mapped_column(ForeignKey("setting_generation_sessions.id"), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    batch: Mapped["SettingReviewBatch"] = relationship(back_populates="changes")
```

- [ ] **Step 4: Add the Alembic migration**

Create `migrations/versions/20260504_add_setting_consolidation_review.py`:

```python
"""add setting consolidation review

Revision ID: 20260504_setting_consolidation
Revises: 20260504_setting_sessions
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260504_setting_consolidation"
down_revision: Union[str, Sequence[str], None] = "20260504_setting_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SOURCE_COLUMNS = (
    sa.Column("source_type", sa.Text(), nullable=True),
    sa.Column("source_session_id", sa.Text(), nullable=True),
    sa.Column("source_review_batch_id", sa.Text(), nullable=True),
    sa.Column("source_review_change_id", sa.Text(), nullable=True),
    sa.Column("archived_at", sa.TIMESTAMP(), nullable=True),
    sa.Column("archive_reason", sa.Text(), nullable=True),
    sa.Column("archived_by_consolidation_batch_id", sa.Text(), nullable=True),
    sa.Column("archived_by_consolidation_change_id", sa.Text(), nullable=True),
)


def upgrade() -> None:
    op.create_table(
        "setting_review_batches",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("source_session_id", sa.Text(), sa.ForeignKey("setting_generation_sessions.id"), nullable=True),
        sa.Column("job_id", sa.Text(), sa.ForeignKey("generation_jobs.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
    )
    op.create_index("ix_setting_review_batches_novel_status", "setting_review_batches", ["novel_id", "status"])
    op.create_index("ix_setting_review_batches_source_session", "setting_review_batches", ["source_session_id"])
    op.create_index("ix_setting_review_batches_job", "setting_review_batches", ["job_id"])
    op.create_table(
        "setting_review_changes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("batch_id", sa.Text(), sa.ForeignKey("setting_review_batches.id"), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("before_snapshot", sa.JSON(), nullable=True),
        sa.Column("after_snapshot", sa.JSON(), nullable=True),
        sa.Column("conflict_hints", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_session_id", sa.Text(), sa.ForeignKey("setting_generation_sessions.id"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
    )
    op.create_index("ix_setting_review_changes_batch_status", "setting_review_changes", ["batch_id", "status"])
    for table_name in ("novel_documents", "entities", "entity_relationships"):
        for column in SOURCE_COLUMNS:
            op.add_column(table_name, column.copy())


def downgrade() -> None:
    for table_name in ("entity_relationships", "entities", "novel_documents"):
        for column_name in (
            "archived_by_consolidation_change_id",
            "archived_by_consolidation_batch_id",
            "archive_reason",
            "archived_at",
            "source_review_change_id",
            "source_review_batch_id",
            "source_session_id",
            "source_type",
        ):
            op.drop_column(table_name, column_name)
    op.drop_index("ix_setting_review_changes_batch_status", table_name="setting_review_changes")
    op.drop_table("setting_review_changes")
    op.drop_index("ix_setting_review_batches_job", table_name="setting_review_batches")
    op.drop_index("ix_setting_review_batches_source_session", table_name="setting_review_batches")
    op.drop_index("ix_setting_review_batches_novel_status", table_name="setting_review_batches")
    op.drop_table("setting_review_batches")
```

- [ ] **Step 5: Run repository tests against the new schema**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_setting_workbench_repo.py -q
```

Expected: FAIL still, now because repository methods are not implemented.

- [ ] **Step 6: Commit persistence scaffolding**

```bash
git add src/novel_dev/db/models.py migrations/versions/20260504_add_setting_consolidation_review.py tests/test_repositories/test_setting_workbench_repo.py
git commit -m "Add setting review persistence scaffolding"
```

## Task 2: Review Schemas And Repository Methods

**Files:**
- Modify: `src/novel_dev/schemas/setting_workbench.py`
- Modify: `src/novel_dev/repositories/setting_workbench_repo.py`
- Test: `tests/test_repositories/test_setting_workbench_repo.py`

- [ ] **Step 1: Extend API schemas**

Add these classes to `src/novel_dev/schemas/setting_workbench.py`:

```python
class SettingConsolidationStartRequest(BaseModel):
    selected_pending_ids: list[str] = Field(default_factory=list)


class SettingConsolidationStartResponse(BaseModel):
    job_id: str
    status: str


class SettingReviewChangeResponse(BaseModel):
    id: str
    batch_id: str
    target_type: str
    operation: str
    target_id: Optional[str] = None
    status: str
    before_snapshot: Optional[dict[str, Any]] = None
    after_snapshot: Optional[dict[str, Any]] = None
    conflict_hints: list[dict[str, Any]] = Field(default_factory=list)
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SettingReviewBatchResponse(BaseModel):
    id: str
    novel_id: str
    source_type: str
    source_file: Optional[str] = None
    source_session_id: Optional[str] = None
    job_id: Optional[str] = None
    status: str
    summary: str = ""
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SettingReviewBatchListResponse(BaseModel):
    items: list[SettingReviewBatchResponse] = Field(default_factory=list)


class SettingReviewBatchDetailResponse(BaseModel):
    batch: SettingReviewBatchResponse
    changes: list[SettingReviewChangeResponse] = Field(default_factory=list)


class SettingReviewApproveRequest(BaseModel):
    change_ids: list[str] = Field(default_factory=list)
    approve_all: bool = False


class SettingConflictResolutionRequest(BaseModel):
    change_id: str
    resolved_after_snapshot: dict[str, Any]
```

- [ ] **Step 2: Implement repository methods**

Modify `src/novel_dev/repositories/setting_workbench_repo.py` imports:

```python
from datetime import datetime

from novel_dev.db.models import (
    SettingGenerationMessage,
    SettingGenerationSession,
    SettingReviewBatch,
    SettingReviewChange,
)
```

Add methods to `SettingWorkbenchRepository`:

```python
    async def create_review_batch(
        self,
        *,
        novel_id: str,
        source_type: str,
        summary: str = "",
        input_snapshot: dict | None = None,
        source_file: str | None = None,
        source_session_id: str | None = None,
        job_id: str | None = None,
        status: str = "pending",
    ) -> SettingReviewBatch:
        batch = SettingReviewBatch(
            id=uuid.uuid4().hex,
            novel_id=novel_id,
            source_type=source_type,
            source_file=source_file,
            source_session_id=source_session_id,
            job_id=job_id,
            status=status,
            summary=summary,
            input_snapshot=input_snapshot or {},
        )
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def get_review_batch(self, batch_id: str) -> Optional[SettingReviewBatch]:
        result = await self.session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.id == batch_id)
        )
        return result.scalar_one_or_none()

    async def get_review_batch_by_job(self, job_id: str) -> Optional[SettingReviewBatch]:
        result = await self.session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.job_id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_review_batches(self, novel_id: str) -> list[SettingReviewBatch]:
        result = await self.session.execute(
            select(SettingReviewBatch)
            .where(SettingReviewBatch.novel_id == novel_id)
            .order_by(SettingReviewBatch.updated_at.desc(), SettingReviewBatch.created_at.desc())
        )
        return list(result.scalars().all())

    async def add_review_change(
        self,
        *,
        batch_id: str,
        target_type: str,
        operation: str,
        target_id: str | None = None,
        before_snapshot: dict | None = None,
        after_snapshot: dict | None = None,
        conflict_hints: list | None = None,
        source_session_id: str | None = None,
        status: str = "pending",
    ) -> SettingReviewChange:
        change = SettingReviewChange(
            id=uuid.uuid4().hex,
            batch_id=batch_id,
            target_type=target_type,
            operation=operation,
            target_id=target_id,
            status=status,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            conflict_hints=conflict_hints or [],
            source_session_id=source_session_id,
        )
        self.session.add(change)
        await self.session.flush()
        return change

    async def get_review_change(self, change_id: str) -> Optional[SettingReviewChange]:
        result = await self.session.execute(
            select(SettingReviewChange).where(SettingReviewChange.id == change_id)
        )
        return result.scalar_one_or_none()

    async def list_review_changes(self, batch_id: str) -> list[SettingReviewChange]:
        result = await self.session.execute(
            select(SettingReviewChange)
            .where(SettingReviewChange.batch_id == batch_id)
            .order_by(SettingReviewChange.created_at.asc())
        )
        return list(result.scalars().all())

    async def mark_change_status(
        self,
        change_id: str,
        status: str,
        *,
        after_snapshot: dict | None = None,
        error_message: str | None = None,
    ) -> Optional[SettingReviewChange]:
        change = await self.get_review_change(change_id)
        if change is None:
            return None
        change.status = status
        if after_snapshot is not None:
            change.after_snapshot = after_snapshot
        change.error_message = error_message
        change.updated_at = datetime.utcnow()
        await self.session.flush()
        return change

    async def update_batch_status(
        self,
        batch_id: str,
        status: str,
        *,
        summary: str | None = None,
        error_message: str | None = None,
    ) -> Optional[SettingReviewBatch]:
        batch = await self.get_review_batch(batch_id)
        if batch is None:
            return None
        batch.status = status
        if summary is not None:
            batch.summary = summary
        batch.error_message = error_message
        batch.updated_at = datetime.utcnow()
        await self.session.flush()
        return batch
```

- [ ] **Step 3: Run repository tests**

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_setting_workbench_repo.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit repository and schema work**

```bash
git add src/novel_dev/schemas/setting_workbench.py src/novel_dev/repositories/setting_workbench_repo.py tests/test_repositories/test_setting_workbench_repo.py
git commit -m "Add setting review repository APIs"
```

## Task 3: Consolidation Service, Snapshot Rules, And Review Creation

**Files:**
- Create: `src/novel_dev/agents/setting_consolidation_agent.py`
- Create: `src/novel_dev/services/setting_consolidation_service.py`
- Test: `tests/test_services/test_setting_consolidation_service.py`

- [ ] **Step 1: Write service tests for snapshot selection and review creation**

Create `tests/test_services/test_setting_consolidation_service.py`:

```python
from datetime import datetime

import pytest

from novel_dev.db.models import Entity, EntityRelationship, PendingExtraction
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.services.setting_consolidation_service import SettingConsolidationService

pytestmark = pytest.mark.asyncio


class FakeConsolidationAgent:
    async def consolidate(self, snapshot):
        assert [doc["id"] for doc in snapshot["documents"]] == ["doc-current"]
        assert [entity["id"] for entity in snapshot["entities"]] == ["entity-active"]
        assert [relationship["source_id"] for relationship in snapshot["relationships"]] == ["entity-active"]
        assert [pending["id"] for pending in snapshot["selected_pending"]] == ["pending-selected"]
        return {
            "summary": "生成 1 张整合设定，归档 1 条旧设定，发现 1 个冲突",
            "changes": [
                {
                    "target_type": "setting_card",
                    "operation": "create",
                    "after_snapshot": {
                        "doc_type": "setting",
                        "title": "修炼体系总览",
                        "content": "炼气、筑基、金丹。",
                    },
                },
                {
                    "target_type": "setting_card",
                    "operation": "archive",
                    "target_id": "doc-current",
                    "before_snapshot": {"title": "旧修炼体系"},
                },
                {
                    "target_type": "conflict",
                    "operation": "resolve",
                    "after_snapshot": {"title": "境界层数冲突", "options": ["九层", "十二层"]},
                    "conflict_hints": [{"reason": "炼气层数冲突"}],
                },
            ],
        }


async def test_consolidation_snapshots_effective_docs_and_selected_pending(async_session):
    doc_repo = DocumentRepository(async_session)
    await doc_repo.create("doc-current", "novel-c", "setting", "旧修炼体系", "炼气九层", version=1)
    await doc_repo.create("doc-old-version", "novel-c", "setting", "旧修炼体系", "炼气八层", version=0)
    async_session.add(Entity(id="entity-active", novel_id="novel-c", type="character", name="陆照"))
    async_session.add(Entity(id="entity-archived", novel_id="novel-c", type="character", name="旧陆照", archived_at=datetime.utcnow()))
    async_session.add(EntityRelationship(source_id="entity-active", target_id="entity-active", relation_type="自我", novel_id="novel-c"))
    pending_repo = PendingExtractionRepository(async_session)
    await pending_repo.create(
        "pending-selected",
        "novel-c",
        "setting",
        {"worldview": "选中的待审核资料"},
        source_filename="selected.md",
    )
    await pending_repo.create(
        "pending-unselected",
        "novel-c",
        "setting",
        {"worldview": "未选择资料"},
        source_filename="unselected.md",
    )
    await async_session.commit()

    service = SettingConsolidationService(async_session, agent=FakeConsolidationAgent())
    batch = await service.run_consolidation(
        novel_id="novel-c",
        selected_pending_ids=["pending-selected"],
        job_id="job-setting-1",
    )

    assert batch.source_type == "consolidation"
    assert batch.job_id == "job-setting-1"
    assert batch.status == "pending"
    assert batch.input_snapshot["documents"][0]["id"] == "doc-current"
    assert batch.input_snapshot["selected_pending"][0]["id"] == "pending-selected"
    assert "pending-unselected" not in str(batch.input_snapshot)
```

- [ ] **Step 2: Run the service test and confirm import failure**

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_setting_consolidation_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.services.setting_consolidation_service'`.

- [ ] **Step 3: Add the agent output contract**

Create `src/novel_dev/agents/setting_consolidation_agent.py`:

```python
from typing import Any

from pydantic import BaseModel, Field

from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage


class ConsolidationChange(BaseModel):
    target_type: str
    operation: str
    target_id: str | None = None
    before_snapshot: dict[str, Any] | None = None
    after_snapshot: dict[str, Any] | None = None
    conflict_hints: list[dict[str, Any]] = Field(default_factory=list)


class ConsolidationResult(BaseModel):
    summary: str
    changes: list[ConsolidationChange] = Field(default_factory=list)


class SettingConsolidationAgent:
    async def consolidate(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "你是小说设定整合助手。请只根据输入快照整合设定。"
            "不要直接裁决冲突；冲突必须输出 target_type=conflict, operation=resolve。"
            "旧内容被新整合内容吸收时，输出 archive 变更，不要输出 delete。"
            "返回 JSON: {summary: string, changes: array}。"
        )
        driver = llm_factory.get_driver()
        response = await driver.chat(
            [
                ChatMessage(role="system", content=prompt),
                ChatMessage(role="user", content=str(snapshot)),
            ],
            temperature=0.45,
            response_format={"type": "json_object"},
        )
        parsed = ConsolidationResult.model_validate_json(response.content)
        return parsed.model_dump()
```

- [ ] **Step 4: Add the consolidation service**

Create `src/novel_dev/services/setting_consolidation_service.py`:

```python
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.agents.setting_consolidation_agent import SettingConsolidationAgent
from novel_dev.db.models import EntityRelationship
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.pending_extraction_repo import PendingExtractionRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.services.log_service import log_service


class SettingConsolidationService:
    def __init__(self, session: AsyncSession, agent: SettingConsolidationAgent | None = None):
        self.session = session
        self.agent = agent or SettingConsolidationAgent()
        self.doc_repo = DocumentRepository(session)
        self.pending_repo = PendingExtractionRepository(session)
        self.setting_repo = SettingWorkbenchRepository(session)
        self.entity_repo = EntityRepository(session)
        self.relationship_repo = RelationshipRepository(session)

    async def build_input_snapshot(self, novel_id: str, selected_pending_ids: list[str]) -> dict[str, Any]:
        docs = []
        for doc_type in ("worldview", "setting", "synopsis", "concept"):
            for doc in await self.doc_repo.get_current_by_type(novel_id, doc_type):
                if getattr(doc, "archived_at", None) is None:
                    docs.append({
                        "id": doc.id,
                        "doc_type": doc.doc_type,
                        "title": doc.title,
                        "content": doc.content,
                        "version": doc.version,
                    })

        selected_pending = []
        for pending_id in selected_pending_ids:
            pending = await self.pending_repo.get_by_id(pending_id)
            if pending is None or pending.novel_id != novel_id:
                raise ValueError(f"待审核记录不存在或不属于当前小说: {pending_id}")
            if pending.status != "pending":
                raise ValueError(f"只能选择 pending 状态的审核记录: {pending_id}")
            selected_pending.append({
                "id": pending.id,
                "source_filename": pending.source_filename,
                "extraction_type": pending.extraction_type,
                "raw_result": pending.raw_result,
                "proposed_entities": pending.proposed_entities or [],
                "diff_result": pending.diff_result or {},
            })

        entities = []
        for entity in await self.entity_repo.list_by_novel(novel_id):
            if getattr(entity, "archived_at", None) is None:
                entities.append({
                    "id": entity.id,
                    "type": entity.type,
                    "name": entity.name,
                    "current_version": entity.current_version,
                    "system_category": entity.system_category,
                    "manual_category": entity.manual_category,
                    "search_document": entity.search_document,
                })

        relationship_result = await self.session.execute(
            select(EntityRelationship).where(
                EntityRelationship.novel_id == novel_id,
                EntityRelationship.is_active == True,
            )
        )
        relationships = []
        for relationship in relationship_result.scalars().all():
            if getattr(relationship, "archived_at", None) is None:
                relationships.append({
                    "id": relationship.id,
                    "source_id": relationship.source_id,
                    "target_id": relationship.target_id,
                    "relation_type": relationship.relation_type,
                    "meta": relationship.meta or {},
                })

        return {
            "novel_id": novel_id,
            "created_at": datetime.utcnow().isoformat(),
            "documents": docs,
            "entities": entities,
            "relationships": relationships,
            "selected_pending": selected_pending,
        }

    async def run_consolidation(
        self,
        *,
        novel_id: str,
        selected_pending_ids: list[str],
        job_id: str | None = None,
        input_snapshot: dict[str, Any] | None = None,
    ):
        snapshot = input_snapshot or await self.build_input_snapshot(novel_id, selected_pending_ids)
        log_service.add_log(
            novel_id,
            "SettingConsolidationService",
            "设定整合开始",
            metadata={
                "document_count": len(snapshot.get("documents", [])),
                "selected_pending_count": len(snapshot.get("selected_pending", [])),
            },
        )
        result = await self.agent.consolidate(snapshot)
        batch = await self.setting_repo.create_review_batch(
            novel_id=novel_id,
            source_type="consolidation",
            summary=result.get("summary") or "",
            input_snapshot=snapshot,
            job_id=job_id,
        )
        for item in result.get("changes") or []:
            await self.setting_repo.add_review_change(
                batch_id=batch.id,
                target_type=item["target_type"],
                operation=item["operation"],
                target_id=item.get("target_id"),
                before_snapshot=item.get("before_snapshot"),
                after_snapshot=item.get("after_snapshot"),
                conflict_hints=item.get("conflict_hints") or [],
            )
        log_service.add_log(
            novel_id,
            "SettingConsolidationService",
            f"设定整合生成审核记录：{batch.summary}",
            metadata={"batch_id": batch.id, "job_id": job_id},
        )
        return batch
```

- [ ] **Step 5: Run the service test**

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_setting_consolidation_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the service and agent**

```bash
git add src/novel_dev/agents/setting_consolidation_agent.py src/novel_dev/services/setting_consolidation_service.py tests/test_services/test_setting_consolidation_service.py
git commit -m "Add setting consolidation service"
```

## Task 4: Background Job And API Routes

**Files:**
- Modify: `src/novel_dev/services/generation_job_service.py`
- Modify: `src/novel_dev/api/routes.py`
- Test: `tests/test_api/test_setting_consolidation_routes.py`

- [ ] **Step 1: Add API tests for starting and reading consolidation**

Create `tests/test_api/test_setting_consolidation_routes.py`:

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.repositories.generation_job_repo import GenerationJobRepository


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
async def test_start_setting_consolidation_creates_job(test_client, async_session, monkeypatch):
    scheduled = []
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", scheduled.append)

    async with test_client as client:
        response = await client.post(
            "/api/novels/novel-api/settings/consolidations",
            json={"selected_pending_ids": []},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert scheduled == [payload["job_id"]]

    job = await GenerationJobRepository(async_session).get_by_id(payload["job_id"])
    assert job.job_type == "setting_consolidation"
    assert job.request_payload == {"selected_pending_ids": []}
```

- [ ] **Step 2: Run the API test and confirm missing route failure**

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_setting_consolidation_routes.py -q
```

Expected: FAIL with HTTP `404`.

- [ ] **Step 3: Route setting consolidation jobs**

Modify `src/novel_dev/services/generation_job_service.py`.

Add the constant:

```python
SETTING_CONSOLIDATION_JOB = "setting_consolidation"
```

Add the import:

```python
from novel_dev.services.setting_consolidation_service import SettingConsolidationService
```

Change the supported job check:

```python
        if job_type not in {CHAPTER_AUTO_RUN_JOB, CHAPTER_REWRITE_JOB, SETTING_CONSOLIDATION_JOB}:
```

Add this branch inside the `try` block:

```python
            elif job_type == SETTING_CONSOLIDATION_JOB:
                service = SettingConsolidationService(session)
                await repo.touch_heartbeat(job_id)
                await session.commit()
                batch = await service.run_consolidation(
                    novel_id=novel_id,
                    selected_pending_ids=request.get("selected_pending_ids", []),
                    job_id=job.id,
                    input_snapshot=request.get("input_snapshot"),
                )
                result = {
                    "batch_id": batch.id,
                    "status": "ready_for_review",
                    "summary": batch.summary,
                }
```

Change the success handling to support dict results:

```python
        result_payload = result if isinstance(result, dict) else result.model_dump()
        await repo.touch_heartbeat(job_id)
        if not isinstance(result, dict) and getattr(result, "stopped_reason", None) == "flow_cancelled":
            await repo.mark_cancelled(job_id, result_payload)
        else:
            await repo.mark_succeeded(job_id, result_payload)
        await session.commit()
```

- [ ] **Step 4: Add serializers and start/list/detail routes**

Modify `src/novel_dev/api/routes.py`.

Import schemas:

```python
from novel_dev.schemas.setting_workbench import (
    SettingConsolidationStartRequest,
    SettingConsolidationStartResponse,
    SettingGenerationSessionCreateRequest,
    SettingGenerationSessionDetailResponse,
    SettingGenerationSessionListResponse,
    SettingGenerationSessionResponse,
    SettingReviewBatchDetailResponse,
    SettingReviewBatchListResponse,
)
```

Import the job constant:

```python
from novel_dev.services.generation_job_service import (
    CHAPTER_AUTO_RUN_JOB,
    CHAPTER_REWRITE_JOB,
    SETTING_CONSOLIDATION_JOB,
    schedule_generation_job,
)
```

Add serializers near the existing setting serializers:

```python
def _serialize_setting_review_batch(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "novel_id": item.novel_id,
        "source_type": item.source_type,
        "source_file": item.source_file,
        "source_session_id": item.source_session_id,
        "job_id": item.job_id,
        "status": item.status,
        "summary": item.summary or "",
        "input_snapshot": item.input_snapshot or {},
        "error_message": item.error_message,
        "created_at": _isoformat(item.created_at),
        "updated_at": _isoformat(item.updated_at),
    }


def _serialize_setting_review_change(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "batch_id": item.batch_id,
        "target_type": item.target_type,
        "operation": item.operation,
        "target_id": item.target_id,
        "status": item.status,
        "before_snapshot": item.before_snapshot,
        "after_snapshot": item.after_snapshot,
        "conflict_hints": item.conflict_hints or [],
        "error_message": item.error_message,
        "created_at": _isoformat(item.created_at),
        "updated_at": _isoformat(item.updated_at),
    }
```

Add routes after the existing setting session routes:

```python
@router.post(
    "/api/novels/{novel_id}/settings/consolidations",
    response_model=SettingConsolidationStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_setting_consolidation(
    novel_id: str,
    req: SettingConsolidationStartRequest,
    session: AsyncSession = Depends(get_session),
):
    repo = GenerationJobRepository(session)
    active = await repo.get_active(novel_id, SETTING_CONSOLIDATION_JOB)
    if active:
        return {"job_id": active.id, "status": active.status}
    job = await repo.create(
        novel_id,
        SETTING_CONSOLIDATION_JOB,
        {"selected_pending_ids": req.selected_pending_ids},
    )
    await session.commit()
    schedule_generation_job(job.id)
    return {"job_id": job.id, "status": job.status}


@router.get(
    "/api/novels/{novel_id}/settings/review_batches",
    response_model=SettingReviewBatchListResponse,
)
async def list_setting_review_batches(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = SettingWorkbenchRepository(session)
    items = await repo.list_review_batches(novel_id)
    return {"items": [_serialize_setting_review_batch(item) for item in items]}


@router.get(
    "/api/novels/{novel_id}/settings/review_batches/{batch_id}",
    response_model=SettingReviewBatchDetailResponse,
)
async def get_setting_review_batch(
    novel_id: str,
    batch_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = SettingWorkbenchRepository(session)
    batch = await repo.get_review_batch(batch_id)
    if batch is None or batch.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Setting review batch not found")
    changes = await repo.list_review_changes(batch.id)
    return {
        "batch": _serialize_setting_review_batch(batch),
        "changes": [_serialize_setting_review_change(change) for change in changes],
    }
```

- [ ] **Step 5: Run API tests**

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_setting_consolidation_routes.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit job and route work**

```bash
git add src/novel_dev/services/generation_job_service.py src/novel_dev/api/routes.py tests/test_api/test_setting_consolidation_routes.py
git commit -m "Expose setting consolidation jobs"
```

## Task 5: Approval, Conflict Blocking, And Archive Application

**Files:**
- Modify: `src/novel_dev/services/setting_consolidation_service.py`
- Modify: `src/novel_dev/repositories/document_repo.py`
- Modify: `src/novel_dev/repositories/entity_repo.py`
- Modify: `src/novel_dev/repositories/relationship_repo.py`
- Modify: `src/novel_dev/api/routes.py`
- Test: `tests/test_services/test_setting_consolidation_service.py`
- Test: `tests/test_api/test_setting_consolidation_routes.py`

- [ ] **Step 1: Add failing tests for unresolved conflict blocking and archive application**

Append to `tests/test_services/test_setting_consolidation_service.py`:

```python
async def test_approve_all_blocks_unresolved_conflict(async_session):
    service = SettingConsolidationService(async_session, agent=FakeConsolidationAgent())
    batch = await service.run_consolidation(novel_id="novel-c", selected_pending_ids=[], job_id="job-conflict")

    with pytest.raises(ValueError, match="存在未解决冲突"):
        await service.approve_review_batch(batch.id, approve_all=True)


async def test_approve_archive_hides_old_document(async_session):
    doc_repo = DocumentRepository(async_session)
    await doc_repo.create("doc-archive", "novel-c", "setting", "旧势力设定", "旧内容", version=1)
    service = SettingConsolidationService(async_session, agent=FakeConsolidationAgent())
    batch = await service.run_consolidation(
        novel_id="novel-c",
        selected_pending_ids=[],
        job_id="job-archive",
        input_snapshot={
            "novel_id": "novel-c",
            "documents": [{"id": "doc-archive", "doc_type": "setting", "title": "旧势力设定", "content": "旧内容"}],
            "selected_pending": [],
        },
    )
    changes = await service.setting_repo.list_review_changes(batch.id)
    archive_change = next(change for change in changes if change.operation == "archive")
    archive_change.target_id = "doc-archive"
    await async_session.commit()

    await service.approve_review_batch(batch.id, change_ids=[archive_change.id])
    archived = await doc_repo.get_by_id("doc-archive")

    assert archived.archived_at is not None
    assert archived.archived_by_consolidation_batch_id == batch.id
    assert archived.archived_by_consolidation_change_id == archive_change.id
```

- [ ] **Step 2: Run service tests and confirm missing approval API failure**

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_setting_consolidation_service.py -q
```

Expected: FAIL with `AttributeError: 'SettingConsolidationService' object has no attribute 'approve_review_batch'`.

- [ ] **Step 3: Add archive helper methods to repositories**

Add to `DocumentRepository`:

```python
    async def archive_for_consolidation(
        self,
        doc_id: str,
        *,
        batch_id: str,
        change_id: str,
        reason: str = "setting_consolidation",
    ) -> Optional[NovelDocument]:
        doc = await self.get_by_id(doc_id)
        if doc is None:
            return None
        doc.archived_at = datetime.utcnow()
        doc.archive_reason = reason
        doc.archived_by_consolidation_batch_id = batch_id
        doc.archived_by_consolidation_change_id = change_id
        await self.session.flush()
        return doc
```

Add `from datetime import datetime` to `document_repo.py`.

Add this helper to `EntityRepository`:

```python
    async def archive_for_consolidation(
        self,
        entity_id: str,
        *,
        batch_id: str,
        change_id: str,
        reason: str = "setting_consolidation",
    ) -> Optional[Entity]:
        entity = await self.get_by_id(entity_id)
        if entity is None:
            return None
        entity.archived_at = datetime.utcnow()
        entity.archive_reason = reason
        entity.archived_by_consolidation_batch_id = batch_id
        entity.archived_by_consolidation_change_id = change_id
        await self.session.flush()
        return entity
```

Add this helper to `RelationshipRepository`:

```python
    async def get_by_id(self, relationship_id: str) -> Optional[EntityRelationship]:
        result = await self.session.execute(
            select(EntityRelationship).where(EntityRelationship.id == int(relationship_id))
        )
        return result.scalar_one_or_none()

    async def archive_for_consolidation(
        self,
        relationship_id: str,
        *,
        batch_id: str,
        change_id: str,
        reason: str = "setting_consolidation",
    ) -> Optional[EntityRelationship]:
        relationship = await self.get_by_id(relationship_id)
        if relationship is None:
            return None
        relationship.archived_at = datetime.utcnow()
        relationship.archive_reason = reason
        relationship.archived_by_consolidation_batch_id = batch_id
        relationship.archived_by_consolidation_change_id = change_id
        await self.session.flush()
        return relationship
```

Add `from datetime import datetime` to `entity_repo.py` and `relationship_repo.py`.

- [ ] **Step 4: Add approval methods to the consolidation service**

Add to `SettingConsolidationService`:

```python
    async def approve_review_batch(
        self,
        batch_id: str,
        *,
        change_ids: list[str] | None = None,
        approve_all: bool = False,
    ):
        batch = await self.setting_repo.get_review_batch(batch_id)
        if batch is None:
            raise ValueError("审核记录不存在")
        changes = await self.setting_repo.list_review_changes(batch.id)
        pending_changes = [change for change in changes if change.status == "pending"]
        unresolved_conflicts = [
            change for change in pending_changes
            if change.target_type == "conflict"
        ]
        if approve_all and unresolved_conflicts:
            raise ValueError("存在未解决冲突，不能整体通过")

        selected_ids = set(change_ids or [])
        selected = pending_changes if approve_all else [change for change in pending_changes if change.id in selected_ids]
        for change in selected:
            await self._apply_change(batch, change)

        latest = await self.setting_repo.list_review_changes(batch.id)
        pending_count = sum(1 for change in latest if change.status == "pending")
        failed_count = sum(1 for change in latest if change.status == "failed")
        if pending_count == 0 and failed_count == 0:
            await self.setting_repo.update_batch_status(batch.id, "approved")
        elif any(change.status in {"approved", "edited_approved"} for change in latest):
            await self.setting_repo.update_batch_status(batch.id, "partially_approved")
        return await self.setting_repo.get_review_batch(batch.id)

    async def _apply_change(self, batch, change) -> None:
        try:
            if change.target_type == "conflict":
                raise ValueError("冲突项必须先提交解决结果")
            if change.operation == "archive":
                await self._archive_target(batch, change)
            elif change.target_type == "setting_card" and change.operation == "create":
                snapshot = change.after_snapshot or {}
                doc = await self.doc_repo.create(
                    f"setting_{change.id}",
                    batch.novel_id,
                    snapshot.get("doc_type") or "setting",
                    snapshot["title"],
                    snapshot.get("content") or "",
                    version=1,
                )
                doc.source_type = "consolidation"
                doc.source_review_batch_id = batch.id
                doc.source_review_change_id = change.id
            else:
                raise ValueError(f"暂不支持的设定审核变更: {change.target_type}/{change.operation}")
        except Exception as exc:
            await self.setting_repo.mark_change_status(change.id, "failed", error_message=str(exc))
            return
        await self.setting_repo.mark_change_status(change.id, "approved")

    async def _archive_target(self, batch, change) -> None:
        if change.target_type == "setting_card":
            archived = await self.doc_repo.archive_for_consolidation(
                change.target_id,
                batch_id=batch.id,
                change_id=change.id,
            )
        elif change.target_type == "entity":
            archived = await self.entity_repo.archive_for_consolidation(
                change.target_id,
                batch_id=batch.id,
                change_id=change.id,
            )
        elif change.target_type == "relationship":
            archived = await self.relationship_repo.archive_for_consolidation(
                change.target_id,
                batch_id=batch.id,
                change_id=change.id,
            )
        else:
            raise ValueError(f"不支持归档目标类型: {change.target_type}")
        if archived is None:
            raise ValueError(f"归档目标不存在: {change.target_id}")
```

- [ ] **Step 5: Add approval route**

In `src/novel_dev/api/routes.py`, add:

```python
@router.post(
    "/api/novels/{novel_id}/settings/review_batches/{batch_id}/approve",
    response_model=SettingReviewBatchDetailResponse,
)
async def approve_setting_review_batch(
    novel_id: str,
    batch_id: str,
    req: SettingReviewApproveRequest,
    session: AsyncSession = Depends(get_session),
):
    service = SettingConsolidationService(session)
    batch = await service.setting_repo.get_review_batch(batch_id)
    if batch is None or batch.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Setting review batch not found")
    try:
        await service.approve_review_batch(
            batch_id,
            change_ids=req.change_ids,
            approve_all=req.approve_all,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    updated = await service.setting_repo.get_review_batch(batch_id)
    changes = await service.setting_repo.list_review_changes(batch_id)
    return {
        "batch": _serialize_setting_review_batch(updated),
        "changes": [_serialize_setting_review_change(change) for change in changes],
    }
```

- [ ] **Step 6: Run targeted backend tests**

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_setting_consolidation_service.py tests/test_api/test_setting_consolidation_routes.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit approval and archive behavior**

```bash
git add src/novel_dev/services/setting_consolidation_service.py src/novel_dev/repositories/document_repo.py src/novel_dev/repositories/entity_repo.py src/novel_dev/repositories/relationship_repo.py src/novel_dev/api/routes.py tests/test_services/test_setting_consolidation_service.py tests/test_api/test_setting_consolidation_routes.py
git commit -m "Apply setting consolidation review changes"
```

## Task 6: Frontend API, Store, And Setting Workbench UI

**Files:**
- Modify: `src/novel_dev/web/src/api.js`
- Modify: `src/novel_dev/web/src/stores/novel.js`
- Modify: `src/novel_dev/web/src/views/SettingWorkbench.vue`
- Test: `src/novel_dev/web/src/api.test.js`
- Test: `src/novel_dev/web/src/stores/novel.test.js`
- Test: `src/novel_dev/web/src/views/SettingWorkbench.test.js`

- [ ] **Step 1: Add frontend tests for consolidation actions**

Add API expectations to `src/novel_dev/web/src/api.test.js`:

```javascript
it('starts setting consolidation', async () => {
  mock.onPost('/novels/novel-1/settings/consolidations', { selected_pending_ids: ['p1'] }).reply(202, { job_id: 'job-1', status: 'queued' })
  await expect(api.startSettingConsolidation('novel-1', ['p1'])).resolves.toEqual({ job_id: 'job-1', status: 'queued' })
})

it('loads setting review batch detail', async () => {
  mock.onGet('/novels/novel-1/settings/review_batches/batch-1').reply(200, { batch: { id: 'batch-1' }, changes: [] })
  await expect(api.getSettingReviewBatch('novel-1', 'batch-1')).resolves.toEqual({ batch: { id: 'batch-1' }, changes: [] })
})
```

Add store expectations to `src/novel_dev/web/src/stores/novel.test.js`:

```javascript
it('starts setting consolidation and stores the active job', async () => {
  const store = useNovelStore()
  store.novelId = 'novel-1'
  vi.mocked(api.startSettingConsolidation).mockResolvedValue({ job_id: 'job-1', status: 'queued' })

  await store.startSettingConsolidation(['p1'])

  expect(api.startSettingConsolidation).toHaveBeenCalledWith('novel-1', ['p1'])
  expect(store.settingWorkbench.consolidationJob).toEqual({ job_id: 'job-1', status: 'queued' })
})
```

Add UI expectation to `src/novel_dev/web/src/views/SettingWorkbench.test.js`:

```javascript
it('opens consolidation dialog and submits selected pending records', async () => {
  const store = useNovelStore()
  store.novelId = 'novel-1'
  store.pendingDocs = [{ id: 'p1', source_filename: 'setting.md', status: 'pending', diff_result: { summary: '新增设定' } }]
  store.settingWorkbench.sessions = []
  store.settingWorkbench.reviewBatches = []
  store.startSettingConsolidation = vi.fn().mockResolvedValue({ job_id: 'job-1', status: 'queued' })

  const wrapper = mount(SettingWorkbench, { global: { plugins: [pinia] } })
  await wrapper.get('[data-testid="setting-consolidation-open"]').trigger('click')
  await wrapper.get('[data-testid="setting-consolidation-pending-p1"]').setValue(true)
  await wrapper.get('[data-testid="setting-consolidation-submit"]').trigger('click')

  expect(store.startSettingConsolidation).toHaveBeenCalledWith(['p1'])
})
```

- [ ] **Step 2: Add API calls**

Modify `src/novel_dev/web/src/api.js`:

```javascript
export const startSettingConsolidation = (id, selectedPendingIds = []) =>
  api.post(`/novels/${id}/settings/consolidations`, { selected_pending_ids: selectedPendingIds }).then(r => r.data)
export const getSettingReviewBatches = (id) =>
  api.get(`/novels/${id}/settings/review_batches`).then(r => r.data)
export const getSettingReviewBatch = (id, batchId) =>
  api.get(`/novels/${id}/settings/review_batches/${encodeURIComponent(batchId)}`).then(r => r.data)
export const approveSettingReviewBatch = (id, batchId, payload) =>
  api.post(`/novels/${id}/settings/review_batches/${encodeURIComponent(batchId)}/approve`, payload).then(r => r.data)
```

- [ ] **Step 3: Extend Pinia state and actions**

Modify `createSettingWorkbenchState` in `src/novel_dev/web/src/stores/novel.js`:

```javascript
const createSettingWorkbenchState = () => ({
  state: 'idle',
  error: '',
  creatingSession: false,
  sessions: [],
  selectedSessionId: '',
  selectedSession: null,
  selectedMessages: [],
  consolidationSubmitting: false,
  consolidationJob: null,
  reviewBatches: [],
  selectedReviewBatch: null,
  selectedReviewChanges: [],
})
```

Add actions:

```javascript
    async startSettingConsolidation(selectedPendingIds = []) {
      if (!this.novelId) return null
      if (this.settingWorkbench.consolidationSubmitting) return null
      this.settingWorkbench.consolidationSubmitting = true
      this.settingWorkbench.error = ''
      try {
        const job = await api.startSettingConsolidation(this.novelId, selectedPendingIds)
        this.settingWorkbench.consolidationJob = job
        return job
      } catch (error) {
        this.settingWorkbench.error = error?.message || '请求失败'
        throw error
      } finally {
        this.settingWorkbench.consolidationSubmitting = false
      }
    },

    async fetchSettingReviewBatches() {
      if (!this.novelId) return
      const payload = await api.getSettingReviewBatches(this.novelId)
      this.settingWorkbench.reviewBatches = payload?.items || []
    },

    async loadSettingReviewBatch(batchId) {
      if (!this.novelId || !batchId) return null
      const payload = await api.getSettingReviewBatch(this.novelId, batchId)
      this.settingWorkbench.selectedReviewBatch = payload?.batch || null
      this.settingWorkbench.selectedReviewChanges = payload?.changes || []
      return payload
    },
```

- [ ] **Step 4: Add the setting workbench UI**

Modify `src/novel_dev/web/src/views/SettingWorkbench.vue`.

Add the consolidation button in the header actions:

```vue
<button
  type="button"
  class="setting-primary"
  data-testid="setting-consolidation-open"
  @click="showConsolidationDialog = true"
>
  一键整合设定
</button>
```

Add dialog markup inside the `v-else` template:

```vue
<el-dialog v-model="showConsolidationDialog" title="一键整合设定" width="640px">
  <div class="space-y-4 text-sm text-gray-600 dark:text-gray-300">
    <p>当前已审核生效设定会自动纳入。待审核记录只有勾选后才参与整合。</p>
    <div v-if="!pendingSelectable.length" class="rounded-lg border border-dashed p-4">暂无可选待审核记录。</div>
    <label
      v-for="item in pendingSelectable"
      :key="item.id"
      class="flex items-start gap-3 rounded-lg border p-3"
    >
      <input
        v-model="selectedPendingIds"
        type="checkbox"
        :value="item.id"
        :data-testid="`setting-consolidation-pending-${item.id}`"
      />
      <span>
        <strong>{{ item.source_filename || item.id }}</strong>
        <small class="block text-gray-500">{{ item.diff_result?.summary || item.extraction_type }}</small>
      </span>
    </label>
  </div>
  <template #footer>
    <button type="button" class="setting-secondary" @click="showConsolidationDialog = false">取消</button>
    <button
      type="button"
      class="setting-primary"
      data-testid="setting-consolidation-submit"
      :disabled="store.settingWorkbench.consolidationSubmitting"
      @click="submitConsolidation"
    >
      {{ store.settingWorkbench.consolidationSubmitting ? '提交中...' : '生成整合审核记录' }}
    </button>
  </template>
</el-dialog>
```

Add review batch list:

```vue
<section class="surface-card p-4">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-gray-900 dark:text-gray-100">审核记录</h2>
    <button type="button" class="setting-secondary" @click="store.fetchSettingReviewBatches()">刷新</button>
  </div>
  <div v-if="!store.settingWorkbench.reviewBatches.length" class="mt-4 text-sm text-gray-500">暂无审核记录。</div>
  <button
    v-for="batch in store.settingWorkbench.reviewBatches"
    :key="batch.id"
    type="button"
    class="setting-session-item mt-2"
    @click="store.loadSettingReviewBatch(batch.id)"
  >
    <span>{{ batch.summary || '未命名审核记录' }}</span>
    <small>{{ batch.source_type === 'consolidation' ? '整合' : batch.source_type }} · {{ batch.status }}</small>
  </button>
</section>
```

Add script state and helpers:

```javascript
const showConsolidationDialog = ref(false)
const selectedPendingIds = ref([])
const pendingSelectable = computed(() => (store.pendingDocs || []).filter((item) => item.status === 'pending'))

async function submitConsolidation() {
  await store.startSettingConsolidation([...selectedPendingIds.value])
  selectedPendingIds.value = []
  showConsolidationDialog.value = false
}
```

- [ ] **Step 5: Run frontend tests**

```bash
cd src/novel_dev/web
npm test -- --run src/api.test.js src/stores/novel.test.js src/views/SettingWorkbench.test.js
```

Expected: PASS.

- [ ] **Step 6: Commit frontend work**

```bash
git add src/novel_dev/web/src/api.js src/novel_dev/web/src/stores/novel.js src/novel_dev/web/src/views/SettingWorkbench.vue src/novel_dev/web/src/api.test.js src/novel_dev/web/src/stores/novel.test.js src/novel_dev/web/src/views/SettingWorkbench.test.js
git commit -m "Add setting consolidation frontend"
```

## Task 7: Archive Filters And Integration Verification

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Modify: `src/novel_dev/web/src/views/Documents.vue`
- Modify: `src/novel_dev/web/src/views/Entities.vue`
- Modify: `src/novel_dev/web/src/components/EntityGraph.vue`
- Test: `tests/test_api/test_encyclopedia_routes.py`
- Test: `src/novel_dev/web/src/views/Documents.test.js`
- Test: `src/novel_dev/web/src/views/Entities.test.js`
- Test: `src/novel_dev/web/src/components/EntityGraph.test.js`

- [ ] **Step 1: Add tests that archived items are hidden by default**

In `tests/test_api/test_encyclopedia_routes.py`, add a route test that creates an entity with `archived_at` set and confirms `/entities` omits it unless `include_archived=true` is passed:

```python
async def test_entities_hide_archived_by_default(test_client, async_session):
    entity = Entity(id="archived-entity", novel_id="novel-e", type="character", name="旧角色")
    entity.archived_at = datetime.utcnow()
    async_session.add(entity)
    async_session.add(Entity(id="active-entity", novel_id="novel-e", type="character", name="新角色"))
    await async_session.commit()

    async with test_client as client:
        response = await client.get("/api/novels/novel-e/entities")
        archived_response = await client.get("/api/novels/novel-e/entities?include_archived=true")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["active-entity"]
    assert {item["id"] for item in archived_response.json()["items"]} == {"active-entity", "archived-entity"}
```

- [ ] **Step 2: Update API filters**

Modify entity and relationship list routes in `src/novel_dev/api/routes.py` to accept:

```python
include_archived: bool = False
```

When querying `Entity` or `EntityRelationship`, add:

```python
if not include_archived:
    stmt = stmt.where(Entity.archived_at.is_(None))
```

and:

```python
if not include_archived:
    stmt = stmt.where(EntityRelationship.archived_at.is_(None))
```

Add archive fields to serializers:

```python
"archived_at": _isoformat(item.archived_at),
"archive_reason": item.archive_reason,
"archived_by_consolidation_batch_id": item.archived_by_consolidation_batch_id,
"archived_by_consolidation_change_id": item.archived_by_consolidation_change_id,
```

- [ ] **Step 3: Update frontend archive filter**

In `Entities.vue`, add a toggle bound to `includeArchived` and pass it through store/API if the existing entity fetch path accepts params. If the store path does not accept params yet, add `api.getEntities(id, params = {})`:

```javascript
export const getEntities = (id, params = {}) => api.get(`/novels/${id}/entities`, { params }).then(r => r.data)
```

Use the label **已归档 / 已整合** in the filter control.

- [ ] **Step 4: Rename import-only review wording**

In `src/novel_dev/web/src/views/Documents.vue`, change the visible heading:

```vue
<h3 class="font-bold mb-3">审核记录</h3>
```

Keep row-level source file information unchanged.

- [ ] **Step 5: Run focused backend and frontend tests**

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_encyclopedia_routes.py tests/test_api/test_setting_consolidation_routes.py -q
cd src/novel_dev/web
npm test -- --run src/views/Documents.test.js src/views/Entities.test.js src/components/EntityGraph.test.js
```

Expected: PASS.

- [ ] **Step 6: Commit archive filters**

```bash
git add src/novel_dev/api/routes.py src/novel_dev/web/src/api.js src/novel_dev/web/src/views/Documents.vue src/novel_dev/web/src/views/Entities.vue src/novel_dev/web/src/components/EntityGraph.vue tests/test_api/test_encyclopedia_routes.py src/novel_dev/web/src/views/Documents.test.js src/novel_dev/web/src/views/Entities.test.js src/novel_dev/web/src/components/EntityGraph.test.js
git commit -m "Hide archived setting data by default"
```

## Task 8: Final Verification

**Files:**
- Verify all changed backend and frontend files.

- [ ] **Step 1: Run migrations head check**

```bash
alembic heads
```

Expected: one current head, including `20260504_setting_consolidation`.

- [ ] **Step 2: Run backend tests**

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_setting_workbench_repo.py tests/test_services/test_setting_consolidation_service.py tests/test_api/test_setting_consolidation_routes.py tests/test_api/test_encyclopedia_routes.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend tests**

```bash
cd src/novel_dev/web
npm test -- --run src/api.test.js src/stores/novel.test.js src/views/SettingWorkbench.test.js src/views/Documents.test.js src/views/Entities.test.js src/components/EntityGraph.test.js
```

Expected: PASS.

- [ ] **Step 4: Run full project smoke tests if local services are available**

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_setting_workbench_routes.py tests/test_api/test_setting_consolidation_routes.py -q
```

Expected: PASS.

- [ ] **Step 5: Confirm staged work is intentional**

```bash
git status --short
```

Expected: only intentional files are modified or untracked. Existing unrelated dirty files from before this plan should not be reverted.

- [ ] **Step 6: Commit final stabilization fixes if any were needed**

If Step 1 through Step 5 required small fixes, commit the planned integration files:

```bash
git add src/novel_dev/db/models.py migrations/versions/20260504_add_setting_consolidation_review.py src/novel_dev/schemas/setting_workbench.py src/novel_dev/repositories/setting_workbench_repo.py src/novel_dev/repositories/document_repo.py src/novel_dev/repositories/entity_repo.py src/novel_dev/repositories/relationship_repo.py src/novel_dev/agents/setting_consolidation_agent.py src/novel_dev/services/setting_consolidation_service.py src/novel_dev/services/generation_job_service.py src/novel_dev/api/routes.py src/novel_dev/services/novel_deletion_service.py src/novel_dev/web/src/api.js src/novel_dev/web/src/stores/novel.js src/novel_dev/web/src/views/SettingWorkbench.vue src/novel_dev/web/src/views/Documents.vue src/novel_dev/web/src/views/Entities.vue src/novel_dev/web/src/components/EntityGraph.vue tests/test_repositories/test_setting_workbench_repo.py tests/test_services/test_setting_consolidation_service.py tests/test_api/test_setting_consolidation_routes.py tests/test_api/test_encyclopedia_routes.py src/novel_dev/web/src/api.test.js src/novel_dev/web/src/stores/novel.test.js src/novel_dev/web/src/views/SettingWorkbench.test.js src/novel_dev/web/src/views/Documents.test.js src/novel_dev/web/src/views/Entities.test.js src/novel_dev/web/src/components/EntityGraph.test.js
git commit -m "Stabilize setting consolidation integration"
```

If no fixes were needed, do not create an empty commit.
