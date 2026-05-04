# Setting Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-class setting workbench where users can import existing setting files or use persistent AI sessions to generate and optimize reviewed setting batches.

**Architecture:** Add explicit persistence for AI setting sessions, review batches, and review changes. Keep formal setting cards, entities, and relationships protected behind review approval, with AI source fields on approved outputs for backlinks into the source session.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic, Pydantic v2, existing LLM helper stack, Vue 3, Pinia, Element Plus, Vitest, pytest.

---

## File Structure

- Create `src/novel_dev/schemas/setting_workbench.py`: API payloads for sessions, messages, review batches, review changes, and generation requests.
- Create `src/novel_dev/repositories/setting_workbench_repo.py`: focused async data access for sessions, messages, batches, and changes.
- Create `src/novel_dev/services/setting_workbench_service.py`: orchestration for session creation, clarification, generation, review approval, and source-object optimization.
- Create `src/novel_dev/agents/setting_workbench_agent.py`: LLM schemas and prompt builders for clarification and batch generation.
- Modify `src/novel_dev/db/models.py`: add session/message/batch/change models and AI source columns on `NovelDocument`, `Entity`, and `EntityRelationship`.
- Create Alembic migration under `migrations/versions/`.
- Modify `src/novel_dev/api/routes.py`: add setting workbench routes and extend serializers for AI source fields.
- Modify `src/novel_dev/services/extraction_service.py`: keep existing pending import path working while setting-card application moves into the new review application path.
- Modify `src/novel_dev/services/novel_deletion_service.py`: delete workbench sessions, messages, batches, and changes when a novel is deleted.
- Create `src/novel_dev/web/src/views/SettingWorkbench.vue`: landing, AI session, and review list/detail UI.
- Modify `src/novel_dev/web/src/api.js`: add workbench API calls.
- Modify `src/novel_dev/web/src/router.js` and `src/novel_dev/web/src/App.vue`: add `/settings` route and sidebar entry.
- Modify `src/novel_dev/web/src/views/Documents.vue`: rename review surface to **审核记录** and reuse unified review data.
- Modify `src/novel_dev/web/src/views/Entities.vue`, `src/novel_dev/web/src/components/entities/EntityDetailPanel.vue`, and `src/novel_dev/web/src/components/EntityGraph.vue`: show clickable AI source backlinks where source fields exist.
- Add backend tests in `tests/test_repositories/test_setting_workbench_repo.py`, `tests/test_services/test_setting_workbench_service.py`, and `tests/test_api/test_setting_workbench_routes.py`.
- Add frontend tests in `src/novel_dev/web/src/views/SettingWorkbench.test.js`, `src/novel_dev/web/src/views/Documents.test.js`, `src/novel_dev/web/src/views/Entities.test.js`, and `src/novel_dev/web/src/components/EntityGraph.test.js`.

## Task 1: Persistence, Migration, Schemas, And Repository

**Files:**
- Modify: `src/novel_dev/db/models.py`
- Create: `migrations/versions/20260502_add_setting_workbench.py`
- Create: `src/novel_dev/schemas/setting_workbench.py`
- Create: `src/novel_dev/repositories/setting_workbench_repo.py`
- Test: `tests/test_repositories/test_setting_workbench_repo.py`

- [ ] **Step 1: Write repository tests first**

Create `tests/test_repositories/test_setting_workbench_repo.py`:

```python
import pytest

from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository

pytestmark = pytest.mark.asyncio


async def test_setting_workbench_repo_creates_session_and_messages(async_session):
    repo = SettingWorkbenchRepository(async_session)

    session = await repo.create_session(
        novel_id="novel-sw",
        title="修炼体系补全",
        target_categories=["功法", "体系设定"],
    )
    message = await repo.add_message(
        session_id=session.id,
        role="user",
        content="主角从废脉开始修炼",
        metadata={"round": 1},
    )

    await async_session.commit()

    sessions = await repo.list_sessions("novel-sw")
    messages = await repo.list_messages(session.id)

    assert sessions[0].id == session.id
    assert sessions[0].status == "clarifying"
    assert sessions[0].target_categories == ["功法", "体系设定"]
    assert messages[0].id == message.id
    assert messages[0].content == "主角从废脉开始修炼"


async def test_setting_workbench_repo_creates_review_batch_and_changes(async_session):
    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-sw",
        title="势力格局",
        target_categories=["势力"],
    )

    batch = await repo.create_review_batch(
        novel_id="novel-sw",
        source_type="ai_session",
        source_session_id=session.id,
        summary="新增 1 张设定卡片，1 个实体，1 个关系变更",
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"title": "势力格局", "content": "宗门互相制衡。"},
        source_session_id=session.id,
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="create",
        after_snapshot={"type": "faction", "name": "青云门", "state": {"description": "正道宗门"}},
        source_session_id=session.id,
    )
    await async_session.commit()

    batches = await repo.list_review_batches("novel-sw")
    changes = await repo.list_review_changes(batch.id)

    assert batches[0].id == batch.id
    assert batches[0].status == "pending"
    assert [change.target_type for change in changes] == ["setting_card", "entity"]
    assert all(change.status == "pending" for change in changes)
```

- [ ] **Step 2: Run repository tests and confirm missing module failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_setting_workbench_repo.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.repositories.setting_workbench_repo'`.

- [ ] **Step 3: Add ORM models and source fields**

Modify `src/novel_dev/db/models.py`.

Add source columns to `Entity`, `EntityRelationship`, and `NovelDocument`:

```python
    source_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_session_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_review_batch_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_review_change_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

Add new models after `PendingExtraction`:

```python
class SettingGenerationSession(Base):
    __tablename__ = "setting_generation_sessions"
    __table_args__ = (
        Index("ix_setting_generation_sessions_novel_status", "novel_id", "status"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="clarifying")
    target_categories: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    clarification_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conversation_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    focused_target: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


class SettingGenerationMessage(Base):
    __tablename__ = "setting_generation_messages"
    __table_args__ = (
        Index("ix_setting_generation_messages_session", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("setting_generation_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)


class SettingReviewBatch(Base):
    __tablename__ = "setting_review_batches"
    __table_args__ = (
        Index("ix_setting_review_batches_novel_status", "novel_id", "status"),
        Index("ix_setting_review_batches_session", "source_session_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_file: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_session_id: Mapped[Optional[str]] = mapped_column(ForeignKey("setting_generation_sessions.id"), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


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
```

- [ ] **Step 4: Add Alembic migration**

Create `migrations/versions/20260502_add_setting_workbench.py`:

```python
"""add setting workbench

Revision ID: 20260502_setting_workbench
Revises: 20260430_chapter_quality_gate
Create Date: 2026-05-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260502_setting_workbench"
down_revision = "20260430_chapter_quality_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setting_generation_sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="clarifying"),
        sa.Column("target_categories", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("clarification_round", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversation_summary", sa.Text(), nullable=True),
        sa.Column("focused_target", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
    )
    op.create_index("ix_setting_generation_sessions_novel_status", "setting_generation_sessions", ["novel_id", "status"])
    op.create_table(
        "setting_generation_messages",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("session_id", sa.Text(), sa.ForeignKey("setting_generation_sessions.id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
    )
    op.create_index("ix_setting_generation_messages_session", "setting_generation_messages", ["session_id", "created_at"])
    op.create_table(
        "setting_review_batches",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("source_session_id", sa.Text(), sa.ForeignKey("setting_generation_sessions.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
    )
    op.create_index("ix_setting_review_batches_novel_status", "setting_review_batches", ["novel_id", "status"])
    op.create_index("ix_setting_review_batches_session", "setting_review_batches", ["source_session_id"])
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
        op.add_column(table_name, sa.Column("source_type", sa.Text(), nullable=True))
        op.add_column(table_name, sa.Column("source_session_id", sa.Text(), nullable=True))
        op.add_column(table_name, sa.Column("source_review_batch_id", sa.Text(), nullable=True))
        op.add_column(table_name, sa.Column("source_review_change_id", sa.Text(), nullable=True))


def downgrade() -> None:
    for table_name in ("entity_relationships", "entities", "novel_documents"):
        op.drop_column(table_name, "source_review_change_id")
        op.drop_column(table_name, "source_review_batch_id")
        op.drop_column(table_name, "source_session_id")
        op.drop_column(table_name, "source_type")
    op.drop_index("ix_setting_review_changes_batch_status", table_name="setting_review_changes")
    op.drop_table("setting_review_changes")
    op.drop_index("ix_setting_review_batches_session", table_name="setting_review_batches")
    op.drop_index("ix_setting_review_batches_novel_status", table_name="setting_review_batches")
    op.drop_table("setting_review_batches")
    op.drop_index("ix_setting_generation_messages_session", table_name="setting_generation_messages")
    op.drop_table("setting_generation_messages")
    op.drop_index("ix_setting_generation_sessions_novel_status", table_name="setting_generation_sessions")
    op.drop_table("setting_generation_sessions")
```

The current Alembic head observed while writing this plan is `20260430_chapter_quality_gate`. If a newer migration lands before implementation starts, update `down_revision` to the then-current head and mention that change in the Task 1 commit.

- [ ] **Step 5: Add schemas**

Create `src/novel_dev/schemas/setting_workbench.py`:

```python
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


SessionStatus = Literal["clarifying", "ready_to_generate", "generating", "generated", "failed", "archived"]
BatchStatus = Literal["pending", "partially_approved", "approved", "rejected", "superseded", "failed"]
ChangeStatus = Literal["pending", "approved", "rejected", "edited_approved", "failed"]
TargetType = Literal["setting_card", "entity", "relationship"]
ChangeOperation = Literal["create", "update", "delete"]


class SettingGenerationSessionCreate(BaseModel):
    title: str
    initial_idea: str = ""
    target_categories: list[str] = Field(default_factory=list)
    focused_target: Optional[dict[str, Any]] = None


class SettingGenerationSessionResponse(BaseModel):
    id: str
    novel_id: str
    title: str
    status: SessionStatus
    target_categories: list[str]
    clarification_round: int
    conversation_summary: Optional[str] = None
    focused_target: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SettingGenerationMessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class SettingSessionReplyRequest(BaseModel):
    content: str


class SettingReviewChangeResponse(BaseModel):
    id: str
    batch_id: str
    target_type: TargetType
    operation: ChangeOperation
    target_id: Optional[str] = None
    status: ChangeStatus
    before_snapshot: Optional[dict[str, Any]] = None
    after_snapshot: Optional[dict[str, Any]] = None
    conflict_hints: list[dict[str, Any]] = Field(default_factory=list)
    source_session_id: Optional[str] = None
    error_message: Optional[str] = None


class SettingReviewBatchResponse(BaseModel):
    id: str
    novel_id: str
    source_type: str
    source_file: Optional[str] = None
    source_session_id: Optional[str] = None
    source_session_title: Optional[str] = None
    status: BatchStatus
    summary: str
    counts: dict[str, int] = Field(default_factory=dict)
    changes: list[SettingReviewChangeResponse] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SettingWorkbenchPayload(BaseModel):
    sessions: list[SettingGenerationSessionResponse]
    review_batches: list[SettingReviewBatchResponse]


class SettingBatchGenerateRequest(BaseModel):
    force: bool = False


class SettingReviewDecision(BaseModel):
    change_id: str
    decision: Literal["approve", "reject", "edit_approve"]
    edited_after_snapshot: Optional[dict[str, Any]] = None


class SettingReviewApplyRequest(BaseModel):
    decisions: list[SettingReviewDecision]
```

- [ ] **Step 6: Add repository implementation**

Create `src/novel_dev/repositories/setting_workbench_repo.py`:

```python
import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import (
    SettingGenerationMessage,
    SettingGenerationSession,
    SettingReviewBatch,
    SettingReviewChange,
)


class SettingWorkbenchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session(
        self,
        *,
        novel_id: str,
        title: str,
        target_categories: list[str] | None = None,
        focused_target: Optional[dict[str, Any]] = None,
    ) -> SettingGenerationSession:
        item = SettingGenerationSession(
            id=f"sgs_{uuid.uuid4().hex[:10]}",
            novel_id=novel_id,
            title=title.strip() or "未命名设定会话",
            target_categories=list(target_categories or []),
            focused_target=focused_target,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def get_session(self, session_id: str) -> Optional[SettingGenerationSession]:
        result = await self.session.execute(
            select(SettingGenerationSession).where(SettingGenerationSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_sessions(self, novel_id: str) -> list[SettingGenerationSession]:
        result = await self.session.execute(
            select(SettingGenerationSession)
            .where(SettingGenerationSession.novel_id == novel_id)
            .order_by(SettingGenerationSession.updated_at.desc(), SettingGenerationSession.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_session_state(
        self,
        session_id: str,
        *,
        status: str | None = None,
        clarification_round: int | None = None,
        conversation_summary: str | None = None,
        target_categories: list[str] | None = None,
    ) -> Optional[SettingGenerationSession]:
        item = await self.get_session(session_id)
        if item is None:
            return None
        if status is not None:
            item.status = status
        if clarification_round is not None:
            item.clarification_round = clarification_round
        if conversation_summary is not None:
            item.conversation_summary = conversation_summary
        if target_categories is not None:
            item.target_categories = target_categories
        await self.session.flush()
        return item

    async def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> SettingGenerationMessage:
        message = SettingGenerationMessage(
            id=f"sgm_{uuid.uuid4().hex[:10]}",
            session_id=session_id,
            role=role,
            content=content,
            meta=dict(metadata or {}),
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_messages(self, session_id: str) -> list[SettingGenerationMessage]:
        result = await self.session.execute(
            select(SettingGenerationMessage)
            .where(SettingGenerationMessage.session_id == session_id)
            .order_by(SettingGenerationMessage.created_at.asc())
        )
        return list(result.scalars().all())

    async def create_review_batch(
        self,
        *,
        novel_id: str,
        source_type: str,
        summary: str,
        source_session_id: str | None = None,
        source_file: str | None = None,
    ) -> SettingReviewBatch:
        batch = SettingReviewBatch(
            id=f"srb_{uuid.uuid4().hex[:10]}",
            novel_id=novel_id,
            source_type=source_type,
            source_file=source_file,
            source_session_id=source_session_id,
            summary=summary,
        )
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def get_review_batch(self, batch_id: str) -> Optional[SettingReviewBatch]:
        result = await self.session.execute(
            select(SettingReviewBatch).where(SettingReviewBatch.id == batch_id)
        )
        return result.scalar_one_or_none()

    async def list_review_batches(self, novel_id: str) -> list[SettingReviewBatch]:
        result = await self.session.execute(
            select(SettingReviewBatch)
            .where(SettingReviewBatch.novel_id == novel_id)
            .order_by(SettingReviewBatch.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_batch_status(self, batch_id: str, status: str, error_message: str | None = None) -> None:
        batch = await self.get_review_batch(batch_id)
        if batch is None:
            return
        batch.status = status
        batch.error_message = error_message
        await self.session.flush()

    async def add_review_change(
        self,
        *,
        batch_id: str,
        target_type: str,
        operation: str,
        after_snapshot: Optional[dict[str, Any]] = None,
        before_snapshot: Optional[dict[str, Any]] = None,
        target_id: str | None = None,
        conflict_hints: list[dict[str, Any]] | None = None,
        source_session_id: str | None = None,
    ) -> SettingReviewChange:
        change = SettingReviewChange(
            id=f"src_{uuid.uuid4().hex[:10]}",
            batch_id=batch_id,
            target_type=target_type,
            operation=operation,
            target_id=target_id,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            conflict_hints=list(conflict_hints or []),
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

    async def update_change_status(
        self,
        change_id: str,
        status: str,
        *,
        after_snapshot: Optional[dict[str, Any]] = None,
        error_message: str | None = None,
    ) -> None:
        change = await self.get_review_change(change_id)
        if change is None:
            return
        change.status = status
        if after_snapshot is not None:
            change.after_snapshot = after_snapshot
        change.error_message = error_message
        await self.session.flush()
```

- [ ] **Step 7: Run repository tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_setting_workbench_repo.py -q
```

Expected: PASS.

- [ ] **Step 8: Check Alembic heads**

Run:

```bash
alembic heads
```

Expected: command succeeds and shows the current head. If the repository has multiple heads, use the correct branch head as `down_revision` and run `alembic upgrade heads` during final verification.

- [ ] **Step 9: Commit persistence slice**

Run:

```bash
git add src/novel_dev/db/models.py migrations/versions/20260502_add_setting_workbench.py src/novel_dev/schemas/setting_workbench.py src/novel_dev/repositories/setting_workbench_repo.py tests/test_repositories/test_setting_workbench_repo.py
git commit -m "Add setting workbench persistence"
```

## Task 2: Review Batch Application Service

**Files:**
- Create: `src/novel_dev/services/setting_workbench_service.py`
- Modify: `src/novel_dev/services/extraction_service.py`
- Modify: `src/novel_dev/repositories/entity_repo.py`
- Modify: `src/novel_dev/repositories/relationship_repo.py`
- Test: `tests/test_services/test_setting_workbench_service.py`

- [ ] **Step 1: Write service tests for review application**

Create `tests/test_services/test_setting_workbench_service.py`:

```python
import pytest

from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.services.entity_service import EntityService
from novel_dev.services.setting_workbench_service import SettingWorkbenchService

pytestmark = pytest.mark.asyncio


async def test_apply_review_batch_creates_ai_sourced_setting_card_and_entity(async_session):
    repo = SettingWorkbenchRepository(async_session)
    service = SettingWorkbenchService(async_session)
    session = await repo.create_session(
        novel_id="novel-review",
        title="修炼体系补全",
        target_categories=["功法"],
    )
    batch = await repo.create_review_batch(
        novel_id="novel-review",
        source_type="ai_session",
        source_session_id=session.id,
        summary="新增 1 张设定卡片，1 个实体",
    )
    card_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"doc_type": "setting", "title": "修炼体系", "content": "九境修炼体系。"},
        source_session_id=session.id,
    )
    entity_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="create",
        after_snapshot={"type": "item", "name": "道种", "state": {"description": "开辟灵脉的核心资源"}},
        source_session_id=session.id,
    )

    result = await service.apply_review_decisions(
        novel_id="novel-review",
        batch_id=batch.id,
        decisions=[
            {"change_id": card_change.id, "decision": "approve"},
            {"change_id": entity_change.id, "decision": "approve"},
        ],
    )
    await async_session.commit()

    docs = await DocumentRepository(async_session).get_by_type("novel-review", "setting")
    entities = await EntityRepository(async_session).list_by_novel("novel-review")
    refreshed_batch = await repo.get_review_batch(batch.id)

    assert result["status"] == "approved"
    assert docs[0].title == "修炼体系"
    assert docs[0].source_type == "ai"
    assert docs[0].source_session_id == session.id
    assert docs[0].source_review_batch_id == batch.id
    assert docs[0].source_review_change_id == card_change.id
    assert entities[0].name == "道种"
    assert entities[0].source_type == "ai"
    assert refreshed_batch.status == "approved"


async def test_apply_review_batch_supports_partial_approval(async_session):
    repo = SettingWorkbenchRepository(async_session)
    service = SettingWorkbenchService(async_session)
    session = await repo.create_session(novel_id="novel-partial", title="势力格局", target_categories=["势力"])
    batch = await repo.create_review_batch(
        novel_id="novel-partial",
        source_type="ai_session",
        source_session_id=session.id,
        summary="新增 2 个实体",
    )
    approved = await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="create",
        after_snapshot={"type": "faction", "name": "青云门", "state": {"description": "正道宗门"}},
        source_session_id=session.id,
    )
    rejected = await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="create",
        after_snapshot={"type": "faction", "name": "血影楼", "state": {"description": "重复反派组织"}},
        source_session_id=session.id,
    )

    await service.apply_review_decisions(
        novel_id="novel-partial",
        batch_id=batch.id,
        decisions=[
            {"change_id": approved.id, "decision": "approve"},
            {"change_id": rejected.id, "decision": "reject"},
        ],
    )
    await async_session.commit()

    entities = await EntityRepository(async_session).list_by_novel("novel-partial")
    changes = await repo.list_review_changes(batch.id)
    batch_after = await repo.get_review_batch(batch.id)

    assert [entity.name for entity in entities] == ["青云门"]
    assert {change.id: change.status for change in changes} == {
        approved.id: "approved",
        rejected.id: "rejected",
    }
    assert batch_after.status == "partially_approved"


async def test_apply_review_batch_updates_existing_card_with_before_after(async_session):
    doc = await DocumentRepository(async_session).create(
        doc_id="doc_card",
        novel_id="novel-update",
        doc_type="setting",
        title="修炼体系",
        content="三境。",
    )
    repo = SettingWorkbenchRepository(async_session)
    service = SettingWorkbenchService(async_session)
    session = await repo.create_session(novel_id="novel-update", title="修炼体系优化", target_categories=["功法"])
    batch = await repo.create_review_batch(
        novel_id="novel-update",
        source_type="ai_session",
        source_session_id=session.id,
        summary="修改 1 张设定卡片",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="update",
        target_id=doc.id,
        before_snapshot={"content": "三境。"},
        after_snapshot={"doc_type": "setting", "title": "修炼体系", "content": "十二境。"},
        source_session_id=session.id,
    )

    await service.apply_review_decisions(
        novel_id="novel-update",
        batch_id=batch.id,
        decisions=[{"change_id": change.id, "decision": "edit_approve", "edited_after_snapshot": {"doc_type": "setting", "title": "修炼体系", "content": "九境。"}}],
    )
    await async_session.commit()

    docs = await DocumentRepository(async_session).get_by_type("novel-update", "setting")
    newest = max(docs, key=lambda item: item.version)

    assert newest.content == "九境。"
    assert newest.version == 2
    assert newest.source_review_change_id == change.id
```

- [ ] **Step 2: Run service tests and confirm missing service failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_setting_workbench_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.services.setting_workbench_service'`.

- [ ] **Step 3: Implement review application service**

Create `src/novel_dev/services/setting_workbench_service.py` with the review application methods first:

```python
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.services.entity_service import EntityService


class SettingWorkbenchService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SettingWorkbenchRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.entity_service = EntityService(session)
        self.relationship_repo = RelationshipRepository(session)

    async def apply_review_decisions(
        self,
        *,
        novel_id: str,
        batch_id: str,
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        batch = await self.repo.get_review_batch(batch_id)
        if batch is None or batch.novel_id != novel_id:
            raise ValueError("Review batch not found")
        if batch.status not in {"pending", "partially_approved", "failed"}:
            raise ValueError("Review batch is not reviewable")

        decision_by_id = {item["change_id"]: item for item in decisions}
        changes = await self.repo.list_review_changes(batch_id)
        applied = 0
        rejected = 0
        failed = 0

        for change in changes:
            decision = decision_by_id.get(change.id)
            if decision is None or change.status != "pending":
                continue
            if decision["decision"] == "reject":
                await self.repo.update_change_status(change.id, "rejected")
                rejected += 1
                continue
            after_snapshot = decision.get("edited_after_snapshot") if decision["decision"] == "edit_approve" else change.after_snapshot
            status = "edited_approved" if decision["decision"] == "edit_approve" else "approved"
            try:
                await self._apply_change(
                    novel_id=novel_id,
                    batch_id=batch_id,
                    change_id=change.id,
                    source_session_id=change.source_session_id or batch.source_session_id,
                    target_type=change.target_type,
                    operation=change.operation,
                    target_id=change.target_id,
                    after_snapshot=after_snapshot or {},
                )
                await self.repo.update_change_status(change.id, status, after_snapshot=after_snapshot)
                applied += 1
            except Exception as exc:
                await self.repo.update_change_status(change.id, "failed", error_message=str(exc))
                failed += 1

        all_changes = await self.repo.list_review_changes(batch_id)
        terminal = [item for item in all_changes if item.status in {"approved", "edited_approved", "rejected", "failed"}]
        approved_count = len([item for item in all_changes if item.status in {"approved", "edited_approved"}])
        rejected_count = len([item for item in all_changes if item.status == "rejected"])
        failed_count = len([item for item in all_changes if item.status == "failed"])
        if failed_count and approved_count == 0:
            batch_status = "failed"
        elif len(terminal) == len(all_changes) and rejected_count == len(all_changes):
            batch_status = "rejected"
        elif len(terminal) == len(all_changes) and approved_count == len(all_changes):
            batch_status = "approved"
        else:
            batch_status = "partially_approved"

        await self.repo.update_batch_status(batch_id, batch_status)
        await self.session.flush()
        return {"status": batch_status, "applied": applied, "rejected": rejected, "failed": failed}

    async def _apply_change(
        self,
        *,
        novel_id: str,
        batch_id: str,
        change_id: str,
        source_session_id: str | None,
        target_type: str,
        operation: str,
        target_id: str | None,
        after_snapshot: dict[str, Any],
    ) -> None:
        if target_type == "setting_card":
            await self._apply_setting_card_change(
                novel_id=novel_id,
                batch_id=batch_id,
                change_id=change_id,
                source_session_id=source_session_id,
                operation=operation,
                target_id=target_id,
                after_snapshot=after_snapshot,
            )
            return
        if target_type == "entity":
            await self._apply_entity_change(
                novel_id=novel_id,
                batch_id=batch_id,
                change_id=change_id,
                source_session_id=source_session_id,
                operation=operation,
                target_id=target_id,
                after_snapshot=after_snapshot,
            )
            return
        if target_type == "relationship":
            await self._apply_relationship_change(
                novel_id=novel_id,
                batch_id=batch_id,
                change_id=change_id,
                source_session_id=source_session_id,
                operation=operation,
                target_id=target_id,
                after_snapshot=after_snapshot,
            )
            return
        raise ValueError(f"Unsupported review target type: {target_type}")
```

Add helper methods in the same file:

```python
    async def _apply_setting_card_change(
        self,
        *,
        novel_id: str,
        batch_id: str,
        change_id: str,
        source_session_id: str | None,
        operation: str,
        target_id: str | None,
        after_snapshot: dict[str, Any],
    ) -> None:
        if operation == "delete":
            doc = await self.doc_repo.get_by_id(target_id or "")
            if doc is None or doc.novel_id != novel_id:
                raise ValueError("Setting card not found")
            doc.content = f"[已归档]\n{doc.content}"
            doc.source_type = "ai"
            doc.source_session_id = source_session_id
            doc.source_review_batch_id = batch_id
            doc.source_review_change_id = change_id
            await self.session.flush()
            return

        doc_type = str(after_snapshot.get("doc_type") or "setting")
        title = str(after_snapshot.get("title") or "未命名设定")
        content = str(after_snapshot.get("content") or "")
        if not content.strip():
            raise ValueError("Setting card content is required")

        if operation == "update" and target_id:
            existing = await self.doc_repo.get_by_id(target_id)
            if existing is None or existing.novel_id != novel_id:
                raise ValueError("Setting card not found")
            version = existing.version + 1
        else:
            version = 1

        doc = await self.doc_repo.create(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type=doc_type,
            title=title,
            content=content,
            version=version,
        )
        doc.source_type = "ai"
        doc.source_session_id = source_session_id
        doc.source_review_batch_id = batch_id
        doc.source_review_change_id = change_id
        await self.session.flush()

    async def _apply_entity_change(
        self,
        *,
        novel_id: str,
        batch_id: str,
        change_id: str,
        source_session_id: str | None,
        operation: str,
        target_id: str | None,
        after_snapshot: dict[str, Any],
    ) -> None:
        if operation == "delete":
            if not target_id:
                raise ValueError("Entity id is required for delete")
            await self.entity_service.update_entity_fields(
                entity_id=target_id,
                updates={"_archived": True, "_archive_reason": "AI review delete change approved"},
                diff_summary={"source": "setting_workbench", "operation": "delete"},
            )
            return

        entity_type = str(after_snapshot.get("type") or after_snapshot.get("entity_type") or "other")
        name = str(after_snapshot.get("name") or "").strip()
        state = dict(after_snapshot.get("state") or after_snapshot.get("data") or {})
        if not name:
            raise ValueError("Entity name is required")
        state.setdefault("name", name)
        entity = await self.entity_service.create_or_update_entity(
            entity_type=entity_type,
            name=name,
            initial_state=state,
            novel_id=novel_id,
        )
        entity.source_type = "ai"
        entity.source_session_id = source_session_id
        entity.source_review_batch_id = batch_id
        entity.source_review_change_id = change_id
        await self.session.flush()

    async def _apply_relationship_change(
        self,
        *,
        novel_id: str,
        batch_id: str,
        change_id: str,
        source_session_id: str | None,
        operation: str,
        target_id: str | None,
        after_snapshot: dict[str, Any],
    ) -> None:
        if operation == "delete":
            if not target_id:
                raise ValueError("Relationship id is required for delete")
            await self.relationship_repo.deactivate(target_id)
            return
        source_id = str(after_snapshot.get("source_id") or "")
        target_entity_id = str(after_snapshot.get("target_id") or "")
        relation_type = str(after_snapshot.get("relation_type") or "")
        if not source_id or not target_entity_id or not relation_type:
            raise ValueError("Relationship source_id, target_id and relation_type are required")
        relationship = await self.relationship_repo.upsert(
            source_id=source_id,
            target_id=target_entity_id,
            relation_type=relation_type,
            meta={**dict(after_snapshot.get("meta") or {}), "source": "setting_workbench"},
            novel_id=novel_id,
        )
        relationship.source_type = "ai"
        relationship.source_session_id = source_session_id
        relationship.source_review_batch_id = batch_id
        relationship.source_review_change_id = change_id
        await self.session.flush()
```

- [ ] **Step 4: Add repository helpers required by service**

If missing, add these methods:

In `src/novel_dev/repositories/document_repo.py`:

```python
    async def get_by_id(self, doc_id: str) -> Optional[NovelDocument]:
        return await self.session.get(NovelDocument, doc_id)
```

In `src/novel_dev/repositories/relationship_repo.py`:

```python
    async def deactivate(self, relationship_id: str | int) -> bool:
        rel = await self.session.get(EntityRelationship, int(relationship_id))
        if rel is None:
            return False
        rel.is_active = False
        await self.session.flush()
        return True
```

- [ ] **Step 5: Run service tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_setting_workbench_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit review application slice**

Run:

```bash
git add src/novel_dev/services/setting_workbench_service.py src/novel_dev/repositories/document_repo.py src/novel_dev/repositories/relationship_repo.py tests/test_services/test_setting_workbench_service.py
git commit -m "Apply setting workbench review batches"
```

## Task 3: AI Clarification And Batch Generation

**Files:**
- Create: `src/novel_dev/agents/setting_workbench_agent.py`
- Modify: `src/novel_dev/services/setting_workbench_service.py`
- Modify: `llm_config.yaml`
- Test: `tests/test_agents/test_setting_workbench_agent.py`
- Test: `tests/test_services/test_setting_workbench_service.py`

- [ ] **Step 1: Write agent schema tests**

Create `tests/test_agents/test_setting_workbench_agent.py`:

```python
from novel_dev.agents.setting_workbench_agent import (
    SettingBatchDraft,
    SettingClarificationDecision,
)


def test_setting_clarification_decision_accepts_ready_payload():
    decision = SettingClarificationDecision.model_validate({
        "status": "ready",
        "assistant_message": "信息足够，可以生成待审核设定。",
        "target_categories": ["功法", "势力"],
        "conversation_summary": "用户确认玄幻升级流和宗门冲突。",
    })

    assert decision.status == "ready"
    assert decision.target_categories == ["功法", "势力"]


def test_setting_batch_draft_counts_setting_cards_entities_and_relationships():
    draft = SettingBatchDraft.model_validate({
        "summary": "新增 1 张设定卡片，1 个实体，1 个关系变更",
        "changes": [
            {"target_type": "setting_card", "operation": "create", "after_snapshot": {"title": "修炼体系", "content": "九境。"}},
            {"target_type": "entity", "operation": "create", "after_snapshot": {"type": "item", "name": "道种", "state": {}}},
            {"target_type": "relationship", "operation": "create", "after_snapshot": {"source_ref": "陆照", "target_ref": "道种", "relation_type": "持有"}},
        ],
    })

    assert draft.summary.startswith("新增 1 张")
    assert len(draft.changes) == 3
```

- [ ] **Step 2: Run agent tests and confirm missing module failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_setting_workbench_agent.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement agent schemas and prompt builders**

Create `src/novel_dev/agents/setting_workbench_agent.py`:

```python
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SettingClarificationDecision(BaseModel):
    status: Literal["needs_clarification", "ready"]
    assistant_message: str
    questions: list[str] = Field(default_factory=list)
    target_categories: list[str] = Field(default_factory=list)
    conversation_summary: str = ""


class SettingBatchChangeDraft(BaseModel):
    target_type: Literal["setting_card", "entity", "relationship"]
    operation: Literal["create", "update", "delete"]
    target_ref: Optional[str] = None
    target_id: Optional[str] = None
    before_snapshot: Optional[dict[str, Any]] = None
    after_snapshot: Optional[dict[str, Any]] = None
    conflict_hints: list[dict[str, Any]] = Field(default_factory=list)


class SettingBatchDraft(BaseModel):
    summary: str
    changes: list[SettingBatchChangeDraft]


class SettingWorkbenchAgent:
    @staticmethod
    def build_clarification_prompt(
        *,
        title: str,
        target_categories: list[str],
        messages: list[dict[str, Any]],
        conversation_summary: str | None = None,
        max_rounds: int = 5,
    ) -> str:
        return "\n".join([
            "你是小说设定工作台的设定澄清助手。",
            "目标：判断用户信息是否足够生成待审核设定批次。",
            "禁止生成正式设定；不足时只提出澄清问题。",
            f"会话标题：{title}",
            f"目标分类：{', '.join(target_categories) if target_categories else '默认全量'}",
            f"最大澄清轮数：{max_rounds}",
            f"会话摘要：{conversation_summary or '暂无'}",
            "消息历史：",
            *[f"{item.get('role')}: {item.get('content')}" for item in messages],
            "返回 SettingClarificationDecision JSON。",
        ])

    @staticmethod
    def build_generation_prompt(
        *,
        title: str,
        target_categories: list[str],
        messages: list[dict[str, Any]],
        conversation_summary: str | None = None,
        focused_context: dict[str, Any] | None = None,
    ) -> str:
        return "\n".join([
            "你是小说设定工作台的设定生成助手。",
            "只生成待审核批次，不直接写入正式设定。",
            "每个批次必须包含 changes，change target_type 只能是 setting_card、entity、relationship。",
            "operation 只能是 create、update、delete。",
            "setting_card 需要 after_snapshot.doc_type、title、content。",
            "entity 需要 after_snapshot.type、name、state。",
            "relationship 需要 after_snapshot.source_ref 或 source_id、target_ref 或 target_id、relation_type。",
            f"会话标题：{title}",
            f"目标分类：{', '.join(target_categories) if target_categories else '默认全量'}",
            f"会话摘要：{conversation_summary or '暂无'}",
            f"聚焦上下文：{focused_context or {}}",
            "消息历史：",
            *[f"{item.get('role')}: {item.get('content')}" for item in messages],
            "返回 SettingBatchDraft JSON。",
        ])
```

- [ ] **Step 4: Add service tests for clarification and generation**

Append to `tests/test_services/test_setting_workbench_service.py`:

```python
async def test_reply_to_session_stores_clarification_question(async_session, monkeypatch):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai",
        title="修炼体系补全",
        initial_idea="主角废脉开局",
        target_categories=["功法"],
    )

    async def fake_call_and_parse_model(**kwargs):
        from novel_dev.agents.setting_workbench_agent import SettingClarificationDecision
        return SettingClarificationDecision(
            status="needs_clarification",
            assistant_message="请补充世界层级。",
            questions=["世界最高战力到什么层次？"],
            target_categories=["功法"],
            conversation_summary="用户想写废脉开局。",
        )

    monkeypatch.setattr("novel_dev.services.setting_workbench_service.call_and_parse_model", fake_call_and_parse_model)

    result = await service.reply_to_session(
        novel_id="novel-ai",
        session_id=session.id,
        content="想要玄幻升级流",
    )

    assert result["session"].status == "clarifying"
    assert result["assistant_message"] == "请补充世界层级。"
    assert result["questions"] == ["世界最高战力到什么层次？"]


async def test_generate_review_batch_creates_changes_from_agent(async_session, monkeypatch):
    service = SettingWorkbenchService(async_session)
    session = await service.create_generation_session(
        novel_id="novel-ai-gen",
        title="势力格局",
        initial_idea="宗门对立",
        target_categories=["势力"],
    )
    await service.repo.update_session_state(session.id, status="ready_to_generate")

    async def fake_call_and_parse_model(**kwargs):
        from novel_dev.agents.setting_workbench_agent import SettingBatchDraft
        return SettingBatchDraft.model_validate({
            "summary": "新增 1 张设定卡片，1 个实体",
            "changes": [
                {"target_type": "setting_card", "operation": "create", "after_snapshot": {"doc_type": "setting", "title": "势力格局", "content": "青云门与魔宗对立。"}},
                {"target_type": "entity", "operation": "create", "after_snapshot": {"type": "faction", "name": "青云门", "state": {"description": "正道宗门"}}},
            ],
        })

    monkeypatch.setattr("novel_dev.services.setting_workbench_service.call_and_parse_model", fake_call_and_parse_model)

    batch = await service.generate_review_batch(novel_id="novel-ai-gen", session_id=session.id)
    changes = await service.repo.list_review_changes(batch.id)

    assert batch.summary == "新增 1 张设定卡片，1 个实体"
    assert [change.target_type for change in changes] == ["setting_card", "entity"]
```

- [ ] **Step 5: Implement session orchestration methods**

Extend `src/novel_dev/services/setting_workbench_service.py` imports:

```python
from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.agents.setting_workbench_agent import (
    SettingBatchDraft,
    SettingClarificationDecision,
    SettingWorkbenchAgent,
)
```

Add methods:

```python
    async def create_generation_session(
        self,
        *,
        novel_id: str,
        title: str,
        initial_idea: str = "",
        target_categories: list[str] | None = None,
        focused_target: dict[str, Any] | None = None,
    ):
        session = await self.repo.create_session(
            novel_id=novel_id,
            title=title,
            target_categories=target_categories or [],
            focused_target=focused_target,
        )
        if initial_idea.strip():
            await self.repo.add_message(session_id=session.id, role="user", content=initial_idea.strip())
        await self.session.flush()
        return session

    async def reply_to_session(self, *, novel_id: str, session_id: str, content: str) -> dict[str, Any]:
        setting_session = await self.repo.get_session(session_id)
        if setting_session is None or setting_session.novel_id != novel_id:
            raise ValueError("Setting generation session not found")
        await self.repo.add_message(session_id=session_id, role="user", content=content.strip())
        messages = await self.repo.list_messages(session_id)
        prompt = SettingWorkbenchAgent.build_clarification_prompt(
            title=setting_session.title,
            target_categories=setting_session.target_categories or [],
            messages=[{"role": msg.role, "content": msg.content} for msg in messages],
            conversation_summary=setting_session.conversation_summary,
        )
        decision = await call_and_parse_model(
            prompt,
            SettingClarificationDecision,
            task_name="setting_workbench_clarify",
            config_agent_name="setting_workbench_service",
            max_tokens=4096,
        )
        next_round = setting_session.clarification_round + 1
        next_status = "ready_to_generate" if decision.status == "ready" or next_round >= 5 else "clarifying"
        updated = await self.repo.update_session_state(
            session_id,
            status=next_status,
            clarification_round=next_round,
            conversation_summary=decision.conversation_summary,
            target_categories=decision.target_categories or setting_session.target_categories,
        )
        await self.repo.add_message(
            session_id=session_id,
            role="assistant",
            content=decision.assistant_message,
            metadata={"questions": decision.questions, "status": decision.status},
        )
        await self.session.flush()
        return {"session": updated, "assistant_message": decision.assistant_message, "questions": decision.questions}

    async def generate_review_batch(self, *, novel_id: str, session_id: str):
        setting_session = await self.repo.get_session(session_id)
        if setting_session is None or setting_session.novel_id != novel_id:
            raise ValueError("Setting generation session not found")
        if setting_session.status not in {"ready_to_generate", "generated"}:
            raise ValueError("Setting session is not ready to generate")
        await self.repo.update_session_state(session_id, status="generating")
        messages = await self.repo.list_messages(session_id)
        prompt = SettingWorkbenchAgent.build_generation_prompt(
            title=setting_session.title,
            target_categories=setting_session.target_categories or [],
            messages=[{"role": msg.role, "content": msg.content} for msg in messages],
            conversation_summary=setting_session.conversation_summary,
            focused_context=setting_session.focused_target,
        )
        draft = await call_and_parse_model(
            prompt,
            SettingBatchDraft,
            task_name="setting_workbench_generate_batch",
            config_agent_name="setting_workbench_service",
            max_tokens=12000,
        )
        batch = await self.repo.create_review_batch(
            novel_id=novel_id,
            source_type="ai_session",
            source_session_id=session_id,
            summary=draft.summary,
        )
        for item in draft.changes:
            await self.repo.add_review_change(
                batch_id=batch.id,
                target_type=item.target_type,
                operation=item.operation,
                target_id=item.target_id,
                before_snapshot=item.before_snapshot,
                after_snapshot=item.after_snapshot,
                conflict_hints=item.conflict_hints,
                source_session_id=session_id,
            )
        await self.repo.update_session_state(session_id, status="generated")
        await self.repo.add_message(
            session_id=session_id,
            role="assistant",
            content=f"已生成审核记录：{draft.summary}",
            metadata={"batch_id": batch.id},
        )
        await self.session.flush()
        return batch
```

- [ ] **Step 6: Add model profile config**

Modify `llm_config.yaml` to add:

```yaml
setting_workbench_service:
  profile: kimi-for-coding
  temperature: 0.55
  max_tokens: 12000
```

Use the same provider/profile style already used by `outline_workbench_service`.

- [ ] **Step 7: Run agent and service tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_setting_workbench_agent.py tests/test_services/test_setting_workbench_service.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit AI orchestration slice**

Run:

```bash
git add src/novel_dev/agents/setting_workbench_agent.py src/novel_dev/services/setting_workbench_service.py llm_config.yaml tests/test_agents/test_setting_workbench_agent.py tests/test_services/test_setting_workbench_service.py
git commit -m "Add setting workbench AI sessions"
```

## Task 4: API Routes And Serializers

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Modify: `src/novel_dev/services/novel_deletion_service.py`
- Test: `tests/test_api/test_setting_workbench_routes.py`
- Test: `tests/test_api/test_create_novel.py`

- [ ] **Step 1: Write API tests**

Create `tests/test_api/test_setting_workbench_routes.py`:

```python
import pytest

from novel_dev.db.models import NovelState
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository

pytestmark = pytest.mark.asyncio


async def test_setting_workbench_create_session_and_reply(async_session, test_client, monkeypatch):
    async_session.add(NovelState(novel_id="novel-api", current_phase="brainstorming", checkpoint_data={}))
    await async_session.commit()

    async def fake_reply(self, *, novel_id, session_id, content):
        session = await self.repo.get_session(session_id)
        return {"session": session, "assistant_message": "请补充核心势力。", "questions": ["主角敌对势力是谁？"]}

    monkeypatch.setattr("novel_dev.services.setting_workbench_service.SettingWorkbenchService.reply_to_session", fake_reply)

    async with test_client as client:
        created = await client.post(
            "/api/novels/novel-api/settings/sessions",
            json={"title": "主角阵营设定", "initial_idea": "废脉少年", "target_categories": ["人物", "势力"]},
        )
        assert created.status_code == 200
        session_id = created.json()["id"]

        reply = await client.post(
            f"/api/novels/novel-api/settings/sessions/{session_id}/reply",
            json={"content": "主角来自没落宗门"},
        )

    assert reply.status_code == 200
    assert reply.json()["assistant_message"] == "请补充核心势力。"
    assert reply.json()["questions"] == ["主角敌对势力是谁？"]


async def test_setting_workbench_generate_batch_and_apply_review(async_session, test_client, monkeypatch):
    async_session.add(NovelState(novel_id="novel-api-review", current_phase="brainstorming", checkpoint_data={}))
    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(novel_id="novel-api-review", title="修炼体系", target_categories=["功法"])
    batch = await repo.create_review_batch(
        novel_id="novel-api-review",
        source_type="ai_session",
        source_session_id=session.id,
        summary="新增 1 张设定卡片",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"doc_type": "setting", "title": "修炼体系", "content": "九境。"},
        source_session_id=session.id,
    )
    await async_session.commit()

    async with test_client as client:
        list_resp = await client.get("/api/novels/novel-api-review/settings/review_batches")
        apply_resp = await client.post(
            f"/api/novels/novel-api-review/settings/review_batches/{batch.id}/apply",
            json={"decisions": [{"change_id": change.id, "decision": "approve"}]},
        )

    assert list_resp.status_code == 200
    assert list_resp.json()["items"][0]["summary"] == "新增 1 张设定卡片"
    assert apply_resp.status_code == 200
    assert apply_resp.json()["status"] == "approved"
```

- [ ] **Step 2: Run API tests and confirm route failure**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_setting_workbench_routes.py -q
```

Expected: FAIL with 404 for the new `/settings` routes.

- [ ] **Step 3: Add route imports and serializers**

Modify `src/novel_dev/api/routes.py` imports:

```python
from novel_dev.schemas.setting_workbench import (
    SettingBatchGenerateRequest,
    SettingGenerationSessionCreate,
    SettingReviewApplyRequest,
    SettingSessionReplyRequest,
)
from novel_dev.services.setting_workbench_service import SettingWorkbenchService
```

Add serializers near existing serializer helpers:

```python
def _serialize_setting_session(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "novel_id": item.novel_id,
        "title": item.title,
        "status": item.status,
        "target_categories": item.target_categories or [],
        "clarification_round": item.clarification_round,
        "conversation_summary": item.conversation_summary,
        "focused_target": item.focused_target,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _serialize_setting_message(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "session_id": item.session_id,
        "role": item.role,
        "content": item.content,
        "meta": item.meta or {},
        "created_at": item.created_at,
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
        "source_session_id": item.source_session_id,
        "error_message": item.error_message,
    }


def _count_setting_review_changes(changes: list) -> dict[str, int]:
    counts = {"setting_card": 0, "entity": 0, "relationship": 0}
    for change in changes:
        if change.target_type in counts:
            counts[change.target_type] += 1
    return counts
```

- [ ] **Step 4: Add setting routes**

Append routes before librarian routes:

```python
@router.get("/api/novels/{novel_id}/settings/workbench")
async def get_setting_workbench(novel_id: str, session: AsyncSession = Depends(get_session)):
    service = SettingWorkbenchService(session)
    sessions = await service.repo.list_sessions(novel_id)
    batches = await service.repo.list_review_batches(novel_id)
    items = []
    for batch in batches:
        changes = await service.repo.list_review_changes(batch.id)
        items.append({
            **_serialize_setting_review_batch(batch, changes),
        })
    return {"sessions": [_serialize_setting_session(item) for item in sessions], "review_batches": items}


@router.post("/api/novels/{novel_id}/settings/sessions")
async def create_setting_session(
    novel_id: str,
    req: SettingGenerationSessionCreate,
    session: AsyncSession = Depends(get_session),
):
    service = SettingWorkbenchService(session)
    created = await service.create_generation_session(
        novel_id=novel_id,
        title=req.title,
        initial_idea=req.initial_idea,
        target_categories=req.target_categories,
        focused_target=req.focused_target,
    )
    await session.commit()
    return _serialize_setting_session(created)


@router.get("/api/novels/{novel_id}/settings/sessions")
async def list_setting_sessions(novel_id: str, session: AsyncSession = Depends(get_session)):
    service = SettingWorkbenchService(session)
    return {"items": [_serialize_setting_session(item) for item in await service.repo.list_sessions(novel_id)]}


@router.get("/api/novels/{novel_id}/settings/sessions/{session_id}")
async def get_setting_session(novel_id: str, session_id: str, session: AsyncSession = Depends(get_session)):
    service = SettingWorkbenchService(session)
    item = await service.repo.get_session(session_id)
    if item is None or item.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Setting generation session not found")
    messages = await service.repo.list_messages(session_id)
    batches = [batch for batch in await service.repo.list_review_batches(novel_id) if batch.source_session_id == session_id]
    return {
        "session": _serialize_setting_session(item),
        "messages": [_serialize_setting_message(message) for message in messages],
        "review_batches": [_serialize_setting_review_batch(batch, await service.repo.list_review_changes(batch.id)) for batch in batches],
    }


@router.post("/api/novels/{novel_id}/settings/sessions/{session_id}/reply")
async def reply_setting_session(
    novel_id: str,
    session_id: str,
    req: SettingSessionReplyRequest,
    session: AsyncSession = Depends(get_session),
):
    service = SettingWorkbenchService(session)
    try:
        result = await service.reply_to_session(novel_id=novel_id, session_id=session_id, content=req.content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await session.commit()
    return {
        "session": _serialize_setting_session(result["session"]),
        "assistant_message": result["assistant_message"],
        "questions": result["questions"],
    }


@router.post("/api/novels/{novel_id}/settings/sessions/{session_id}/generate")
async def generate_setting_review_batch(
    novel_id: str,
    session_id: str,
    req: SettingBatchGenerateRequest,
    session: AsyncSession = Depends(get_session),
):
    service = SettingWorkbenchService(session)
    try:
        batch = await service.generate_review_batch(novel_id=novel_id, session_id=session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await session.commit()
    changes = await service.repo.list_review_changes(batch.id)
    return _serialize_setting_review_batch(batch, changes)


@router.get("/api/novels/{novel_id}/settings/review_batches")
async def list_setting_review_batches(novel_id: str, session: AsyncSession = Depends(get_session)):
    service = SettingWorkbenchService(session)
    batches = await service.repo.list_review_batches(novel_id)
    return {"items": [_serialize_setting_review_batch(batch, await service.repo.list_review_changes(batch.id)) for batch in batches]}


@router.get("/api/novels/{novel_id}/settings/review_batches/{batch_id}")
async def get_setting_review_batch(novel_id: str, batch_id: str, session: AsyncSession = Depends(get_session)):
    service = SettingWorkbenchService(session)
    batch = await service.repo.get_review_batch(batch_id)
    if batch is None or batch.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Setting review batch not found")
    changes = await service.repo.list_review_changes(batch.id)
    return _serialize_setting_review_batch(batch, changes)


@router.post("/api/novels/{novel_id}/settings/review_batches/{batch_id}/apply")
async def apply_setting_review_batch(
    novel_id: str,
    batch_id: str,
    req: SettingReviewApplyRequest,
    session: AsyncSession = Depends(get_session),
):
    service = SettingWorkbenchService(session)
    try:
        result = await service.apply_review_decisions(
            novel_id=novel_id,
            batch_id=batch_id,
            decisions=[item.model_dump() for item in req.decisions],
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await session.commit()
    return result
```

Add `_serialize_setting_review_batch`:

```python
def _serialize_setting_review_batch(item, changes: list) -> dict[str, Any]:
    return {
        "id": item.id,
        "novel_id": item.novel_id,
        "source_type": item.source_type,
        "source_file": item.source_file,
        "source_session_id": item.source_session_id,
        "status": item.status,
        "summary": item.summary,
        "counts": _count_setting_review_changes(changes),
        "changes": [_serialize_setting_review_change(change) for change in changes],
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
```

- [ ] **Step 5: Include AI source fields in existing serializers**

In `_serialize_library_document`, include:

```python
        "source_type": getattr(doc, "source_type", None),
        "source_session_id": getattr(doc, "source_session_id", None),
        "source_review_batch_id": getattr(doc, "source_review_batch_id", None),
        "source_review_change_id": getattr(doc, "source_review_change_id", None),
```

In entity serializers, include the same source fields for entities and relationships. Use existing keys if the serializer maps `entity_id`.

- [ ] **Step 6: Update deletion cleanup**

Modify `src/novel_dev/services/novel_deletion_service.py` imports and delete sequence:

```python
from novel_dev.db.models import (
    SettingGenerationMessage,
    SettingGenerationSession,
    SettingReviewBatch,
    SettingReviewChange,
)
```

Add deletes before deleting `novel_state`:

```python
await self.session.execute(
    delete(SettingReviewChange).where(
        SettingReviewChange.batch_id.in_(
            select(SettingReviewBatch.id).where(SettingReviewBatch.novel_id == novel_id)
        )
    )
)
await self.session.execute(delete(SettingReviewBatch).where(SettingReviewBatch.novel_id == novel_id))
await self.session.execute(
    delete(SettingGenerationMessage).where(
        SettingGenerationMessage.session_id.in_(
            select(SettingGenerationSession.id).where(SettingGenerationSession.novel_id == novel_id)
        )
    )
)
await self.session.execute(delete(SettingGenerationSession).where(SettingGenerationSession.novel_id == novel_id))
```

- [ ] **Step 7: Run API tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_setting_workbench_routes.py tests/test_api/test_create_novel.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit API slice**

Run:

```bash
git add src/novel_dev/api/routes.py src/novel_dev/services/novel_deletion_service.py tests/test_api/test_setting_workbench_routes.py tests/test_api/test_create_novel.py
git commit -m "Expose setting workbench API"
```

## Task 5: Frontend API, Store, Router, And Workbench Page

**Files:**
- Modify: `src/novel_dev/web/src/api.js`
- Modify: `src/novel_dev/web/src/stores/novel.js`
- Modify: `src/novel_dev/web/src/router.js`
- Modify: `src/novel_dev/web/src/App.vue`
- Create: `src/novel_dev/web/src/views/SettingWorkbench.vue`
- Test: `src/novel_dev/web/src/views/SettingWorkbench.test.js`
- Test: `src/novel_dev/web/src/stores/novel.test.js`
- Test: `src/novel_dev/web/src/App.test.js`

- [ ] **Step 1: Write frontend tests**

Create `src/novel_dev/web/src/views/SettingWorkbench.test.js`:

```javascript
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { describe, expect, it, vi } from 'vitest'
import SettingWorkbench from './SettingWorkbench.vue'
import { useNovelStore } from '@/stores/novel.js'

vi.mock('@/api.js', async () => {
  const actual = await vi.importActual('@/api.js')
  return {
    ...actual,
    getSettingWorkbench: vi.fn().mockResolvedValue({
      sessions: [
        { id: 'sgs_1', title: '修炼体系补全', status: 'clarifying', target_categories: ['功法'], clarification_round: 1 },
      ],
      review_batches: [
        { id: 'srb_1', source_type: 'ai_session', source_session_id: 'sgs_1', status: 'pending', summary: '新增 1 张设定卡片，1 个实体', counts: { setting_card: 1, entity: 1, relationship: 0 }, changes: [] },
      ],
    }),
    createSettingSession: vi.fn().mockResolvedValue({ id: 'sgs_2', title: '主角阵营设定', status: 'clarifying', target_categories: ['人物'], clarification_round: 0 }),
    replySettingSession: vi.fn().mockResolvedValue({ session: { id: 'sgs_2', title: '主角阵营设定', status: 'ready_to_generate', target_categories: ['人物'], clarification_round: 1 }, assistant_message: '信息足够，可以生成。', questions: [] }),
    generateSettingReviewBatch: vi.fn().mockResolvedValue({ id: 'srb_2', status: 'pending', summary: '新增 1 张设定卡片', counts: { setting_card: 1, entity: 0, relationship: 0 }, changes: [] }),
  }
})

describe('SettingWorkbench', () => {
  it('shows import and AI generation entries plus review records', async () => {
    const wrapper = mount(SettingWorkbench, {
      global: { plugins: [createTestingPinia({ stubActions: false })] },
    })
    const store = useNovelStore()
    store.novelId = 'novel-1'
    await flushPromises()

    expect(wrapper.text()).toContain('导入已有资料')
    expect(wrapper.text()).toContain('从想法生成设定')
    expect(wrapper.text()).toContain('审核记录')
    expect(wrapper.text()).toContain('新增 1 张设定卡片，1 个实体')
  })

  it('creates AI session and displays ready generation state', async () => {
    const wrapper = mount(SettingWorkbench, {
      global: { plugins: [createTestingPinia({ stubActions: false })] },
    })
    const store = useNovelStore()
    store.novelId = 'novel-1'
    await flushPromises()

    await wrapper.find('[data-testid="setting-ai-entry"]').trigger('click')
    await wrapper.find('[data-testid="setting-session-title"]').setValue('主角阵营设定')
    await wrapper.find('[data-testid="setting-session-idea"]').setValue('废脉少年')
    await wrapper.find('[data-testid="setting-create-session"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('主角阵营设定')
  })
})
```

- [ ] **Step 2: Run frontend test and confirm missing component failure**

Run:

```bash
cd src/novel_dev/web
npm test -- --run src/views/SettingWorkbench.test.js
```

Expected: FAIL because `SettingWorkbench.vue` does not exist.

- [ ] **Step 3: Add API functions**

Modify `src/novel_dev/web/src/api.js`:

```javascript
export const getSettingWorkbench = (id) =>
  api.get(`/novels/${id}/settings/workbench`).then(r => r.data)
export const createSettingSession = (id, payload) =>
  api.post(`/novels/${id}/settings/sessions`, payload).then(r => r.data)
export const getSettingSession = (id, sessionId) =>
  api.get(`/novels/${id}/settings/sessions/${sessionId}`).then(r => r.data)
export const replySettingSession = (id, sessionId, payload) =>
  api.post(`/novels/${id}/settings/sessions/${sessionId}/reply`, payload).then(r => r.data)
export const generateSettingReviewBatch = (id, sessionId, payload = {}) =>
  api.post(`/novels/${id}/settings/sessions/${sessionId}/generate`, payload).then(r => r.data)
export const getSettingReviewBatch = (id, batchId) =>
  api.get(`/novels/${id}/settings/review_batches/${batchId}`).then(r => r.data)
export const applySettingReviewBatch = (id, batchId, payload) =>
  api.post(`/novels/${id}/settings/review_batches/${batchId}/apply`, payload).then(r => r.data)
```

- [ ] **Step 4: Add store state and actions**

Modify `src/novel_dev/web/src/stores/novel.js`.

Add state factory:

```javascript
const createSettingWorkbenchState = () => ({
  state: 'idle',
  error: '',
  sessions: [],
  reviewBatches: [],
  selectedSessionId: '',
  selectedSession: null,
  selectedMessages: [],
  selectedReviewBatch: null,
  creatingSession: false,
  replying: false,
  generating: false,
  applyingBatch: false,
})
```

Add to store state:

```javascript
settingWorkbench: createSettingWorkbenchState(),
```

Add actions:

```javascript
    async fetchSettingWorkbench() {
      if (!this.novelId) return
      this.settingWorkbench.state = 'loading'
      this.settingWorkbench.error = ''
      try {
        const payload = await api.getSettingWorkbench(this.novelId)
        this.settingWorkbench.sessions = payload.sessions || []
        this.settingWorkbench.reviewBatches = payload.review_batches || []
        this.settingWorkbench.state = 'ready'
      } catch (error) {
        this.settingWorkbench.state = 'error'
        this.settingWorkbench.error = error?.message || '加载设定工作台失败'
      }
    },
    async createSettingSession(payload) {
      if (!this.novelId) return null
      this.settingWorkbench.creatingSession = true
      try {
        const session = await api.createSettingSession(this.novelId, payload)
        this.settingWorkbench.sessions.unshift(session)
        this.settingWorkbench.selectedSessionId = session.id
        return session
      } finally {
        this.settingWorkbench.creatingSession = false
      }
    },
    async loadSettingSession(sessionId) {
      if (!this.novelId || !sessionId) return
      const payload = await api.getSettingSession(this.novelId, sessionId)
      this.settingWorkbench.selectedSessionId = sessionId
      this.settingWorkbench.selectedSession = payload.session
      this.settingWorkbench.selectedMessages = payload.messages || []
      return payload
    },
    async replySettingSession(content) {
      if (!this.novelId || !this.settingWorkbench.selectedSessionId) return null
      this.settingWorkbench.replying = true
      try {
        const payload = await api.replySettingSession(this.novelId, this.settingWorkbench.selectedSessionId, { content })
        this.settingWorkbench.selectedSession = payload.session
        this.settingWorkbench.selectedMessages.push({ role: 'user', content })
        this.settingWorkbench.selectedMessages.push({ role: 'assistant', content: payload.assistant_message, meta: { questions: payload.questions } })
        return payload
      } finally {
        this.settingWorkbench.replying = false
      }
    },
    async generateSettingReviewBatch() {
      if (!this.novelId || !this.settingWorkbench.selectedSessionId) return null
      this.settingWorkbench.generating = true
      try {
        const batch = await api.generateSettingReviewBatch(this.novelId, this.settingWorkbench.selectedSessionId, {})
        this.settingWorkbench.reviewBatches.unshift(batch)
        return batch
      } finally {
        this.settingWorkbench.generating = false
      }
    },
```

- [ ] **Step 5: Add route and menu**

Modify `src/novel_dev/web/src/router.js`:

```javascript
  { path: '/settings', component: () => import('@/views/SettingWorkbench.vue') },
```

Modify `src/novel_dev/web/src/App.vue` menu item:

```javascript
  { path: '/settings', label: '设定工作台', eyebrow: 'Settings', detail: '导入资料，或从初始想法生成可审核设定。' },
```

Keep `/documents` temporarily available for backwards compatibility; its menu label can be changed in Task 6.

- [ ] **Step 6: Create SettingWorkbench view**

Create `src/novel_dev/web/src/views/SettingWorkbench.vue`:

```vue
<template>
  <div class="space-y-6">
    <section class="page-header">
      <div>
        <div class="page-header__eyebrow">Settings Workbench</div>
        <h1 class="page-header__title">设定工作台</h1>
        <p class="page-header__description">导入已有资料，或从一个初始想法生成待审核设定。</p>
      </div>
    </section>

    <el-alert v-if="!store.novelId" title="请先选择小说" type="info" show-icon />
    <template v-else>
      <div class="grid gap-4 lg:grid-cols-2">
        <button type="button" class="surface-card setting-entry" @click="$router.push('/documents')">
          <span class="setting-entry__title">导入已有资料</span>
          <span class="setting-entry__desc">上传世界观、人物表、文风样本和设定文档，生成审核记录。</span>
        </button>
        <button type="button" class="surface-card setting-entry" data-testid="setting-ai-entry" @click="mode = 'ai'">
          <span class="setting-entry__title">从想法生成设定</span>
          <span class="setting-entry__desc">通过多轮澄清生成待审核设定批次。</span>
        </button>
      </div>

      <section v-if="mode === 'ai'" class="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
        <aside class="surface-card p-4">
          <div class="font-semibold">AI 会话</div>
          <div class="mt-3 space-y-2">
            <button
              v-for="session in store.settingWorkbench.sessions"
              :key="session.id"
              type="button"
              class="setting-session-item"
              :class="{ 'setting-session-item--active': session.id === store.settingWorkbench.selectedSessionId }"
              @click="selectSession(session.id)"
            >
              <span>{{ session.title }}</span>
              <small>{{ statusLabel(session.status) }}</small>
            </button>
          </div>
          <div class="mt-4 space-y-2">
            <input v-model="newTitle" data-testid="setting-session-title" class="setting-input" placeholder="会话标题，例如：修炼体系补全" />
            <textarea v-model="newIdea" data-testid="setting-session-idea" class="setting-input min-h-[96px]" placeholder="输入初始想法" />
            <button data-testid="setting-create-session" class="setting-primary" type="button" :disabled="store.settingWorkbench.creatingSession" @click="createSession">
              创建会话
            </button>
          </div>
        </aside>

        <section class="surface-card p-4">
          <div class="flex items-start justify-between gap-3">
            <div>
              <h2 class="text-xl font-semibold">{{ selectedSession?.title || '选择或创建会话' }}</h2>
              <p class="mt-1 text-sm text-gray-500">多轮澄清后生成待审核设定记录。</p>
            </div>
            <button
              v-if="selectedSession?.status === 'ready_to_generate' || selectedSession?.status === 'generated'"
              type="button"
              class="setting-primary"
              :disabled="store.settingWorkbench.generating"
              @click="store.generateSettingReviewBatch()"
            >
              {{ store.settingWorkbench.generating ? '生成中...' : '生成待审核设定' }}
            </button>
          </div>

          <div class="mt-4 max-h-80 space-y-3 overflow-auto rounded-xl border p-3">
            <div v-if="!messages.length" class="text-sm text-gray-500">暂无对话。创建会话后继续补充信息。</div>
            <article v-for="(message, index) in messages" :key="message.id || index" class="setting-message">
              <div class="text-xs uppercase text-gray-400">{{ message.role === 'user' ? '你' : 'AI' }}</div>
              <div class="mt-1 whitespace-pre-wrap text-sm">{{ message.content }}</div>
            </article>
          </div>

          <div class="mt-4 flex gap-2">
            <textarea v-model="replyDraft" class="setting-input min-h-[80px] flex-1" placeholder="回答澄清问题，或继续优化设定方向" />
            <button class="setting-primary self-end" type="button" :disabled="!replyDraft.trim() || store.settingWorkbench.replying" @click="sendReply">
              {{ store.settingWorkbench.replying ? '发送中...' : '发送回答' }}
            </button>
          </div>
        </section>
      </section>

      <section class="surface-card p-5">
        <div class="flex items-center justify-between">
          <h2 class="text-xl font-semibold">审核记录</h2>
          <button type="button" class="documents-library-card__edit" @click="store.fetchSettingWorkbench()">刷新</button>
        </div>
        <div v-if="!reviewBatches.length" class="mt-4 text-sm text-gray-500">暂无审核记录。</div>
        <div v-else class="mt-4 space-y-3">
          <article v-for="batch in reviewBatches" :key="batch.id" class="setting-review-row">
            <div class="font-semibold">{{ batch.summary }}</div>
            <div class="mt-1 text-xs text-gray-500">
              {{ batch.source_type === 'ai_session' ? 'AI 会话' : '导入资料' }} · {{ statusLabel(batch.status) }}
            </div>
            <div class="mt-2 text-sm text-gray-600">
              设定卡片 {{ batch.counts?.setting_card || 0 }} · 实体 {{ batch.counts?.entity || 0 }} · 关系 {{ batch.counts?.relationship || 0 }}
            </div>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useNovelStore } from '@/stores/novel.js'

const store = useNovelStore()
const mode = ref('landing')
const newTitle = ref('')
const newIdea = ref('')
const replyDraft = ref('')

const selectedSession = computed(() => store.settingWorkbench.selectedSession)
const messages = computed(() => store.settingWorkbench.selectedMessages || [])
const reviewBatches = computed(() => store.settingWorkbench.reviewBatches || [])

watch(() => store.novelId, () => {
  if (store.novelId) store.fetchSettingWorkbench()
}, { immediate: true })

onMounted(() => {
  if (store.novelId) store.fetchSettingWorkbench()
})

function statusLabel(status) {
  return {
    clarifying: '澄清中',
    ready_to_generate: '可生成',
    generating: '生成中',
    generated: '已生成',
    pending: '待审核',
    approved: '已批准',
    partially_approved: '部分通过',
    rejected: '已拒绝',
    failed: '失败',
  }[status] || status || '未知'
}

async function createSession() {
  const session = await store.createSettingSession({
    title: newTitle.value || '未命名设定会话',
    initial_idea: newIdea.value,
    target_categories: [],
  })
  if (session?.id) await store.loadSettingSession(session.id)
}

async function selectSession(id) {
  await store.loadSettingSession(id)
}

async function sendReply() {
  const content = replyDraft.value.trim()
  if (!content) return
  replyDraft.value = ''
  await store.replySettingSession(content)
}
</script>

<style scoped>
.setting-entry {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 1.25rem;
  text-align: left;
}
.setting-entry__title,
.setting-primary {
  font-weight: 700;
}
.setting-entry__desc {
  color: var(--app-text-muted);
  font-size: 0.875rem;
}
.setting-session-item,
.setting-input,
.setting-review-row,
.setting-message {
  border: 1px solid var(--app-border);
  border-radius: 0.75rem;
  background: var(--app-surface);
}
.setting-session-item {
  display: flex;
  width: 100%;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.75rem;
  text-align: left;
}
.setting-session-item--active {
  border-color: var(--app-border-strong);
  background: var(--app-surface-soft);
}
.setting-input {
  width: 100%;
  padding: 0.75rem;
  color: var(--app-text);
}
.setting-primary {
  border-radius: 999px;
  background: color-mix(in srgb, var(--app-accent, #14b8a6) 78%, white 10%);
  color: white;
  padding: 0.625rem 1rem;
}
.setting-primary:disabled {
  opacity: 0.5;
}
.setting-review-row,
.setting-message {
  padding: 0.875rem;
}
</style>
```

- [ ] **Step 7: Run frontend workbench tests**

Run:

```bash
cd src/novel_dev/web
npm test -- --run src/views/SettingWorkbench.test.js src/stores/novel.test.js src/App.test.js
```

Expected: PASS after adding any store mock imports needed by existing tests.

- [ ] **Step 8: Commit frontend workbench shell**

Run:

```bash
git add src/novel_dev/web/src/api.js src/novel_dev/web/src/stores/novel.js src/novel_dev/web/src/router.js src/novel_dev/web/src/App.vue src/novel_dev/web/src/views/SettingWorkbench.vue src/novel_dev/web/src/views/SettingWorkbench.test.js src/novel_dev/web/src/stores/novel.test.js src/novel_dev/web/src/App.test.js
git commit -m "Add setting workbench frontend"
```

## Task 6: Unified Review UI, AI Badges, And Source Backlinks

**Files:**
- Modify: `src/novel_dev/web/src/views/Documents.vue`
- Modify: `src/novel_dev/web/src/views/Entities.vue`
- Modify: `src/novel_dev/web/src/components/entities/EntityDetailPanel.vue`
- Modify: `src/novel_dev/web/src/components/EntityGraph.vue`
- Test: `src/novel_dev/web/src/views/Documents.test.js`
- Test: `src/novel_dev/web/src/views/Entities.test.js`
- Test: `src/novel_dev/web/src/components/EntityGraph.test.js`

- [ ] **Step 1: Write UI tests for labels and AI badges**

Append to `src/novel_dev/web/src/views/Documents.test.js`:

```javascript
it('renames import review records to unified review records', async () => {
  const wrapper = mountDocumentsWithStore({
    pendingDocs: [
      { id: 'pe_1', source_filename: '设定.md', extraction_type: 'setting', status: 'pending', diff_result: { summary: '1 个新增实体' } },
    ],
  })
  await flushPromises()

  expect(wrapper.text()).toContain('审核记录')
  expect(wrapper.text()).not.toContain('导入审核记录')
})

it('shows AI badge next to AI sourced setting cards', async () => {
  const wrapper = mountDocumentsWithStore({
    libraryItems: [
      { id: 'doc_ai', doc_type: 'setting', title: '修炼体系', content: '九境。', version: 1, source_type: 'ai', source_session_id: 'sgs_1' },
    ],
  })
  await flushPromises()

  expect(wrapper.text()).toContain('AI')
  expect(wrapper.text()).toContain('修炼体系')
})
```

Append to entity-related tests:

```javascript
it('renders AI source backlink for AI generated entity detail', async () => {
  const wrapper = mountEntitiesWithStore({
    entities: [
      { entity_id: 'ent_1', name: '青云门', type: 'faction', source_type: 'ai', source_session_id: 'sgs_1', latest_state: {} },
    ],
  })
  await flushPromises()

  expect(wrapper.text()).toContain('AI 生成')
  expect(wrapper.text()).toContain('查看会话')
})
```

- [ ] **Step 2: Run UI tests and confirm label/badge failures**

Run:

```bash
cd src/novel_dev/web
npm test -- --run src/views/Documents.test.js src/views/Entities.test.js src/components/EntityGraph.test.js
```

Expected: FAIL on missing unified label or AI badge.

- [ ] **Step 3: Rename Documents review surface**

Modify `src/novel_dev/web/src/views/Documents.vue`:

```vue
<h3 class="font-bold">审核记录</h3>
<p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
  这里统一显示导入资料、AI 设定会话和后续优化产生的待审核变更。
</p>
```

Keep existing pending extraction rows until the unified `setting_review_batches` UI fully replaces them. Add a source column that displays `导入资料` for existing `pendingDocs`.

- [ ] **Step 4: Add AI badge component inline for documents**

In library card title area:

```vue
<div class="font-medium text-gray-900 dark:text-gray-100">
  {{ item.title || group.label }}
  <button
    v-if="item.source_type === 'ai' && item.source_session_id"
    type="button"
    class="documents-ai-badge"
    @click="openSourceSession(item.source_session_id, item.source_review_change_id)"
  >
    AI
  </button>
</div>
```

Add method:

```javascript
function openSourceSession(sessionId, changeId = '') {
  const query = new URLSearchParams({ session: sessionId })
  if (changeId) query.set('change', changeId)
  window.location.assign(`/settings?${query.toString()}`)
}
```

Add style:

```css
.documents-ai-badge {
  margin-left: 0.5rem;
  border: 1px solid color-mix(in srgb, #2563eb 35%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, #2563eb 9%, var(--app-surface));
  color: #2563eb;
  padding: 0.05rem 0.45rem;
  font-size: 0.68rem;
  font-weight: 800;
}
```

- [ ] **Step 5: Add AI badges to entity detail and graph**

In `EntityDetailPanel.vue`, show:

```vue
<button
  v-if="entity?.source_type === 'ai' && entity?.source_session_id"
  type="button"
  class="entity-ai-badge"
  @click="$emit('open-source-session', { sessionId: entity.source_session_id, changeId: entity.source_review_change_id })"
>
  AI 生成 · 查看会话
</button>
```

Add emit:

```javascript
const emit = defineEmits(['open-source-session'])
```

In `Entities.vue`, handle the event:

```vue
<EntityDetailPanel
  ...
  @open-source-session="openSourceSession"
/>
```

Add method:

```javascript
function openSourceSession({ sessionId, changeId }) {
  const query = new URLSearchParams({ session: sessionId })
  if (changeId) query.set('change', changeId)
  window.location.assign(`/settings?${query.toString()}`)
}
```

For `EntityGraph.vue`, add source info to edge detail tooltip or selected edge panel:

```vue
<button
  v-if="selectedRelationship?.source_type === 'ai' && selectedRelationship?.source_session_id"
  type="button"
  class="entity-ai-badge"
  @click="$emit('open-source-session', { sessionId: selectedRelationship.source_session_id, changeId: selectedRelationship.source_review_change_id })"
>
  AI 生成 · 查看会话
</button>
```

- [ ] **Step 6: Run UI tests**

Run:

```bash
cd src/novel_dev/web
npm test -- --run src/views/Documents.test.js src/views/Entities.test.js src/components/EntityGraph.test.js
```

Expected: PASS.

- [ ] **Step 7: Commit review UI and backlinks**

Run:

```bash
git add src/novel_dev/web/src/views/Documents.vue src/novel_dev/web/src/views/Documents.test.js src/novel_dev/web/src/views/Entities.vue src/novel_dev/web/src/views/Entities.test.js src/novel_dev/web/src/components/entities/EntityDetailPanel.vue src/novel_dev/web/src/components/EntityGraph.vue src/novel_dev/web/src/components/EntityGraph.test.js
git commit -m "Add setting review backlinks"
```

## Task 7: Final Integration, Migration, And Runtime Verification

**Files:**
- Modify only files required by failed verification.
- Test commands cover backend, frontend, build, migration, and live health.

- [ ] **Step 1: Run backend focused suite**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest \
  tests/test_repositories/test_setting_workbench_repo.py \
  tests/test_services/test_setting_workbench_service.py \
  tests/test_api/test_setting_workbench_routes.py \
  tests/test_api/test_setting_style_routes.py \
  tests/test_services/test_extraction_service.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend focused suite**

Run:

```bash
cd src/novel_dev/web
npm test -- --run \
  src/views/SettingWorkbench.test.js \
  src/views/Documents.test.js \
  src/views/Entities.test.js \
  src/components/EntityGraph.test.js \
  src/stores/novel.test.js
```

Expected: PASS.

- [ ] **Step 3: Run migration checks**

Run:

```bash
alembic heads
alembic upgrade heads
```

Expected: both commands succeed. If `alembic heads` shows multiple heads, use `alembic upgrade heads`, not `head`.

- [ ] **Step 4: Run frontend build**

Run:

```bash
cd src/novel_dev/web
npm run build
```

Expected: PASS. Vite chunk-size warnings are acceptable if build exits 0.

- [ ] **Step 5: Restart backend and verify routes**

Run:

```bash
pkill -f "uvicorn novel_dev.api" || true
screen -S novel-dev-api -dm bash -lc 'cd /Users/linlin/Desktop/novel-dev && exec env PYTHONPATH=src DATABASE_URL=postgresql+asyncpg://linlin@localhost/novel_dev python3.11 -m uvicorn novel_dev.api:app --host 0.0.0.0 --port 8000 >> /tmp/novel-dev/api.log 2>&1'
curl -sf http://127.0.0.1:8000/healthz
```

Expected: `{"ok":true}`.

- [ ] **Step 6: Verify setting workbench API manually**

Run, replacing `novel-b963` with an existing novel id if needed:

```bash
curl -sf http://127.0.0.1:8000/api/novels/novel-b963/settings/workbench
```

Expected: JSON with `sessions` and `review_batches` arrays.

- [ ] **Step 7: Commit verification fixes**

If verification required code changes, inspect the files changed by those fixes and commit the verified fix set:

```bash
git status --short
git add path/to/changed_file.py path/to/changed_test.py
git commit -m "Stabilize setting workbench integration"
```

If no changes were required, do not create an empty commit.

## Self-Review Checklist

- Spec coverage: persistence, AI sessions, multi-round clarification, review batches, setting cards, entities, relationships, partial approval, AI source badges, backlinks, optimization context, deletion cleanup, and tests are all assigned to tasks.
- Placeholder scan: no step relies on vague catch-all implementation language; each implementation step names files and concrete code shape.
- Type consistency: `setting_card`, `entity`, `relationship`, `create`, `update`, `delete`, `source_session_id`, `source_review_batch_id`, and `source_review_change_id` are used consistently across schemas, models, services, API, and UI.
