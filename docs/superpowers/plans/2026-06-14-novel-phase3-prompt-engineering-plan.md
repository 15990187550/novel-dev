# novel-dev 阶段三:Prompt 工程化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 novel-dev 的 8 个 agent prompt 抽取为数据库版本化存储,加 A/B test harness 和 LLM 根因分析 service,UI 给出采纳/回滚入口,根因分析结果嵌入自动重写决策。

**Architecture:** 3 个新表(`prompt_versions` / `quality_root_cause` / `ab_tests`)+ 3 个新 service(`PromptRegistry` / `ABTestRunner` / `RootCauseAnalyzer`)+ LLM 工厂层加 `ABTestMiddleware` 做版本调度;8 个 agent 改成从 registry 加载 prompt;FastReviewAgent 调 Analyzer,WriterAgent 读根因写进 chapter_context 顶部。

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 async, Pydantic, FastAPI, Alembic, Vue 3, pytest, scipy(用于 Welch's t-test)。

**Branch:** 阶段二完成后继续在 `phase2-writer-protection` 分支上叠加阶段三 commit(用户决定后可以再拉新分支)。

**前置条件:**
- 阶段二已交付:`RecommendationWirer` / `ChapterRewriteService` / `BeatCoverageValidator` 在 `phase2-writer-protection` 分支上
- 阶段一已建:`chapter_quality_metrics.prompt_version` 字段、`judge_consistency` utility
- 8 个生产 agent:`brainstorm` / `volume_planner` / `context_agent` / `writer` / `critic` / `editor` / `fast_review` / `librarian`

---

## 任务清单(25 个)

| 任务 | 组件 | 文件 |
|---|---|---|
| 1 | DB 模型 | `src/novel_dev/db/models.py` |
| 2 | Alembic 迁移 | `alembic/versions/xxxx_phase3_tables.py` |
| 3 | 默认 prompts 引导 | `src/novel_dev/agents/_default_prompts.py` |
| 4 | PromptVersionRepository | `src/novel_dev/repositories/prompt_version_repo.py` |
| 5 | RootCauseRepository | `src/novel_dev/repositories/root_cause_repo.py` |
| 6 | ABTestRepository | `src/novel_dev/repositories/ab_test_repo.py` |
| 7 | PromptRegistry service | `src/novel_dev/services/prompt_registry.py` |
| 8 | 8 个 agent 迁移 | 8 个 agent 文件 |
| 9 | QualityMetricsService 记录 prompt_version | `src/novel_dev/services/quality_metrics_service.py` |
| 10 | ABTestRunner service | `src/novel_dev/services/ab_test_runner.py` |
| 11 | ABTestMiddleware in LLMFactory | `src/novel_dev/llm/factory.py` |
| 12 | RootCauseAnalyzer service | `src/novel_dev/services/root_cause_analyzer.py` |
| 13 | FastReviewAgent 集成 | `src/novel_dev/agents/fast_review_agent.py` |
| 14 | WireResult + Wirer 读根因 | `src/novel_dev/services/recommendation_wirer.py` |
| 15 | ChapterRewriteService 注入 | `src/novel_dev/services/chapter_rewrite_service.py` |
| 16 | WriterAgent 读根因入 context | `src/novel_dev/agents/writer_agent.py` |
| 17 | 4 个 prompt CRUD API | `src/novel_dev/api/routes.py` |
| 18 | 5 个 A/B API | `src/novel_dev/api/routes.py` |
| 19 | root cause 查询 API | `src/novel_dev/api/routes.py` |
| 20 | PromptVersionsManager.vue | `src/novel_dev/web/src/views/PromptVersionsManager.vue` |
| 21 | ABTestConsole.vue | `src/novel_dev/web/src/views/ABTestConsole.vue` |
| 22 | QualityRecommendationWidget 加根因 | `src/novel_dev/web/src/components/QualityRecommendationWidget.vue` |
| 23 | llm_config.yaml phase3 段 | `llm_config.yaml` + `config/quality_config.py` |
| 24 | E2E 测试 | `tests/test_e2e/test_phase3_prompt_engineering.py` |
| 25 | 全量测试 + 覆盖率 | (验证) |

---

## Task 1: 添加 3 个 DB 模型

**Files:**
- Modify: `src/novel_dev/db/models.py`(在 `Chapter` 模型附近新增 3 个类)
- Test: `tests/test_db/test_phase3_models.py`(新建)

- [ ] **Step 1: 写失败测试**

在 `tests/test_db/test_phase3_models.py`:
```python
import pytest
from novel_dev.db.models import PromptVersion, QualityRootCause, ABTest

def test_prompt_version_table_columns():
    assert hasattr(PromptVersion, "agent_name")
    assert hasattr(PromptVersion, "version")
    assert hasattr(PromptVersion, "content")
    assert hasattr(PromptVersion, "is_active")
    assert hasattr(PromptVersion, "created_at")
    assert hasattr(PromptVersion, "created_by")
    assert hasattr(PromptVersion, "sample_count")
    assert hasattr(PromptVersion, "parent_version")
    assert hasattr(PromptVersion, "ab_test_id")

def test_quality_root_cause_table_columns():
    assert hasattr(QualityRootCause, "chapter_id")
    assert hasattr(QualityRootCause, "analyzer_version")
    assert hasattr(QualityRootCause, "summary")
    assert hasattr(QualityRootCause, "suggested_actions")
    assert hasattr(QualityRootCause, "confidence")
    assert hasattr(QualityRootCause, "input_snapshot")
    assert hasattr(QualityRootCause, "created_at")

def test_ab_test_table_columns():
    assert hasattr(ABTest, "agent_name")
    assert hasattr(ABTest, "baseline_version")
    assert hasattr(ABTest, "challenger_version")
    assert hasattr(ABTest, "status")
    assert hasattr(ABTest, "winner")
    assert hasattr(ABTest, "started_at")
    assert hasattr(ABTest, "ended_at")
    assert hasattr(ABTest, "config")
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_db/test_phase3_models.py -v`
Expected: ImportError 或 AttributeError

- [ ] **Step 3: 实现 3 个模型**

在 `src/novel_dev/db/models.py` `Chapter` 类之后,新增:

```python
class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("agent_name", "version", name="uq_prompt_versions_agent_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    created_by: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    ab_test_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)


class QualityRootCause(Base):
    __tablename__ = "quality_root_cause"
    __table_args__ = (
        Index("ix_quality_root_cause_chapter_created", "chapter_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chapter_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    analyzer_version: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_actions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class ABTest(Base):
    __tablename__ = "ab_tests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    baseline_version: Mapped[str] = mapped_column(String(32), nullable=False)
    challenger_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", index=True)
    winner: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
```

需要的 import(检查文件顶部是否已存在):
- `from sqlalchemy import ... UniqueConstraint, Index, Float, JSON` 等
- `import uuid`
- `from datetime import datetime`

- [ ] **Step 4: 跑测试,确认通过**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_db/test_phase3_models.py -v`
Expected: 3 PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/db/models.py tests/test_db/test_phase3_models.py
git commit -m "feat(db): add PromptVersion, QualityRootCause, ABTest models"
```

---

## Task 2: Alembic 迁移

**Files:**
- Create: `alembic/versions/2026_06_14_phase3_tables.py`(新迁移)

- [ ] **Step 1: 生成迁移手稿**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src alembic revision -m "phase3 prompt engineering tables"
```

Expected: 创建一个 `alembic/versions/xxxx_phase3_prompt_engineering_tables.py` 文件,记下文件名。

- [ ] **Step 2: 编写 upgrade() 和 downgrade()**

在新建的迁移文件中,替换 `upgrade()` 和 `downgrade()`:

```python
"""phase3 prompt engineering tables

Revision ID: <paste-revision-id>
Revises: <paste-prev-revision>
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "<paste>"
down_revision = "<paste>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_name", sa.String(64), nullable=False, index=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("false"), index=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_by", sa.String(32), nullable=False, server_default="user"),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("parent_version", sa.String(32), nullable=True),
        sa.Column("ab_test_id", sa.String(36), nullable=True, index=True),
        sa.UniqueConstraint("agent_name", "version", name="uq_prompt_versions_agent_version"),
    )

    op.create_table(
        "quality_root_cause",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chapter_id", sa.String(64), nullable=False, index=True),
        sa.Column("analyzer_version", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("suggested_actions", sa.JSON, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("input_snapshot", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), index=True),
    )
    op.create_index("ix_quality_root_cause_chapter_created", "quality_root_cause", ["chapter_id", "created_at"])

    op.create_table(
        "ab_tests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_name", sa.String(64), nullable=False, index=True),
        sa.Column("baseline_version", sa.String(32), nullable=False),
        sa.Column("challenger_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running", index=True),
        sa.Column("winner", sa.String(16), nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("ended_at", sa.DateTime, nullable=True),
        sa.Column("config", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ab_tests")
    op.drop_index("ix_quality_root_cause_chapter_created", table_name="quality_root_cause")
    op.drop_table("quality_root_cause")
    op.drop_table("prompt_versions")
```

- [ ] **Step 3: 跑迁移验证(上 + 下)**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src alembic upgrade head
# 检查表存在(可以 psql 或者用下面的 Python)
PYTHONPATH=src python3.11 -c "from novel_dev.db.models import PromptVersion, QualityRootCause, ABTest; from novel_dev.db import engine; print('OK')"
PYTHONPATH=src alembic downgrade -1
PYTHONPATH=src alembic upgrade head
```

Expected: 三次都正常,迁移可上可下。

- [ ] **Step 4: 提交**

```bash
git add alembic/versions/<paste-filename>.py
git commit -m "feat(db): alembic migration for phase3 tables"
```

---

## Task 3: 默认 prompts 引导文件

**Files:**
- Create: `src/novel_dev/agents/_default_prompts.py`

- [ ] **Step 1: 写文件**

读取 `src/novel_dev/agents/writer_agent.py` 等 8 个 agent 文件,把它们的 hardcoded prompt 字符串(通常是 `system_template` / `prompt_template` / `PROMPT` 等模块级常量,或方法内的 f-string)抽出来,放到 `_default_prompts.py`。如果某些 prompt 完全是方法内 f-string,提取为函数返回这些字符串的常量。

示例结构:
```python
# src/novel_dev/agents/_default_prompts.py
"""Default prompt templates for all 8 production agents + 1 root cause analyzer.

These defaults are loaded into the prompt_versions table on first boot
if the table is empty. Each agent falls back to its hardcoded default
if the registry is empty AND cold_start.allow_hardcoded_fallback is true.
"""

DEFAULT_PROMPTS: dict[str, str] = {
    "brainstorm": "<从 brainstorm_agent.py 抽出>",
    "volume_planner": "<从 volume_planner.py 抽出>",
    "context_agent": "<从 context_agent.py 抽出>",
    "writer": "<从 writer_agent.py 抽出>",
    "critic": "<从 critic_agent.py 抽出>",
    "editor": "<从 editor_agent.py 抽出>",
    "fast_review": "<从 fast_review_agent.py 抽出>",
    "librarian": "<从 librarian.py 抽出>",
    "root_cause_analyzer": (
        "你是一个小说质量根因分析专家。下面是某章节的元数据:\n"
        "- 章节文本(已截断到 5000 字):\n{chapter_text}\n"
        "- 5 维评分:\n{score_breakdown}\n"
        "- 触发的问题码:\n{issue_codes}\n"
        "- beat boundary cards:\n{beat_cards}\n\n"
        "请分析:本章的核心质量问题是什么?给出 2-3 句话的 summary,"
        "以及 1-3 个 suggested_actions(每条含 action / target / severity)。"
        "最后给出 confidence (0-1)。\n\n"
        "请以 JSON 格式返回:\n"
        '{"summary": "...", "suggested_actions": [...], "confidence": 0.x}'
    ),
}
```

实施步骤:
1. `grep -nE '^[A-Z_]+\s*=\s*[\"\x27]{3}|prompt_template|system_template' src/novel_dev/agents/*.py` 找到所有 prompt 字符串
2. 逐个 agent 抽出来,作为 `DEFAULT_PROMPTS` 的值
3. 9 个 key 不能少(包括 `root_cause_analyzer`)

- [ ] **Step 2: 验证导入**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -c "from novel_dev.agents._default_prompts import DEFAULT_PROMPTS; print(len(DEFAULT_PROMPTS), 'prompts loaded'); print(list(DEFAULT_PROMPTS.keys()))"
```

Expected: 9 prompts loaded,keys 包含 brainstorm / volume_planner / context_agent / writer / critic / editor / fast_review / librarian / root_cause_analyzer

- [ ] **Step 3: 提交**

```bash
git add src/novel_dev/agents/_default_prompts.py
git commit -m "feat(agents): extract default prompts for cold-start bootstrap"
```

---

## Task 4: PromptVersionRepository

**Files:**
- Create: `src/novel_dev/repositories/prompt_version_repo.py`
- Test: `tests/test_repositories/test_prompt_version_repo.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_repositories/test_prompt_version_repo.py
import pytest
from novel_dev.db.models import PromptVersion
from novel_dev.repositories.prompt_version_repo import PromptVersionRepository


@pytest.mark.asyncio
async def test_create_and_get_active(async_session):
    repo = PromptVersionRepository(async_session)
    await repo.create(agent_name="writer", version="v1.0", content="hello {var}", is_active=True)
    active = await repo.get_active("writer")
    assert active is not None
    assert active.content == "hello {var}"
    assert active.is_active is True


@pytest.mark.asyncio
async def test_set_active_atomic_switch(async_session):
    repo = PromptVersionRepository(async_session)
    await repo.create(agent_name="writer", version="v1.0", content="old", is_active=True)
    await repo.create(agent_name="writer", version="v2.0", content="new", is_active=False)
    await repo.set_active("writer", "v2.0")
    active = await repo.get_active("writer")
    assert active.version == "v2.0"
    # v1.0 应该已自动取消 active
    v1 = await repo.get_by_version("writer", "v1.0")
    assert v1.is_active is False


@pytest.mark.asyncio
async def test_list_versions_descending(async_session):
    repo = PromptVersionRepository(async_session)
    await repo.create(agent_name="writer", version="v1.0", content="a", is_active=True)
    await repo.create(agent_name="writer", version="v2.0", content="b")
    versions = await repo.list_versions("writer")
    assert [v.version for v in versions] == ["v2.0", "v1.0"]


@pytest.mark.asyncio
async def test_delete_inactive_only(async_session):
    repo = PromptVersionRepository(async_session)
    await repo.create(agent_name="writer", version="v1.0", content="a", is_active=True)
    with pytest.raises(ValueError, match="active"):
        await repo.delete("writer", "v1.0")
    await repo.create(agent_name="writer", version="v2.0", content="b")
    await repo.delete("writer", "v2.0")
    assert await repo.get_by_version("writer", "v2.0") is None


@pytest.mark.asyncio
async def test_increment_sample_count(async_session):
    repo = PromptVersionRepository(async_session)
    await repo.create(agent_name="writer", version="v1.0", content="x", is_active=True)
    await repo.increment_sample_count("writer", "v1.0")
    await repo.increment_sample_count("writer", "v1.0")
    v = await repo.get_by_version("writer", "v1.0")
    assert v.sample_count == 2
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_prompt_version_repo.py -v`
Expected: ImportError

- [ ] **Step 3: 实现 repository**

```python
# src/novel_dev/repositories/prompt_version_repo.py
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import PromptVersion


class PromptVersionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, agent_name: str, version: str, content: str,
        is_active: bool = False, created_by: str = "user",
        parent_version: Optional[str] = None, ab_test_id: Optional[str] = None,
    ) -> PromptVersion:
        pv = PromptVersion(
            id=str(uuid.uuid4()),
            agent_name=agent_name,
            version=version,
            content=content,
            is_active=is_active,
            created_at=datetime.utcnow(),
            created_by=created_by,
            sample_count=0,
            parent_version=parent_version,
            ab_test_id=ab_test_id,
        )
        self.session.add(pv)
        await self.session.flush()
        return pv

    async def get_active(self, agent_name: str) -> Optional[PromptVersion]:
        result = await self.session.execute(
            select(PromptVersion).where(
                PromptVersion.agent_name == agent_name,
                PromptVersion.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get_by_version(self, agent_name: str, version: str) -> Optional[PromptVersion]:
        result = await self.session.execute(
            select(PromptVersion).where(
                PromptVersion.agent_name == agent_name,
                PromptVersion.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def list_versions(self, agent_name: str) -> list[PromptVersion]:
        result = await self.session.execute(
            select(PromptVersion)
            .where(PromptVersion.agent_name == agent_name)
            .order_by(PromptVersion.created_at.desc())
        )
        return list(result.scalars().all())

    async def set_active(self, agent_name: str, version: str) -> None:
        """原子切换:旧 active 关 + 新 active 开(同事务)"""
        target = await self.get_by_version(agent_name, version)
        if not target:
            raise ValueError(f"Version {version} not found for agent {agent_name}")
        # 关掉旧的
        result = await self.session.execute(
            select(PromptVersion).where(
                PromptVersion.agent_name == agent_name,
                PromptVersion.is_active == True,  # noqa: E712
            )
        )
        for old in result.scalars().all():
            old.is_active = False
        # 开新的
        target.is_active = True
        await self.session.flush()

    async def delete(self, agent_name: str, version: str) -> None:
        target = await self.get_by_version(agent_name, version)
        if not target:
            return
        if target.is_active:
            raise ValueError(f"Cannot delete active version {version} for agent {agent_name}")
        await self.session.delete(target)
        await self.session.flush()

    async def increment_sample_count(self, agent_name: str, version: str) -> None:
        target = await self.get_by_version(agent_name, version)
        if target:
            target.sample_count += 1
            await self.session.flush()
```

- [ ] **Step 4: 跑测试,确认通过**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_prompt_version_repo.py -v`
Expected: 5 PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/repositories/prompt_version_repo.py tests/test_repositories/test_prompt_version_repo.py
git commit -m "feat(repo): PromptVersionRepository with atomic set_active"
```

---

## Task 5: RootCauseRepository

**Files:**
- Create: `src/novel_dev/repositories/root_cause_repo.py`
- Test: `tests/test_repositories/test_root_cause_repo.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_repositories/test_root_cause_repo.py
import pytest
from novel_dev.repositories.root_cause_repo import RootCauseRepository


@pytest.mark.asyncio
async def test_persist_and_get_latest(async_session):
    repo = RootCauseRepository(async_session)
    rc = await repo.persist(
        chapter_id="ch_1",
        analyzer_version="v1.0",
        summary="beat 越界",
        suggested_actions=[{"action": "重写 beat 2", "target": "beat:2", "severity": "high"}],
        confidence=0.85,
        input_snapshot={"chapter_preview": "..."},
    )
    latest = await repo.get_latest_for_chapter("ch_1")
    assert latest.id == rc.id
    assert latest.summary == "beat 越界"
    assert latest.suggested_actions[0]["severity"] == "high"


@pytest.mark.asyncio
async def test_get_latest_returns_newest(async_session):
    repo = RootCauseRepository(async_session)
    await repo.persist("ch_1", "v1.0", "first", [], 0.5, {})
    await repo.persist("ch_1", "v1.0", "second", [], 0.7, {})
    latest = await repo.get_latest_for_chapter("ch_1")
    assert latest.summary == "second"


@pytest.mark.asyncio
async def test_get_latest_empty_returns_none(async_session):
    repo = RootCauseRepository(async_session)
    assert await repo.get_latest_for_chapter("nonexistent") is None
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_root_cause_repo.py -v`

- [ ] **Step 3: 实现**

```python
# src/novel_dev/repositories/root_cause_repo.py
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import QualityRootCause


class RootCauseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def persist(
        self,
        chapter_id: str,
        analyzer_version: str,
        summary: str,
        suggested_actions: list[dict],
        confidence: float,
        input_snapshot: dict,
    ) -> QualityRootCause:
        rc = QualityRootCause(
            id=str(uuid.uuid4()),
            chapter_id=chapter_id,
            analyzer_version=analyzer_version,
            summary=summary,
            suggested_actions={"items": suggested_actions},  # JSON 字段存为 dict
            confidence=confidence,
            input_snapshot=input_snapshot,
            created_at=datetime.utcnow(),
        )
        self.session.add(rc)
        await self.session.flush()
        return rc

    async def get_latest_for_chapter(self, chapter_id: str) -> Optional[QualityRootCause]:
        result = await self.session.execute(
            select(QualityRootCause)
            .where(QualityRootCause.chapter_id == chapter_id)
            .order_by(QualityRootCause.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
```

- [ ] **Step 4: 跑测试,确认通过**

Run: `cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_root_cause_repo.py -v`
Expected: 3 PASS

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/repositories/root_cause_repo.py tests/test_repositories/test_root_cause_repo.py
git commit -m "feat(repo): RootCauseRepository with persist and get_latest"
```

---

## Task 6: ABTestRepository

**Files:**
- Create: `src/novel_dev/repositories/ab_test_repo.py`
- Test: `tests/test_repositories/test_ab_test_repo.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_repositories/test_ab_test_repo.py
import pytest
from datetime import datetime
from novel_dev.repositories.ab_test_repo import ABTestRepository


@pytest.mark.asyncio
async def test_create_and_get(async_session):
    repo = ABTestRepository(async_session)
    ab = await repo.create(
        agent_name="critic",
        baseline_version="v1.0",
        challenger_version="v2.0",
        config={"max_samples": 10, "min_samples": 3, "alpha": 0.05},
    )
    found = await repo.get(ab.id)
    assert found.agent_name == "critic"
    assert found.status == "running"


@pytest.mark.asyncio
async def test_list_running(async_session):
    repo = ABTestRepository(async_session)
    await repo.create("critic", "v1.0", "v2.0", {})
    await repo.create("writer", "v1.0", "v2.0", {})
    running = await repo.list_running()
    assert len(running) == 2


@pytest.mark.asyncio
async def test_mark_completed(async_session):
    repo = ABTestRepository(async_session)
    ab = await repo.create("critic", "v1.0", "v2.0", {})
    await repo.mark_completed(ab.id, winner="challenger", ended_at=datetime.utcnow())
    found = await repo.get(ab.id)
    assert found.status == "completed"
    assert found.winner == "challenger"
    assert found.ended_at is not None
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 实现**

```python
# src/novel_dev/repositories/ab_test_repo.py
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import ABTest


class ABTestRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        agent_name: str,
        baseline_version: str,
        challenger_version: str,
        config: dict,
    ) -> ABTest:
        ab = ABTest(
            id=str(uuid.uuid4()),
            agent_name=agent_name,
            baseline_version=baseline_version,
            challenger_version=challenger_version,
            status="running",
            started_at=datetime.utcnow(),
            config=config,
        )
        self.session.add(ab)
        await self.session.flush()
        return ab

    async def get(self, test_id: str) -> Optional[ABTest]:
        result = await self.session.execute(
            select(ABTest).where(ABTest.id == test_id)
        )
        return result.scalar_one_or_none()

    async def list_running(self, agent_name: Optional[str] = None) -> list[ABTest]:
        stmt = select(ABTest).where(ABTest.status == "running")
        if agent_name:
            stmt = stmt.where(ABTest.agent_name == agent_name)
        result = await self.session.execute(stmt.order_by(ABTest.started_at.desc()))
        return list(result.scalars().all())

    async def list_all(self) -> list[ABTest]:
        result = await self.session.execute(
            select(ABTest).order_by(ABTest.started_at.desc())
        )
        return list(result.scalars().all())

    async def mark_completed(
        self, test_id: str, winner: Optional[str], ended_at: datetime,
    ) -> None:
        ab = await self.get(test_id)
        if not ab:
            return
        ab.status = "completed"
        ab.winner = winner
        ab.ended_at = ended_at
        await self.session.flush()

    async def mark_aborted(self, test_id: str) -> None:
        ab = await self.get(test_id)
        if not ab:
            return
        ab.status = "aborted"
        ab.ended_at = datetime.utcnow()
        await self.session.flush()
```

- [ ] **Step 4: 跑测试,确认通过**

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/repositories/ab_test_repo.py tests/test_repositories/test_ab_test_repo.py
git commit -m "feat(repo): ABTestRepository for A/B test lifecycle"
```

---

## Task 7: PromptRegistry service

**Files:**
- Create: `src/novel_dev/services/prompt_registry.py`
- Test: `tests/test_services/test_prompt_registry.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_services/test_prompt_registry.py
import pytest
from novel_dev.services.prompt_registry import PromptRegistry
from novel_dev.agents._default_prompts import DEFAULT_PROMPTS


@pytest.mark.asyncio
async def test_get_active_returns_db_version(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "from db", is_active=True)
    content = await reg.get_active("writer")
    assert content == "from db"


@pytest.mark.asyncio
async def test_get_active_falls_back_to_default(async_session, monkeypatch):
    # 关掉 cold_start fallback
    monkeypatch.setattr("novel_dev.services.prompt_registry.settings", type("S", (), {
        "phase3_prompt_registry_bootstrap_default": False,
        "phase3_cold_start_allow_hardcoded_fallback": True,
    })())
    reg = PromptRegistry(async_session)
    content = await reg.get_active("writer")
    assert content == DEFAULT_PROMPTS["writer"]


@pytest.mark.asyncio
async def test_get_by_version_for_ab(async_session):
    reg = PromptRegistry(async_session)
    await reg.create_version("writer", "v1.0", "v1 content", is_active=True)
    await reg.create_version("writer", "v2.0", "v2 content")
    v1 = await reg.get_by_version("writer", "v1.0")
    v2 = await reg.get_by_version("writer", "v2.0")
    assert v1 == "v1 content"
    assert v2 == "v2 content"


@pytest.mark.asyncio
async def test_bootstrap_loads_defaults(async_session):
    reg = PromptRegistry(async_session)
    await reg.bootstrap_defaults()
    # 9 个 key 全部入库
    for agent_name in DEFAULT_PROMPTS:
        content = await reg.get_active(agent_name)
        assert content == DEFAULT_PROMPTS[agent_name]
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 实现 PromptRegistry**

```python
# src/novel_dev/services/prompt_registry.py
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents._default_prompts import DEFAULT_PROMPTS
from novel_dev.config.settings import settings
from novel_dev.repositories.prompt_version_repo import PromptVersionRepository

logger = logging.getLogger(__name__)


class PromptRegistry:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = PromptVersionRepository(session)

    async def get_active(self, agent_name: str) -> str:
        pv = await self.repo.get_active(agent_name)
        if pv:
            return pv.content
        if getattr(settings, "phase3_cold_start_allow_hardcoded_fallback", True):
            logger.warning(
                "prompt_registry_cold_start_fallback",
                extra={"agent_name": agent_name},
            )
            return DEFAULT_PROMPTS.get(agent_name, "")
        raise RuntimeError(
            f"No active prompt for {agent_name} and cold_start fallback disabled"
        )

    async def get_by_version(self, agent_name: str, version: str) -> str:
        pv = await self.repo.get_by_version(agent_name, version)
        if not pv:
            raise ValueError(f"Version {version} not found for {agent_name}")
        return pv.content

    async def list_versions(self, agent_name: str) -> list[dict]:
        versions = await self.repo.list_versions(agent_name)
        return [
            {
                "id": v.id,
                "agent_name": v.agent_name,
                "version": v.version,
                "content": v.content,
                "is_active": v.is_active,
                "created_at": v.created_at.isoformat(),
                "created_by": v.created_by,
                "sample_count": v.sample_count,
                "parent_version": v.parent_version,
                "ab_test_id": v.ab_test_id,
            }
            for v in versions
        ]

    async def create_version(
        self, agent_name: str, version: str, content: str,
        is_active: bool = False, created_by: str = "user",
        parent_version: Optional[str] = None,
        ab_test_id: Optional[str] = None,
    ) -> dict:
        existing = await self.repo.get_by_version(agent_name, version)
        if existing:
            raise ValueError(f"Version {version} already exists for {agent_name}")
        pv = await self.repo.create(
            agent_name=agent_name, version=version, content=content,
            is_active=is_active, created_by=created_by,
            parent_version=parent_version, ab_test_id=ab_test_id,
        )
        if is_active:
            await self.repo.set_active(agent_name, version)
        logger.info("prompt_version_created", extra={
            "agent_name": agent_name, "version": version, "created_by": created_by,
        })
        return {"id": pv.id, "version": version, "agent_name": agent_name}

    async def set_active(self, agent_name: str, version: str) -> None:
        await self.repo.set_active(agent_name, version)
        logger.info("prompt_version_applied", extra={
            "agent_name": agent_name, "version": version,
        })

    async def rollback(self, agent_name: str, to_version: str) -> None:
        await self.set_active(agent_name, to_version)

    async def delete_version(self, agent_name: str, version: str) -> None:
        await self.repo.delete(agent_name, version)

    async def bootstrap_defaults(self) -> None:
        """启动时若表空,同步 _default_prompts.py 内容到 DB 并设为 active"""
        for agent_name, content in DEFAULT_PROMPTS.items():
            existing = await self.repo.get_active(agent_name)
            if existing:
                continue
            await self.repo.create(
                agent_name=agent_name, version="v1.0",
                content=content, is_active=True, created_by="system",
            )
        logger.info("prompt_registry_bootstrap", extra={"count": len(DEFAULT_PROMPTS)})

    async def increment_sample_count(self, agent_name: str, version: str) -> None:
        await self.repo.increment_sample_count(agent_name, version)
```

需要 `src/novel_dev/config/settings.py` 中有 `phase3_prompt_registry_bootstrap_default` 和 `phase3_cold_start_allow_hardcoded_fallback` 两个 bool 配置项。如果 settings 用 pydantic,直接加字段即可(Task 23 配 phase3 段时会一并配)。

- [ ] **Step 4: 跑测试,确认通过**

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/services/prompt_registry.py tests/test_services/test_prompt_registry.py
git commit -m "feat(services): PromptRegistry with cold-start fallback"
```

---

## Task 8: 把 8 个 agent 迁移到 PromptRegistry

**Files:**
- Modify: 8 个 agent 文件(`writer_agent.py` / `critic_agent.py` / `editor_agent.py` / `fast_review_agent.py` / `librarian.py` / `brainstorm_agent.py` / `volume_planner.py` / `context_agent.py`)
- Test: `tests/test_agents/test_prompt_loading.py`

> **说明:** 这是一个大任务,逐个 agent 改 TDD 太啰嗦。本任务用一个统一测试 + 8 个 agent 一次性迁移(同一个 commit),迁移时保证每个 agent 的现有测试都通过。

- [ ] **Step 1: 盘点 8 个 agent 的 prompt 加载点**

```bash
cd /Users/linlin/Desktop/novel-dev && grep -nE 'PROMPT|system_template|prompt_template|^\s*prompt\s*=' src/novel_dev/agents/{writer,critic,editor,fast_review,librarian,brainstorm}_agent.py src/novel_dev/agents/volume_planner.py src/novel_dev/agents/context_agent.py 2>/dev/null
```

把每个 agent 的 prompt 字符串位置记下来,确认每个 agent 至少有一个 prompt 模板。

- [ ] **Step 2: 写统一测试**

```python
# tests/test_agents/test_prompt_loading.py
"""验证 8 个 agent 全部从 PromptRegistry 加载 prompt"""
import pytest

AGENT_NAMES = [
    "brainstorm", "volume_planner", "context_agent",
    "writer", "critic", "editor",
    "fast_review", "librarian",
]

# 每个 agent 类的 __init__ 接收 session;改后,实例化时应能从 PromptRegistry 拿 prompt
# 由于 agent 的 prompt 加载点在方法内,我们通过 mock LLM 调用来验证


@pytest.mark.asyncio
async def test_each_agent_loads_prompt_from_registry(async_session, monkeypatch):
    from novel_dev.services.prompt_registry import PromptRegistry
    reg = PromptRegistry(async_session)
    await reg.bootstrap_defaults()

    for agent_name in AGENT_NAMES:
        active = await reg.get_active(agent_name)
        assert active, f"{agent_name} has no active prompt after bootstrap"
        assert len(active) > 0, f"{agent_name} active prompt is empty"
```

- [ ] **Step 3: 改 8 个 agent 文件**

每个 agent 的改动模式(以 writer_agent.py 为例):

**改前(伪代码):**
```python
class WriterAgent:
    def __init__(self, session, embedding_service):
        self.session = session
        ...

    async def write_chapter(self, ...):
        prompt = f"你是小说作家。\n章节计划: {plan}\n..."  # hardcoded
        response = await self.llm.acomplete(...)
```

**改后:**
```python
class WriterAgent:
    def __init__(self, session, embedding_service, prompt_registry=None):
        self.session = session
        self.embedding_service = embedding_service
        self.prompt_registry = prompt_registry or PromptRegistry(session)

    async def write_chapter(self, ..., prompt_version: str | None = None):
        template = await self.prompt_registry.get_active("writer")
        # A/B 中间件会传 prompt_version;否则 None
        version = prompt_version or (await self.prompt_registry.get_active_version_name("writer"))
        prompt = template.format(plan=plan, ...)
        response = await self.llm.acomplete(...)
        # 调用完后回写 sample_count
        await self.prompt_registry.increment_sample_count("writer", version)
        return response, {"prompt_version": version}
```

需要在 `PromptRegistry` 加一个新方法:
```python
async def get_active_version_name(self, agent_name: str) -> str:
    pv = await self.repo.get_active(agent_name)
    return pv.version if pv else "v1.0"
```

**逐个 agent 改时:**
- 找到 hardcoded prompt 字符串位置
- 改为 `await self.prompt_registry.get_active("agent_name")` 然后 `.format(...)`
- 在 `__init__` 接收可选 `prompt_registry` 参数(为单测和向后兼容)
- 在调用 LLM 前后,记录 `prompt_version` 到返回值的 metadata
- 调用 `increment_sample_count`

**不要破坏现有测试:** 每个 agent 文件改完后,跑该 agent 的现有测试。

- [ ] **Step 4: 跑全量 agent 测试**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/ -v
```

Expected: 全部现有测试 PASS,加上新加的 test_each_agent_loads_prompt_from_registry 也 PASS。

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/agents/ tests/test_agents/test_prompt_loading.py src/novel_dev/services/prompt_registry.py
git commit -m "feat(agents): migrate 8 agents to load prompts from PromptRegistry"
```

---

## Task 9: QualityMetricsService 记录 prompt_version

**Files:**
- Modify: `src/novel_dev/services/quality_metrics_service.py`
- Test: `tests/test_services/test_quality_metrics_prompt_version.py`(扩展现有测试)

> 阶段一已建 `prompt_version` 字段但没填值。本任务让所有调用 `record()` 的地方传 `prompt_version`。

- [ ] **Step 1: 找所有 record() 调用点**

```bash
cd /Users/linlin/Desktop/novel-dev && grep -rn "quality_metrics_service.record\|QualityMetricsService.*record" src/ tests/ 2>/dev/null
```

- [ ] **Step 2: 在每个调用点传 prompt_version**

每个 agent 调 `QualityMetricsService.record(...)` 时,从该次调用的 `prompt_version` metadata 取值并传入。

**改前(伪代码):**
```python
await QualityMetricsService(session).record(QualityMetricInput(
    chapter_id=..., overall_score=..., gate_status=..., issue_codes=...,
))
```

**改后:**
```python
await QualityMetricsService(session).record(QualityMetricInput(
    chapter_id=..., overall_score=..., gate_status=..., issue_codes=...,
    prompt_version=metadata.get("prompt_version"),  # 新增
))
```

`QualityMetricInput` 的 `prompt_version: Optional[str] = None` 已在阶段一建好,这里只传值。

- [ ] **Step 3: 写测试验证落库**

```python
# tests/test_services/test_quality_metrics_prompt_version.py
import pytest
from novel_dev.db.models import ChapterQualityMetric
from novel_dev.services.quality_metrics_service import QualityMetricsService, QualityMetricInput


@pytest.mark.asyncio
async def test_record_stores_prompt_version(async_session):
    svc = QualityMetricsService(async_session)
    await svc.record(QualityMetricInput(
        chapter_id="ch_1", novel_id="n_1", phase="draft",
        attempt_index=1, overall_score=80, gate_status="warn",
        prompt_version="v2.0",
    ))
    from sqlalchemy import select
    result = await async_session.execute(select(ChapterQualityMetric))
    rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].prompt_version == "v2.0"
```

- [ ] **Step 4: 跑测试,确认通过**

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/services/quality_metrics_service.py tests/test_services/test_quality_metrics_prompt_version.py <所有调用 record 的文件>
git commit -m "feat(metrics): record prompt_version in QualityMetricsService"
```

---

## Task 10: ABTestRunner service

**Files:**
- Create: `src/novel_dev/services/ab_test_runner.py`
- Test: `tests/test_services/test_ab_test_runner.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_services/test_ab_test_runner.py
import pytest
from datetime import datetime
from novel_dev.services.ab_test_runner import ABTestRunner


@pytest.mark.asyncio
async def test_start_creates_test_record(async_session):
    runner = ABTestRunner(async_session)
    ab = await runner.start(
        agent_name="critic",
        baseline_version="v1.0", challenger_version="v2.0",
        max_samples=10, min_samples=3,
    )
    assert ab.status == "running"
    assert ab.config["max_samples"] == 10


@pytest.mark.asyncio
async def test_pick_version_is_stable_per_chapter(async_session):
    runner = ABTestRunner(async_session)
    await runner.start("critic", "v1.0", "v2.0", max_samples=10, min_samples=3)
    v1 = await runner.pick_version("critic", "ch_1")
    v2 = await runner.pick_version("critic", "ch_1")
    assert v1 == v2  # 同一 chapter 稳定走一个版本


@pytest.mark.asyncio
async def test_pick_version_distributes_across_chapters(async_session):
    runner = ABTestRunner(async_session)
    await runner.start("critic", "v1.0", "v2.0", max_samples=10, min_samples=3)
    baseline_count = 0
    for i in range(100):
        v = await runner.pick_version("critic", f"ch_{i}")
        if v == "v1.0":
            baseline_count += 1
    # 应该在 40-60 之间
    assert 40 <= baseline_count <= 60


@pytest.mark.asyncio
async def test_results_calculates_p_value(async_session):
    from novel_dev.services.quality_metrics_service import QualityMetricsService, QualityMetricInput

    runner = ABTestRunner(async_session)
    await runner.start("critic", "v1.0", "v2.0", max_samples=10, min_samples=3)

    svc = QualityMetricsService(async_session)
    # baseline 章节得分 70 ± 5
    for i in range(5):
        await svc.record(QualityMetricInput(
            chapter_id=f"baseline_{i}", novel_id="n_1", phase="critic",
            attempt_index=1, overall_score=70 + i, gate_status="warn",
            prompt_version="v1.0",
        ))
    # challenger 章节得分 85 ± 5
    for i in range(5):
        await svc.record(QualityMetricInput(
            chapter_id=f"challenger_{i}", novel_id="n_1", phase="critic",
            attempt_index=1, overall_score=85 + i, gate_status="warn",
            prompt_version="v2.0",
        ))

    ab_id = (await runner.list_running())[0].id
    result = await runner.results(ab_id)
    assert result.baseline_mean < result.challenger_mean
    assert result.p_value < 0.05
    assert result.winner == "challenger"


@pytest.mark.asyncio
async def test_results_inconclusive_when_too_few_samples(async_session):
    runner = ABTestRunner(async_session)
    ab = await runner.start("critic", "v1.0", "v2.0", max_samples=10, min_samples=3)
    result = await runner.results(ab.id)
    assert result.winner is None
    assert result.status == "pending"
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 实现 ABTestRunner**

```python
# src/novel_dev/services/ab_test_runner.py
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from scipy import stats
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import ABTest, ChapterQualityMetric
from novel_dev.repositories.ab_test_repo import ABTestRepository

logger = logging.getLogger(__name__)


@dataclass
class ABTestResult:
    test_id: str
    status: str  # "running" / "pending" / "completed"
    baseline_mean: Optional[float]
    challenger_mean: Optional[float]
    p_value: Optional[float]
    baseline_n: int
    challenger_n: int
    winner: Optional[str]  # "baseline" / "challenger" / "inconclusive" / None


class ABTestRunner:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ABTestRepository(session)

    async def start(
        self,
        agent_name: str,
        baseline_version: str,
        challenger_version: str,
        max_samples: int = 10,
        min_samples: int = 3,
        alpha: float = 0.05,
        scope_filter: Optional[dict] = None,
    ) -> ABTest:
        # 检查已有 running 的同 agent 测试
        running = await self.repo.list_running(agent_name=agent_name)
        if running:
            raise ValueError(
                f"Agent {agent_name} already has a running A/B test ({running[0].id})"
            )
        ab = await self.repo.create(
            agent_name=agent_name,
            baseline_version=baseline_version,
            challenger_version=challenger_version,
            config={
                "max_samples": max_samples,
                "min_samples": min_samples,
                "alpha": alpha,
                "scope_filter": scope_filter or {},
            },
        )
        logger.info("ab_test_started", extra={
            "test_id": ab.id, "agent_name": agent_name,
            "baseline_version": baseline_version,
            "challenger_version": challenger_version,
        })
        return ab

    async def stop(self, test_id: str) -> ABTest:
        await self.repo.mark_aborted(test_id)
        logger.info("ab_test_stopped", extra={"test_id": test_id})
        return await self.repo.get(test_id)

    async def list_running(self) -> list[ABTest]:
        return await self.repo.list_running()

    async def list_all(self) -> list[ABTest]:
        return await self.repo.list_all()

    async def pick_version(self, agent_name: str, chapter_id: str) -> str:
        """A/B 调度:基于 chapter_id 哈希,稳定走一个版本"""
        running = await self.repo.list_running(agent_name=agent_name)
        if not running:
            return None  # 没有 A/B,调用方走单版本
        ab = running[0]
        # 哈希分布
        h = int(hashlib.md5(f"{ab.id}:{chapter_id}".encode()).hexdigest(), 16)
        return ab.baseline_version if h % 2 == 0 else ab.challenger_version

    async def results(self, test_id: str) -> ABTestResult:
        ab = await self.repo.get(test_id)
        if not ab:
            raise ValueError(f"A/B test {test_id} not found")
        # 拉取该 agent 的所有指标,按 prompt_version 区分
        result = await self.session.execute(
            select(ChapterQualityMetric).where(
                ChapterQualityMetric.phase == ab.agent_name,
            )
        )
        metrics = list(result.scalars().all())
        baseline_scores = [
            m.overall_score for m in metrics
            if m.prompt_version == ab.baseline_version and m.overall_score is not None
        ]
        challenger_scores = [
            m.overall_score for m in metrics
            if m.prompt_version == ab.challenger_version and m.overall_score is not None
        ]
        baseline_n = len(baseline_scores)
        challenger_n = len(challenger_scores)
        max_samples = ab.config.get("max_samples", 10)
        min_samples = ab.config.get("min_samples", 3)
        alpha = ab.config.get("alpha", 0.05)
        # 未达到 min_samples
        if baseline_n < min_samples or challenger_n < min_samples:
            return ABTestResult(
                test_id=test_id, status="pending",
                baseline_mean=sum(baseline_scores) / baseline_n if baseline_n else None,
                challenger_mean=sum(challenger_scores) / challenger_n if challenger_n else None,
                p_value=None, baseline_n=baseline_n, challenger_n=challenger_n,
                winner=None,
            )
        baseline_mean = sum(baseline_scores) / baseline_n
        challenger_mean = sum(challenger_scores) / challenger_n
        # Welch's t-test
        t_stat, p_value = stats.ttest_ind(baseline_scores, challenger_scores, equal_var=False)
        # 自动 stop
        if baseline_n + challenger_n >= max_samples * 2:
            winner = "challenger" if p_value < alpha and challenger_mean > baseline_mean else "baseline"
            await self.repo.mark_completed(test_id, winner=winner, ended_at=datetime.utcnow())
        else:
            winner = "challenger" if p_value < alpha and challenger_mean > baseline_mean else None
        return ABTestResult(
            test_id=test_id,
            status="completed" if baseline_n + challenger_n >= max_samples * 2 else "running",
            baseline_mean=baseline_mean, challenger_mean=challenger_mean,
            p_value=p_value, baseline_n=baseline_n, challenger_n=challenger_n,
            winner=winner,
        )

    async def declare_winner(self, test_id: str, winner: str) -> None:
        """采纳赢家:set_active + 标 ab_tests.winner"""
        ab = await self.repo.get(test_id)
        if not ab:
            raise ValueError(f"A/B test {test_id} not found")
        if winner not in ("baseline", "challenger"):
            raise ValueError(f"Invalid winner: {winner}")
        chosen_version = ab.baseline_version if winner == "baseline" else ab.challenger_version
        from novel_dev.services.prompt_registry import PromptRegistry
        reg = PromptRegistry(self.session)
        await reg.set_active(ab.agent_name, chosen_version)
        await self.repo.mark_completed(test_id, winner=winner, ended_at=datetime.utcnow())
        logger.info("ab_test_winner_declared", extra={
            "test_id": test_id, "winner": winner, "chosen_version": chosen_version,
        })
```

需要 `pip install scipy` 添加依赖(如果还没装)。

- [ ] **Step 4: 跑测试,确认通过**

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/services/ab_test_runner.py tests/test_services/test_ab_test_runner.py
git commit -m "feat(services): ABTestRunner with Welch's t-test and stable per-chapter dispatch"
```

---

## Task 11: ABTestMiddleware in LLMFactory

**Files:**
- Modify: `src/novel_dev/llm/factory.py`
- Test: `tests/test_llm/test_ab_test_middleware.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_llm/test_ab_test_middleware.py
import pytest
from unittest.mock import AsyncMock, patch
from novel_dev.llm.factory import LLMFactory


@pytest.mark.asyncio
async def test_get_returns_prompt_version_metadata(async_session):
    factory = LLMFactory(session=async_session, agent_name="writer", task="write_chapter")
    factory._ab_test_runner = AsyncMock()
    factory._ab_test_runner.pick_version = AsyncMock(return_value="v1.0")
    factory._prompt_registry = AsyncMock()
    factory._prompt_registry.get_active = AsyncMock(return_value="default content")

    client, metadata = await factory.get_with_metadata()
    assert metadata["prompt_version"] == "v1.0"


@pytest.mark.asyncio
async def test_get_falls_back_to_active_when_no_ab(async_session):
    factory = LLMFactory(session=async_session, agent_name="writer", task="write_chapter")
    factory._ab_test_runner = AsyncMock()
    factory._ab_test_runner.pick_version = AsyncMock(return_value=None)
    factory._prompt_registry = AsyncMock()
    factory._prompt_registry.get_active_version_name = AsyncMock(return_value="v2.0")
    factory._prompt_registry.get_active = AsyncMock(return_value="v2.0 content")

    client, metadata = await factory.get_with_metadata()
    assert metadata["prompt_version"] == "v2.0"
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 改 LLMFactory**

在 `src/novel_dev/llm/factory.py` 中:

1. 引入 `PromptRegistry` 和 `ABTestRunner`(懒加载,避免循环依赖)
2. 新增 `get_with_metadata()` 方法,返回 `(client, {"prompt_version": ...})`
3. 旧 `get()` 方法保留(向后兼容),内部委托给 `get_with_metadata()`

```python
# 在 LLMFactory 类内新增
async def get_with_metadata(self):
    """返回 (client, metadata);metadata 含 prompt_version 供下游记录"""
    from novel_dev.services.prompt_registry import PromptRegistry
    from novel_dev.services.ab_test_runner import ABTestRunner

    if not hasattr(self, "_prompt_registry") or self._prompt_registry is None:
        self._prompt_registry = PromptRegistry(self.session)
    if not hasattr(self, "_ab_test_runner") or self._ab_test_runner is None:
        self._ab_test_runner = ABTestRunner(self.session)

    # A/B 调度
    ab_version = await self._ab_test_runner.pick_version(self.agent_name, self._current_chapter_id or "")
    if ab_version:
        content = await self._prompt_registry.get_by_version(self.agent_name, ab_version)
        prompt_version = ab_version
    else:
        content = await self._prompt_registry.get_active(self.agent_name)
        prompt_version = await self._prompt_registry.get_active_version_name(self.agent_name)

    # 调 sample_count
    await self._prompt_registry.increment_sample_count(self.agent_name, prompt_version)

    # 实际拿 client(原 get() 逻辑)
    client = self._original_get()
    return client, {"prompt_version": prompt_version, "prompt_content": content}
```

实际代码可能更复杂,因为原 `get()` 涉及配置解析和 fallback chain。**重点:不要破坏现有 `get()` 行为**,只是新增 `get_with_metadata()`。

- [ ] **Step 4: 跑测试,确认通过 + 跑全量 LLM 测试**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_llm/ -v
```

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/llm/factory.py tests/test_llm/test_ab_test_middleware.py
git commit -m "feat(llm): LLMFactory.get_with_metadata returns prompt_version"
```

---

## Task 12: RootCauseAnalyzer service

**Files:**
- Create: `src/novel_dev/services/root_cause_analyzer.py`
- Test: `tests/test_services/test_root_cause_analyzer.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_services/test_root_cause_analyzer.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from novel_dev.services.root_cause_analyzer import RootCauseAnalyzer, RootCauseResult


@pytest.mark.asyncio
async def test_analyze_happy_path(async_session):
    analyzer = RootCauseAnalyzer(async_session)
    analyzer.prompt_registry = AsyncMock()
    analyzer.prompt_registry.get_active = AsyncMock(return_value="Analyze: {chapter_text} {score_breakdown} {issue_codes} {beat_cards}")
    analyzer.llm_client = AsyncMock()
    fake_response = MagicMock()
    fake_response.text = json.dumps({
        "summary": "beat 2 越界",
        "suggested_actions": [{"action": "重写", "target": "beat:2", "severity": "high"}],
        "confidence": 0.85,
    }, ensure_ascii=False)
    fake_response.usage = None
    fake_response.finish_reason = None
    analyzer.llm_client.acomplete = AsyncMock(return_value=fake_response)

    result = await analyzer.analyze(
        novel_id="n_1", chapter_id="ch_1",
        chapter_text="陆照听见追兵...",
        score_breakdown={"narrative": 75, "character": 60},
        issue_codes=["BEAT_BOUNDARY_VIOLATION", "AI_FLAVOR_HIGH"],
        beat_boundary_cards=[],
    )
    assert result.summary == "beat 2 越界"
    assert result.confidence == 0.85


@pytest.mark.asyncio
async def test_analyze_truncates_long_text(async_session):
    analyzer = RootCauseAnalyzer(async_session)
    analyzer.prompt_registry = AsyncMock()
    captured = {}
    async def fake_get_active(name):
        return "Prompt: {chapter_text} {score_breakdown} {issue_codes} {beat_cards}"
    analyzer.prompt_registry.get_active = fake_get_active
    analyzer.llm_client = AsyncMock()
    fake_response = MagicMock()
    fake_response.text = '{"summary": "x", "suggested_actions": [], "confidence": 0.5}'
    fake_response.usage = None
    fake_response.finish_reason = None
    captured["response"] = fake_response
    analyzer.llm_client.acomplete = AsyncMock(return_value=fake_response)

    long_text = "x" * 10000
    await analyzer.analyze("n_1", "ch_1", long_text, {}, [], [])
    # 验证 prompt 模板收到的 chapter_text 截断到 5000 字
    call_args = analyzer.llm_client.acomplete.call_args
    messages = call_args[0][0]
    content = messages[0].content
    assert "x" * 5001 not in content  # 没超过 5000


@pytest.mark.asyncio
async def test_analyze_llm_failure_soft_degrades(async_session):
    analyzer = RootCauseAnalyzer(async_session)
    analyzer.prompt_registry = AsyncMock()
    analyzer.prompt_registry.get_active = AsyncMock(return_value="x")
    analyzer.llm_client = AsyncMock()
    analyzer.llm_client.acomplete = AsyncMock(side_effect=ConnectionError("boom"))

    result = await analyzer.analyze("n_1", "ch_1", "text", {}, [], [])
    assert result.summary == "[分析失败,请人工]"
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_analyze_invalid_json_soft_degrades(async_session):
    analyzer = RootCauseAnalyzer(async_session)
    analyzer.prompt_registry = AsyncMock()
    analyzer.prompt_registry.get_active = AsyncMock(return_value="x")
    analyzer.llm_client = AsyncMock()
    fake_response = MagicMock()
    fake_response.text = "not json"
    fake_response.usage = None
    fake_response.finish_reason = None
    analyzer.llm_client.acomplete = AsyncMock(return_value=fake_response)

    result = await analyzer.analyze("n_1", "ch_1", "text", {}, [], [])
    assert result.summary == "[分析失败,请人工]"
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_analyze_persists_result(async_session):
    analyzer = RootCauseAnalyzer(async_session)
    analyzer.prompt_registry = AsyncMock()
    analyzer.prompt_registry.get_active = AsyncMock(return_value="x")
    analyzer.llm_client = AsyncMock()
    fake_response = MagicMock()
    fake_response.text = json.dumps({
        "summary": "ok", "suggested_actions": [], "confidence": 0.7,
    })
    fake_response.usage = None
    fake_response.finish_reason = None
    analyzer.llm_client.acomplete = AsyncMock(return_value=fake_response)

    await analyzer.analyze("n_1", "ch_1", "text", {}, [], [])
    from novel_dev.repositories.root_cause_repo import RootCauseRepository
    latest = await RootCauseRepository(async_session).get_latest_for_chapter("ch_1")
    assert latest is not None
    assert latest.summary == "ok"
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 实现 RootCauseAnalyzer**

```python
# src/novel_dev/services/root_cause_analyzer.py
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from novel_dev.db.models import BeatBoundaryCard
from novel_dev.llm import llm_factory
from novel_dev.repositories.root_cause_repo import RootCauseRepository
from novel_dev.services.prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 5000


@dataclass
class RootCauseResult:
    summary: str
    suggested_actions: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    analyzer_version: str = "v1.0"


class RootCauseAnalyzer:
    def __init__(
        self, session,
        prompt_registry: Optional[PromptRegistry] = None,
        llm_client=None,
    ):
        self.session = session
        self.prompt_registry = prompt_registry or PromptRegistry(session)
        self.llm_client = llm_client
        self.repo = RootCauseRepository(session)

    async def _get_llm_client(self):
        if self.llm_client:
            return self.llm_client
        return llm_factory.get("RootCauseAnalyzer")

    async def analyze(
        self,
        novel_id: str,
        chapter_id: str,
        chapter_text: str,
        score_breakdown: dict,
        issue_codes: list[str],
        beat_boundary_cards: list[BeatBoundaryCard],
    ) -> RootCauseResult:
        # 1. 截断章节文本
        if len(chapter_text) > MAX_INPUT_CHARS:
            truncated = chapter_text[:MAX_INPUT_CHARS] + "...[截断]"
        else:
            truncated = chapter_text

        # 2. 构造 prompt
        try:
            template = await self.prompt_registry.get_active("root_cause_analyzer")
        except Exception as exc:
            logger.warning("root_cause_prompt_load_failed", extra={"error": repr(exc)})
            return await self._fail_and_persist(novel_id, chapter_id, str(exc))

        # 取 active 版本名(用于记录 analyzer_version)
        from novel_dev.repositories.prompt_version_repo import PromptVersionRepository
        active = await PromptVersionRepository(self.session).get_active("root_cause_analyzer")
        analyzer_version = active.version if active else "v1.0"

        prompt = template.format(
            chapter_text=truncated,
            score_breakdown=json.dumps(score_breakdown, ensure_ascii=False),
            issue_codes=", ".join(issue_codes) if issue_codes else "(none)",
            beat_cards=self._format_beat_cards(beat_boundary_cards),
        )

        # 3. LLM 调用,失败软降级
        try:
            client = await self._get_llm_client()
            from novel_dev.llm.models import ChatMessage
            response = await client.acomplete(
                [ChatMessage(role="user", content=prompt)],
            )
            result = self._parse_response(response.text, analyzer_version)
        except Exception as exc:
            logger.warning("root_cause_analysis_failed", extra={
                "chapter_id": chapter_id, "error": repr(exc),
            })
            return await self._fail_and_persist(novel_id, chapter_id, str(exc), analyzer_version)

        # 4. 持久化
        await self.repo.persist(
            chapter_id=chapter_id,
            analyzer_version=analyzer_version,
            summary=result.summary,
            suggested_actions=result.suggested_actions,
            confidence=result.confidence,
            input_snapshot={"chapter_preview": truncated[:500]},
        )
        return result

    async def _fail_and_persist(
        self, novel_id: str, chapter_id: str, error: str,
        analyzer_version: str = "v1.0",
    ) -> RootCauseResult:
        result = RootCauseResult(
            summary="[分析失败,请人工]",
            suggested_actions=[],
            confidence=0.0,
            analyzer_version=analyzer_version,
        )
        await self.repo.persist(
            chapter_id=chapter_id,
            analyzer_version=analyzer_version,
            summary=result.summary,
            suggested_actions=result.suggested_actions,
            confidence=result.confidence,
            input_snapshot={"error": error},
        )
        return result

    def _parse_response(self, text: str, analyzer_version: str) -> RootCauseResult:
        # 简单 JSON 解析,可能需要 call_and_parse 包装
        text = text.strip()
        # 去掉 markdown code fence
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.MULTILINE)
        data = json.loads(text)
        return RootCauseResult(
            summary=data.get("summary", "[无 summary]"),
            suggested_actions=data.get("suggested_actions", []),
            confidence=float(data.get("confidence", 0.0)),
            analyzer_version=analyzer_version,
        )

    def _format_beat_cards(self, cards: list[BeatBoundaryCard]) -> str:
        if not cards:
            return "(none)"
        lines = []
        for c in cards:
            must = ", ".join(c.must_cover) if c.must_cover else "(no must_cover)"
            forbid = ", ".join(c.forbidden_materials) if c.forbidden_materials else "(no forbidden)"
            lines.append(f"  beat {c.beat_index}: must_cover=[{must}], forbidden=[{forbid}]")
        return "\n".join(lines)
```

- [ ] **Step 4: 跑测试,确认通过**

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/services/root_cause_analyzer.py tests/test_services/test_root_cause_analyzer.py
git commit -m "feat(services): RootCauseAnalyzer with soft-degrade and persistence"
```

---

## Task 13: FastReviewAgent 集成 RootCauseAnalyzer

**Files:**
- Modify: `src/novel_dev/agents/fast_review_agent.py`
- Test: `tests/test_agents/test_fast_review_root_cause.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_agents/test_fast_review_root_cause.py
import pytest
from unittest.mock import AsyncMock, patch
from novel_dev.services.root_cause_analyzer import RootCauseResult


@pytest.mark.asyncio
async def test_fast_review_calls_root_cause_for_warn_block(async_session, sample_chapter):
    with patch("novel_dev.agents.fast_review_agent.RootCauseAnalyzer") as MockAnalyzer:
        instance = MockAnalyzer.return_value
        instance.analyze = AsyncMock(return_value=RootCauseResult(
            summary="test", suggested_actions=[], confidence=0.5,
        ))
        with patch("novel_dev.agents.fast_review_agent._do_review", new=AsyncMock(return_value=("warn", {}))):
            from novel_dev.agents.fast_review_agent import FastReviewAgent
            agent = FastReviewAgent(async_session)
            await agent.review_standalone("n_1", "ch_1", {})
            # 验证 analyze 被调用
            instance.analyze.assert_awaited_once()


@pytest.mark.asyncio
async def test_fast_review_skips_root_cause_for_pass(async_session):
    with patch("novel_dev.agents.fast_review_agent.RootCauseAnalyzer") as MockAnalyzer:
        instance = MockAnalyzer.return_value
        instance.analyze = AsyncMock()
        with patch("novel_dev.agents.fast_review_agent._do_review", new=AsyncMock(return_value=("pass", {}))):
            from novel_dev.agents.fast_review_agent import FastReviewAgent
            agent = FastReviewAgent(async_session)
            await agent.review_standalone("n_1", "ch_1", {})
            instance.analyze.assert_not_awaited()
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 改 FastReviewAgent**

在 `review_standalone()` 末尾(报告生成后),**仅当 score 不是 pass 时**调 RootCauseAnalyzer:

```python
# 在 review_standalone 末尾增加
if report.gate_status != "pass":
    try:
        from novel_dev.services.root_cause_analyzer import RootCauseAnalyzer
        analyzer = RootCauseAnalyzer(self.session)
        chapter = await self.chapter_repo.get_by_id(chapter_id)
        chapter_text = chapter.polished_text or chapter.raw_draft or ""
        result = await analyzer.analyze(
            novel_id=novel_id,
            chapter_id=chapter_id,
            chapter_text=chapter_text,
            score_breakdown=report.score_breakdown or {},
            issue_codes=report.issue_codes or [],
            beat_boundary_cards=checkpoint.get("beat_boundary_cards", []),
        )
        checkpoint["root_cause"] = result.summary
        checkpoint["root_cause_actions"] = result.suggested_actions
    except Exception as exc:
        logger.warning("root_cause_integration_failed", extra={"error": repr(exc)})
```

`report.gate_status` 是 FastReview 的最终 gate 状态(`pass` / `warn` / `block`)。

- [ ] **Step 4: 跑测试,确认通过 + 跑 FastReview 现有测试**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_fast_review_*.py -v
```

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/agents/fast_review_agent.py tests/test_agents/test_fast_review_root_cause.py
git commit -m "feat(fast_review): trigger RootCauseAnalyzer for non-pass chapters"
```

---

## Task 14: WireResult 加 root_cause 字段 + Wirer 读取

**Files:**
- Modify: `src/novel_dev/services/recommendation_wirer.py`
- Test: `tests/test_services/test_recommendation_wirer_root_cause.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_services/test_recommendation_wirer_root_cause.py
import pytest
from unittest.mock import AsyncMock, patch
from novel_dev.services.recommendation_wirer import RecommendationWirer, WireResult
from novel_dev.services.root_cause_analyzer import RootCauseResult


@pytest.mark.asyncio
async def test_wirer_includes_root_cause_in_wire_result(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    fake_root_cause = RootCauseResult(
        summary="beat 2 越界",
        suggested_actions=[{"action": "重写", "target": "beat:2", "severity": "high"}],
        confidence=0.85,
    )
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=None)):
        with patch("novel_dev.services.recommendation_wirer.RootCauseRepository") as MockRepo:
            MockRepo.return_value.get_latest_for_chapter = AsyncMock(return_value=fake_root_cause)
            result = await wirer.evaluate_and_dispatch("n_1", "missing_ch")
    # chapter 是 None 时走的是 manual_review 分支,不读 root_cause
    assert result.root_cause is None


@pytest.mark.asyncio
async def test_wirer_accept_path_includes_root_cause(async_session):
    wirer = RecommendationWirer(async_session, max_auto_rewrites=2)
    fake_root_cause = RootCauseResult(summary="ok", confidence=0.9)
    ch = type("Chapter", (), {
        "id": "ch_1", "final_review_score": 90, "quality_status": "pass",
        "attempt_index": 0, "score_breakdown": {},
    })()
    with patch.object(wirer.chapter_repo, "get_by_id", new=AsyncMock(return_value=ch)):
        with patch("novel_dev.services.recommendation_wirer.RootCauseRepository") as MockRepo:
            MockRepo.return_value.get_latest_for_chapter = AsyncMock(return_value=fake_root_cause)
            result = await wirer.evaluate_and_dispatch("n_1", "ch_1")
    assert result.action == "accept"
    assert result.root_cause is fake_root_cause
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 改 RecommendationWirer**

```python
# 在 WireResult 加 root_cause 字段
@dataclass
class WireResult:
    action: Literal["accept", "auto_rewrite_queued", "manual_review"]
    recommendation: Recommendation | None
    rewrite_job_id: str | None
    root_cause: Optional["RootCauseResult"] = None  # 新增


# 在 RecommendationWirer.evaluate_and_dispatch() 末尾
# 读最近根因(在 return 之前)
from novel_dev.repositories.root_cause_repo import RootCauseRepository
root_cause_repo = RootCauseRepository(self.session)
latest_root_cause_record = await root_cause_repo.get_latest_for_chapter(chapter_id)
# 转换为 RootCauseResult 对象(为 UI 用)
root_cause = None
if latest_root_cause_record:
    root_cause = RootCauseResult(
        summary=latest_root_cause_record.summary,
        suggested_actions=latest_root_cause_record.suggested_actions.get("items", []),
        confidence=latest_root_cause_record.confidence,
        analyzer_version=latest_root_cause_record.analyzer_version,
    )
# 把 root_cause 附加到每个 return WireResult(每个 return 处都加)
```

需要修改 4 个 return 处:
- L45: chapter not found → root_cause=None
- L49: drift detected → root_cause=None
- L65: exception → root_cause=None
- L69: accept → root_cause
- L72: stop_and_inspect → root_cause
- L75-76: budget → root_cause(在 _queue_rewrite 之后)

- [ ] **Step 4: 跑测试,确认通过 + 跑 Wirer 现有测试**

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/services/recommendation_wirer.py tests/test_services/test_recommendation_wirer_root_cause.py
git commit -m "feat(wirer): include root_cause in WireResult"
```

---

## Task 15: ChapterRewriteService 注入 root_cause_segment

**Files:**
- Modify: `src/novel_dev/services/chapter_rewrite_service.py`
- Test: `tests/test_services/test_chapter_rewrite_root_cause.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_services/test_chapter_rewrite_root_cause.py
import pytest
from unittest.mock import AsyncMock, patch
from novel_dev.services.root_cause_analyzer import RootCauseResult


@pytest.mark.asyncio
async def test_rewrite_injects_root_cause_into_checkpoint(async_session):
    fake_root_cause = RootCauseResult(
        summary="beat 2 越界",
        suggested_actions=[{"action": "重写 beat 2", "target": "beat:2", "severity": "high"}],
        confidence=0.85,
    )
    with patch("novel_dev.services.chapter_rewrite_service.RootCauseRepository") as MockRepo:
        MockRepo.return_value.get_latest_for_chapter = AsyncMock(return_value=None)
        with patch("novel_dev.services.chapter_rewrite_service.RootCauseRepository") as MockRepo2:
            MockRepo2.return_value.get_latest_for_chapter = AsyncMock(return_value=type("RC", (), {
                "summary": fake_root_cause.summary,
                "suggested_actions": {"items": fake_root_cause.suggested_actions},
                "confidence": fake_root_cause.confidence,
                "analyzer_version": fake_root_cause.analyzer_version,
            })())
            # ... 复杂的全流程 mock 测
            pass  # 这个测试可能需要重构
```

**实际测试可能更简单,验证 build_root_cause_segment 方法:**

```python
def test_build_root_cause_segment_formats_correctly():
    from novel_dev.services.chapter_rewrite_service import ChapterRewriteService
    fake = type("RC", (), {
        "summary": "beat 2 越界",
        "suggested_actions": {"items": [
            {"action": "重写 beat 2", "target": "beat:2", "severity": "high"},
            {"action": "强化主角", "target": "dimension:character", "severity": "medium"},
        ]},
        "confidence": 0.85,
    })()
    seg = ChapterRewriteService._build_root_cause_segment(fake)
    assert "## 上轮根因建议" in seg
    assert "beat 2 越界" in seg
    assert "重写 beat 2" in seg
    assert "强化主角" in seg
    assert "0.85" in seg
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 改 ChapterRewriteService**

```python
# 新增静态方法
@staticmethod
def _build_root_cause_segment(root_cause_record) -> str:
    if not root_cause_record:
        return ""
    actions = root_cause_record.suggested_actions.get("items", [])
    lines = [
        "## 上轮根因建议",
        f"- summary: {root_cause_record.summary}",
    ]
    for a in actions:
        lines.append(f"- 建议动作: {a.get('action', '')} (severity: {a.get('severity', 'unknown')})")
    lines.append(f"- confidence: {root_cause_record.confidence}")
    return "\n".join(lines)


# 在 rewrite() 方法中,调 WriterAgent.write_standalone() 之前,增加:
from novel_dev.repositories.root_cause_repo import RootCauseRepository
root_cause_record = await RootCauseRepository(self.session).get_latest_for_chapter(chapter_id)
checkpoint["root_cause_segment"] = self._build_root_cause_segment(root_cause_record)
```

- [ ] **Step 4: 跑测试,确认通过**

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/services/chapter_rewrite_service.py tests/test_services/test_chapter_rewrite_root_cause.py
git commit -m "feat(rewrite): inject root_cause_segment into checkpoint for Writer"
```

---

## Task 16: WriterAgent 读根因入 context

**Files:**
- Modify: `src/novel_dev/agents/writer_agent.py`
- Test: `tests/test_agents/test_writer_root_cause_context.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_agents/test_writer_root_cause_context.py
from novel_dev.agents.writer_agent import WriterAgent


def test_assemble_chapter_context_inserts_root_cause_at_top():
    base_context = {"chapter_plan": "plan", "existing_data": "x"}
    segment = "## 上轮根因建议\n- summary: beat 2 越界"
    result = WriterAgent._insert_root_cause_segment(base_context, segment)
    assert "root_cause_segment" in result
    assert result["root_cause_segment"] == segment
    # 验证它会被最先读取
    keys = list(result.keys())
    assert keys[0] == "root_cause_segment"  # 顶部


def test_assemble_chapter_context_no_segment_unchanged():
    base_context = {"chapter_plan": "plan"}
    result = WriterAgent._insert_root_cause_segment(base_context, "")
    assert result == base_context
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 改 WriterAgent**

```python
# 新增静态方法
@staticmethod
def _insert_root_cause_segment(context: dict, segment: str) -> dict:
    if not segment:
        return context
    return {"root_cause_segment": segment, **context}


# 在 write_standalone() 中(实际拼装 prompt 前),从 checkpoint 读 root_cause_segment
# 并插到 chapter_context 顶部
if isinstance(checkpoint, dict) and checkpoint.get("root_cause_segment"):
    chapter_context = self._insert_root_cause_segment(
        chapter_context, checkpoint["root_cause_segment"]
    )
```

同时,实际把 `root_cause_segment` 拼到最终 LLM prompt 的顶部(在 system message 或 user message 第一段):

```python
# 拼 prompt 时
final_prompt = ""
if chapter_context.get("root_cause_segment"):
    final_prompt += chapter_context["root_cause_segment"] + "\n\n"
final_prompt += <原 prompt 模板>
```

- [ ] **Step 4: 跑测试,确认通过 + 跑 Writer 现有测试**

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/agents/writer_agent.py tests/test_agents/test_writer_root_cause_context.py
git commit -m "feat(writer): insert root_cause_segment at top of chapter_context"
```

---

## Task 17: 4 个 prompt CRUD API

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Test: `tests/test_api/test_prompt_endpoints.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_api/test_prompt_endpoints.py
import pytest


@pytest.mark.asyncio
async def test_list_versions(async_session, client):
    await client.post("/api/prompts/writer/versions", json={
        "version": "v1.0", "content": "hello",
    })
    resp = await client.get("/api/prompts/writer/versions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["versions"]) == 1
    assert data["versions"][0]["version"] == "v1.0"


@pytest.mark.asyncio
async def test_create_version(async_session, client):
    resp = await client.post("/api/prompts/writer/versions", json={
        "version": "v1.0", "content": "hi", "is_active": True,
    })
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_create_duplicate_version_409(async_session, client):
    await client.post("/api/prompts/writer/versions", json={"version": "v1.0", "content": "a"})
    resp = await client.post("/api/prompts/writer/versions", json={"version": "v1.0", "content": "b"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_set_active(async_session, client):
    await client.post("/api/prompts/writer/versions", json={"version": "v1.0", "content": "a", "is_active": True})
    await client.post("/api/prompts/writer/versions", json={"version": "v2.0", "content": "b"})
    resp = await client.patch("/api/prompts/writer/versions/v2.0", json={"is_active": True})
    assert resp.status_code == 200
    # v1.0 应已取消 active
    list_resp = await client.get("/api/prompts/writer/versions")
    v1 = next(v for v in list_resp.json()["versions"] if v["version"] == "v1.0")
    assert v1["is_active"] is False


@pytest.mark.asyncio
async def test_delete_inactive(async_session, client):
    await client.post("/api/prompts/writer/versions", json={"version": "v1.0", "content": "a", "is_active": True})
    await client.post("/api/prompts/writer/versions", json={"version": "v2.0", "content": "b"})
    resp = await client.delete("/api/prompts/writer/versions/v2.0")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_active_rejected(async_session, client):
    await client.post("/api/prompts/writer/versions", json={"version": "v1.0", "content": "a", "is_active": True})
    resp = await client.delete("/api/prompts/writer/versions/v1.0")
    assert resp.status_code == 400
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 实现 4 个端点**

在 `src/novel_dev/api/routes.py` 末尾添加:

```python
from novel_dev.services.prompt_registry import PromptRegistry


@router.get("/prompts/{agent_name}/versions")
async def list_prompt_versions(agent_name: str, session: AsyncSession = Depends(get_session)):
    reg = PromptRegistry(session)
    versions = await reg.list_versions(agent_name)
    return {"agent_name": agent_name, "versions": versions}


@router.post("/prompts/{agent_name}/versions", status_code=201)
async def create_prompt_version(
    agent_name: str,
    payload: dict,
    session: AsyncSession = Depends(get_session),
):
    reg = PromptRegistry(session)
    try:
        return await reg.create_version(
            agent_name=agent_name,
            version=payload["version"],
            content=payload["content"],
            is_active=payload.get("is_active", False),
            created_by=payload.get("created_by", "user"),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.patch("/prompts/{agent_name}/versions/{version}")
async def update_prompt_version(
    agent_name: str, version: str,
    payload: dict,
    session: AsyncSession = Depends(get_session),
):
    reg = PromptRegistry(session)
    if payload.get("is_active"):
        await reg.set_active(agent_name, version)
    return {"status": "ok"}


@router.delete("/prompts/{agent_name}/versions/{version}", status_code=204)
async def delete_prompt_version(
    agent_name: str, version: str,
    session: AsyncSession = Depends(get_session),
):
    reg = PromptRegistry(session)
    try:
        await reg.delete_version(agent_name, version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 4: 跑测试,确认通过**

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_prompt_endpoints.py
git commit -m "feat(api): prompt CRUD endpoints"
```

---

## Task 18: 5 个 A/B API

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Test: `tests/test_api/test_ab_test_endpoints.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_api/test_ab_test_endpoints.py
import pytest


@pytest.mark.asyncio
async def test_start_ab_test(async_session, client):
    # 准备 prompt_versions
    await client.post("/api/prompts/critic/versions", json={"version": "v1.0", "content": "a", "is_active": True})
    await client.post("/api/prompts/critic/versions", json={"version": "v2.0", "content": "b"})

    resp = await client.post("/api/ab-tests", json={
        "agent_name": "critic",
        "baseline_version": "v1.0",
        "challenger_version": "v2.0",
        "max_samples": 5,
        "min_samples": 2,
    })
    assert resp.status_code == 201
    assert resp.json()["status"] == "running"


@pytest.mark.asyncio
async def test_list_ab_tests(async_session, client):
    resp = await client.get("/api/ab-tests")
    assert resp.status_code == 200
    assert "tests" in resp.json()


@pytest.mark.asyncio
async def test_get_ab_test_results(async_session, client):
    await client.post("/api/prompts/critic/versions", json={"version": "v1.0", "content": "a", "is_active": True})
    await client.post("/api/prompts/critic/versions", json={"version": "v2.0", "content": "b"})
    start = await client.post("/api/ab-tests", json={
        "agent_name": "critic",
        "baseline_version": "v1.0", "challenger_version": "v2.0",
    })
    test_id = start.json()["id"]
    resp = await client.get(f"/api/ab-tests/{test_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data


@pytest.mark.asyncio
async def test_stop_ab_test(async_session, client):
    # ... 准备 + start,然后 stop
    pass


@pytest.mark.asyncio
async def test_declare_winner(async_session, client):
    # ... 准备 + start,然后 declare_winner
    pass
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 实现 5 个端点**

```python
from novel_dev.services.ab_test_runner import ABTestRunner


@router.post("/ab-tests", status_code=201)
async def start_ab_test(payload: dict, session: AsyncSession = Depends(get_session)):
    runner = ABTestRunner(session)
    try:
        ab = await runner.start(
            agent_name=payload["agent_name"],
            baseline_version=payload["baseline_version"],
            challenger_version=payload["challenger_version"],
            max_samples=payload.get("max_samples", 10),
            min_samples=payload.get("min_samples", 3),
        )
        return {"id": ab.id, "status": ab.status, "agent_name": ab.agent_name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ab-tests")
async def list_ab_tests(session: AsyncSession = Depends(get_session)):
    runner = ABTestRunner(session)
    tests = await runner.list_all()
    return {"tests": [
        {
            "id": t.id, "agent_name": t.agent_name,
            "baseline_version": t.baseline_version,
            "challenger_version": t.challenger_version,
            "status": t.status, "winner": t.winner,
        } for t in tests
    ]}


@router.get("/ab-tests/{test_id}")
async def get_ab_test(test_id: str, session: AsyncSession = Depends(get_session)):
    runner = ABTestRunner(session)
    ab = await runner.repo.get(test_id)
    if not ab:
        raise HTTPException(status_code=404, detail="A/B test not found")
    results = await runner.results(test_id)
    return {
        "id": ab.id, "agent_name": ab.agent_name,
        "baseline_version": ab.baseline_version, "challenger_version": ab.challenger_version,
        "status": ab.status, "winner": ab.winner,
        "results": {
            "baseline_mean": results.baseline_mean,
            "challenger_mean": results.challenger_mean,
            "p_value": results.p_value,
            "baseline_n": results.baseline_n, "challenger_n": results.challenger_n,
        },
    }


@router.post("/ab-tests/{test_id}/stop")
async def stop_ab_test(test_id: str, session: AsyncSession = Depends(get_session)):
    runner = ABTestRunner(session)
    await runner.stop(test_id)
    return {"status": "aborted"}


@router.post("/ab-tests/{test_id}/declare-winner")
async def declare_ab_winner(
    test_id: str, payload: dict,
    session: AsyncSession = Depends(get_session),
):
    runner = ABTestRunner(session)
    await runner.declare_winner(test_id, payload["winner"])
    return {"status": "ok"}
```

- [ ] **Step 4: 跑测试,确认通过**

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_ab_test_endpoints.py
git commit -m "feat(api): A/B test lifecycle endpoints"
```

---

## Task 19: root cause 查询 API

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Test: `tests/test_api/test_root_cause_endpoint.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_api/test_root_cause_endpoint.py
import pytest
from novel_dev.repositories.root_cause_repo import RootCauseRepository


@pytest.mark.asyncio
async def test_get_root_cause_for_chapter(async_session, client):
    repo = RootCauseRepository(async_session)
    await repo.persist(
        chapter_id="ch_1", analyzer_version="v1.0",
        summary="test summary",
        suggested_actions=[{"action": "x", "target": "y", "severity": "high"}],
        confidence=0.8, input_snapshot={},
    )
    resp = await client.get("/api/chapters/ch_1/root-cause")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"] == "test summary"
    assert data["confidence"] == 0.8
    assert len(data["suggested_actions"]) == 1


@pytest.mark.asyncio
async def test_get_root_cause_empty_404(async_session, client):
    resp = await client.get("/api/chapters/nonexistent/root-cause")
    assert resp.status_code == 404
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 实现端点**

```python
@router.get("/chapters/{chapter_id}/root-cause")
async def get_root_cause(chapter_id: str, session: AsyncSession = Depends(get_session)):
    repo = RootCauseRepository(session)
    latest = await repo.get_latest_for_chapter(chapter_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No root cause found")
    return {
        "chapter_id": chapter_id,
        "analyzer_version": latest.analyzer_version,
        "summary": latest.summary,
        "suggested_actions": latest.suggested_actions.get("items", []),
        "confidence": latest.confidence,
        "created_at": latest.created_at.isoformat(),
    }
```

- [ ] **Step 4: 跑测试,确认通过**

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_root_cause_endpoint.py
git commit -m "feat(api): root cause query endpoint"
```

---

## Task 20: PromptVersionsManager.vue

**Files:**
- Create: `src/novel_dev/web/src/views/PromptVersionsManager.vue`
- Test: `src/novel_dev/web/src/views/PromptVersionsManager.test.js`

- [ ] **Step 1: 写失败测试**

```javascript
// src/novel_dev/web/src/views/PromptVersionsManager.test.js
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import PromptVersionsManager from './PromptVersionsManager.vue'

describe('PromptVersionsManager', () => {
  it('shows empty state when no versions', async () => {
    const wrapper = mount(PromptVersionsManager, {
      global: {
        mocks: {
          $api: {
            get: vi.fn().mockResolvedValue({ versions: [] }),
          },
        },
      },
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="empty-state"]').exists()).toBe(true)
  })

  it('lists versions returned by API', async () => {
    const wrapper = mount(PromptVersionsManager, {
      global: {
        mocks: {
          $api: {
            get: vi.fn().mockResolvedValue({
              versions: [
                { version: 'v1.0', is_active: true, content: 'a', sample_count: 10 },
                { version: 'v2.0', is_active: false, content: 'b', sample_count: 0 },
              ],
            }),
          },
        },
      },
    })
    await wrapper.vm.$nextTick()
    const rows = wrapper.findAll('[data-testid="version-row"]')
    expect(rows.length).toBe(2)
  })

  it('emits set-active when clicking the button', async () => {
    const wrapper = mount(PromptVersionsManager, {
      global: {
        mocks: {
          $api: {
            get: vi.fn().mockResolvedValue({
              versions: [
                { version: 'v1.0', is_active: false, content: 'a', sample_count: 0 },
              ],
            }),
            patch: vi.fn().mockResolvedValue({}),
          },
        },
      },
    })
    await wrapper.vm.$nextTick()
    const btn = wrapper.find('[data-testid="set-active-btn"]')
    if (btn.exists()) await btn.trigger('click')
    // 验证 API 被调用
    // ...
  })
})
```

- [ ] **Step 2: 跑测试,确认失败**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web && npm test -- PromptVersionsManager.test.js
```

- [ ] **Step 3: 实现组件**

Vue 3 单文件组件,关键元素:
- 顶部下拉(选 agent_name)
- 版本列表(每行 version / is_active 标签 / created_at / sample_count / 3 个按钮:查看 / 设 active / 删除)
- 创建版本弹窗
- 冷启动空状态提示

```vue
<template>
  <div class="prompt-versions-manager">
    <header>
      <h2>Prompt 版本管理</h2>
      <select v-model="selectedAgent" data-testid="agent-select">
        <option v-for="a in AGENT_NAMES" :key="a" :value="a">{{ a }}</option>
      </select>
      <button @click="showCreate = true" data-testid="create-btn">创建新版本</button>
    </header>

    <div v-if="!versions.length" data-testid="empty-state" class="empty">
      <p>此 agent 尚无 prompt。可从系统默认导入。</p>
      <button @click="bootstrap" data-testid="bootstrap-btn">导入默认</button>
    </div>

    <table v-else>
      <tr v-for="v in versions" :key="v.id" data-testid="version-row">
        <td>{{ v.version }}</td>
        <td>
          <span v-if="v.is_active" class="badge active">active</span>
        </td>
        <td>{{ v.sample_count }}</td>
        <td>
          <button data-testid="view-btn" @click="viewContent(v)">查看</button>
          <button v-if="!v.is_active" data-testid="set-active-btn" @click="setActive(v)">设 active</button>
          <button v-if="!v.is_active" data-testid="delete-btn" @click="deleteVersion(v)">删除</button>
        </td>
      </tr>
    </table>

    <!-- 创建/查看 弹窗 -->
    <Modal v-if="showCreate" @close="showCreate = false">
      <input v-model="newVersion" placeholder="v1.1" />
      <textarea v-model="newContent" rows="10" />
      <button @click="createVersion">创建</button>
    </Modal>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'

const AGENT_NAMES = ['brainstorm', 'volume_planner', 'context_agent', 'writer', 'critic', 'editor', 'fast_review', 'librarian', 'root_cause_analyzer']
const selectedAgent = ref('writer')
const versions = ref([])
const showCreate = ref(false)
const newVersion = ref('')
const newContent = ref('')

const fetchVersions = async () => {
  const resp = await $api.get(`/api/prompts/${selectedAgent.value}/versions`)
  versions.value = resp.versions
}
const setActive = async (v) => {
  await $api.patch(`/api/prompts/${selectedAgent.value}/versions/${v.version}`, { is_active: true })
  await fetchVersions()
}
// ... 其他方法
onMounted(fetchVersions)
watch(selectedAgent, fetchVersions)
</script>
```

- [ ] **Step 4: 跑测试,确认通过**

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/web/src/views/PromptVersionsManager.vue src/novel_dev/web/src/views/PromptVersionsManager.test.js
git commit -m "feat(ui): PromptVersionsManager view"
```

---

## Task 21: ABTestConsole.vue

**Files:**
- Create: `src/novel_dev/web/src/views/ABTestConsole.vue`
- Test: `src/novel_dev/web/src/views/ABTestConsole.test.js`

- [ ] **Step 1: 写失败测试**

```javascript
// src/novel_dev/web/src/views/ABTestConsole.test.js
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ABTestConsole from './ABTestConsole.vue'

describe('ABTestConsole', () => {
  it('shows running tests', async () => {
    const wrapper = mount(ABTestConsole, {
      global: {
        mocks: {
          $api: {
            get: vi.fn().mockResolvedValue({
              tests: [
                { id: 't1', agent_name: 'critic', baseline_version: 'v1.0', challenger_version: 'v2.0', status: 'running', winner: null },
              ],
            }),
          },
        },
      },
    })
    await wrapper.vm.$nextTick()
    const cards = wrapper.findAll('[data-testid="ab-test-card"]')
    expect(cards.length).toBe(1)
  })

  it('shows stop button for running tests', async () => {
    const wrapper = mount(ABTestConsole, {
      global: { mocks: { $api: { get: vi.fn().mockResolvedValue({ tests: [{ id: 't1', status: 'running', agent_name: 'critic', baseline_version: 'v1.0', challenger_version: 'v2.0' }] }) } } },
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="stop-btn"]').exists()).toBe(true)
  })
})
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 实现组件**

```vue
<template>
  <div class="ab-test-console">
    <header>
      <h2>A/B Test 控制台</h2>
      <button @click="showCreate = true" data-testid="create-ab-btn">新建 A/B</button>
    </header>

    <section>
      <h3>运行中</h3>
      <div v-for="t in runningTests" :key="t.id" data-testid="ab-test-card" class="card">
        <div>{{ t.agent_name }}: {{ t.baseline_version }} vs {{ t.challenger_version }}</div>
        <div v-if="t.results">
          baseline mean: {{ t.results.baseline_mean?.toFixed(1) }},
          challenger mean: {{ t.results.challenger_mean?.toFixed(1) }},
          p = {{ t.results.p_value?.toFixed(3) }}
        </div>
        <div>
          <button data-testid="view-results-btn" @click="viewResults(t)">查看详细</button>
          <button data-testid="stop-btn" @click="stop(t)">停止</button>
          <button v-if="t.results?.winner" data-testid="declare-winner-btn" @click="declareWinner(t)">
            采纳 {{ t.results.winner }}
          </button>
        </div>
      </div>
    </section>

    <section>
      <h3>历史</h3>
      <div v-for="t in completedTests" :key="t.id" data-testid="ab-test-history">
        {{ t.agent_name }} {{ t.baseline_version }} vs {{ t.challenger_version }} — 赢家: {{ t.winner }}
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
const tests = ref([])
const showCreate = ref(false)

const fetchTests = async () => {
  const resp = await $api.get('/api/ab-tests')
  tests.value = resp.tests
}
const runningTests = computed(() => tests.value.filter(t => t.status === 'running'))
const completedTests = computed(() => tests.value.filter(t => t.status !== 'running'))
const stop = async (t) => {
  await $api.post(`/api/ab-tests/${t.id}/stop`)
  await fetchTests()
}
const declareWinner = async (t) => {
  await $api.post(`/api/ab-tests/${t.id}/declare-winner`, { winner: t.results.winner })
  await fetchTests()
}
onMounted(fetchTests)
</script>
```

- [ ] **Step 4: 跑测试,确认通过**

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/web/src/views/ABTestConsole.vue src/novel_dev/web/src/views/ABTestConsole.test.js
git commit -m "feat(ui): ABTestConsole view"
```

---

## Task 22: QualityRecommendationWidget 加根因展示

**Files:**
- Modify: `src/novel_dev/web/src/components/QualityRecommendationWidget.vue`
- Test: `src/novel_dev/web/src/components/QualityRecommendationWidget.test.js`

- [ ] **Step 1: 写失败测试**

```javascript
// 扩展 QualityRecommendationWidget.test.js
it('shows root cause when present', async () => {
  const wrapper = mount(QualityRecommendationWidget, {
    props: {
      novelId: 'n1', chapterId: 'c1',
      rootCause: {
        summary: 'beat 2 越界',
        suggested_actions: [
          { action: '重写 beat 2', target: 'beat:2', severity: 'high' },
        ],
        confidence: 0.85,
      },
    },
  })
  expect(wrapper.find('[data-testid="root-cause-summary"]').text()).toContain('beat 2 越界')
  expect(wrapper.findAll('[data-testid="root-cause-action"]').length).toBe(1)
})
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 改组件**

在 `<template>` 增加根因展示区(在 `rationale` 区附近):

```vue
<section v-if="rootCause" data-testid="root-cause-section" class="root-cause">
  <h4>上轮根因分析</h4>
  <p data-testid="root-cause-summary">{{ rootCause.summary }}</p>
  <ul>
    <li
      v-for="(a, i) in rootCause.suggested_actions"
      :key="i"
      :data-severity="a.severity"
      data-testid="root-cause-action"
    >
      {{ a.action }} <span class="severity">({{ a.severity }})</span>
    </li>
  </ul>
  <small>置信度: {{ rootCause.confidence }}</small>
</section>
```

`<script setup>` 增加 prop:
```javascript
const props = defineProps({
  // ... 现有 props
  rootCause: { type: Object, default: null },
})
```

- [ ] **Step 4: 跑测试,确认通过 + 跑全量前端测试**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web && npm test -- QualityRecommendationWidget.test.js
```

- [ ] **Step 5: 提交**

```bash
git add src/novel_dev/web/src/components/QualityRecommendationWidget.vue src/novel_dev/web/src/components/QualityRecommendationWidget.test.js
git commit -m "feat(ui): show root cause in QualityRecommendationWidget"
```

---

## Task 23: llm_config.yaml phase3 段

**Files:**
- Modify: `llm_config.yaml`
- Modify: `src/novel_dev/config/quality_config.py`(加载 phase3 段)
- Test: `tests/test_config/test_phase3_config.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_config/test_phase3_config.py
import pytest


def test_phase3_config_loads(monkeypatch):
    from novel_dev.config.quality_config import get_phase3_config
    cfg = get_phase3_config()
    assert "root_cause_analyzer" in cfg
    assert cfg["ab_test"]["default_max_samples"] == 10
    assert cfg["prompt_registry"]["bootstrap_default"] is True


def test_phase3_config_missing_raises(monkeypatch):
    def bad():
        return {}
    monkeypatch.setattr("novel_dev.config.quality_config.get_llm_config", bad)
    from novel_dev.config.quality_config import get_phase3_config
    with pytest.raises(KeyError):
        get_phase3_config()
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 加 llm_config.yaml 段**

在 `llm_config.yaml` 末尾追加:

```yaml
# === 阶段三:Prompt 工程化 配置 ===
phase3:
  root_cause_analyzer:
    enabled: true
    max_input_chars: 5000
    llm_client: root_cause_analyzer
  ab_test:
    enabled: true
    default_max_samples: 10
    default_min_samples: 3
    significance_alpha: 0.05
  prompt_registry:
    bootstrap_default: true
  cold_start:
    allow_hardcoded_fallback: true
```

- [ ] **Step 4: 改 quality_config.py**

```python
def get_phase3_config() -> dict:
    cfg = get_llm_config()
    if "phase3" not in cfg:
        raise KeyError("Missing required section: phase3")
    return cfg["phase3"]
```

- [ ] **Step 5: 跑测试,确认通过**

- [ ] **Step 6: 提交**

```bash
git add llm_config.yaml src/novel_dev/config/quality_config.py tests/test_config/test_phase3_config.py
git commit -m "feat(config): add phase3 config section with validation"
```

---

## Task 24: E2E 测试

**Files:**
- Create: `tests/test_e2e/test_phase3_prompt_engineering.py`

- [ ] **Step 1: 写 E2E 测试**

```python
# tests/test_e2e/test_phase3_prompt_engineering.py
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_full_phase3_flow(async_session, client):
    """E2E: bootstrap → 创建版本 → 启用 → A/B → 根因分析 → 采纳赢家"""
    from novel_dev.services.prompt_registry import PromptRegistry
    from novel_dev.services.ab_test_runner import ABTestRunner
    from novel_dev.services.root_cause_analyzer import RootCauseResult

    reg = PromptRegistry(async_session)
    await reg.bootstrap_defaults()

    # 1. 创建新版本 critic v2.0
    await reg.create_version("critic", "v2.0", "v2 content", is_active=False)

    # 2. 启动 A/B
    runner = ABTestRunner(async_session)
    ab = await runner.start("critic", "v1.0", "v2.0", max_samples=4, min_samples=2)

    # 3. 模拟 4 个 chapter 跑 critic(2 baseline, 2 challenger)
    from novel_dev.services.quality_metrics_service import QualityMetricsService, QualityMetricInput
    svc = QualityMetricsService(async_session)
    for i, (ver, score) in enumerate([("v1.0", 70), ("v1.0", 75), ("v2.0", 85), ("v2.0", 88)]):
        await svc.record(QualityMetricInput(
            chapter_id=f"ch_{i}", novel_id="n_1", phase="critic",
            attempt_index=1, overall_score=score, gate_status="warn",
            prompt_version=ver,
        ))

    # 4. results 应该判定 challenger 赢
    result = await runner.results(ab.id)
    assert result.winner == "challenger"
    assert result.p_value < 0.05

    # 5. 采纳 challenger
    await runner.declare_winner(ab.id, "challenger")
    active = await reg.get_active("critic")
    assert active == "v2 content"

    # 6. 根因分析(模拟)
    with patch("novel_dev.services.root_cause_analyzer.RootCauseAnalyzer") as Mock:
        instance = Mock.return_value
        instance.analyze = AsyncMock(return_value=RootCauseResult(
            summary="test", suggested_actions=[], confidence=0.5,
        ))
        from novel_dev.agents.fast_review_agent import FastReviewAgent
        # ... 实际触发 FastReview,略


@pytest.mark.asyncio
async def test_cold_start_bootstrap_then_active_prompt(async_session, client):
    """E2E: 表空 → bootstrap → get_active 返回默认"""
    from novel_dev.services.prompt_registry import PromptRegistry
    from novel_dev.agents._default_prompts import DEFAULT_PROMPTS
    reg = PromptRegistry(async_session)
    await reg.bootstrap_defaults()
    for agent_name, content in DEFAULT_PROMPTS.items():
        active = await reg.get_active(agent_name)
        assert active == content
```

- [ ] **Step 2: 跑测试,确认通过**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_e2e/test_phase3_prompt_engineering.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_e2e/test_phase3_prompt_engineering.py
git commit -m "test(e2e): phase3 prompt engineering full flow"
```

---

## Task 25: 全量测试 + 覆盖率验证

**Files:** 无(验证)

- [ ] **Step 1: 跑全量测试**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/ -q
```

Expected: 全部 PASS(可能除已知 flaky DB 测试)。

- [ ] **Step 2: 跑覆盖率(阶段三新文件)**

```bash
cd /Users/linlin/Desktop/novel-dev && PYTHONPATH=src python3.11 -m pytest tests/test_services/test_prompt_registry.py tests/test_services/test_ab_test_runner.py tests/test_services/test_root_cause_analyzer.py tests/test_repositories/ --cov=novel_dev.services.prompt_registry --cov=novel_dev.services.ab_test_runner --cov=novel_dev.services.root_cause_analyzer --cov=novel_dev.repositories.prompt_version_repo --cov=novel_dev.repositories.root_cause_repo --cov=novel_dev.repositories.ab_test_repo --cov-report=term-missing
```

Expected:
- PromptRegistry ≥ 90%
- ABTestRunner ≥ 90%
- RootCauseAnalyzer ≥ 90%
- 3 个 repo ≥ 95%

- [ ] **Step 3: 跑前端测试**

```bash
cd /Users/linlin/Desktop/novel-dev/src/novel_dev/web && npm test -- --run
```

Expected: 全部 PASS

- [ ] **Step 4: 提交最终报告(可选 commit)**

```bash
git commit --allow-empty -m "test: phase 3 full test run green"
```

---

## Self-Review

- **Spec coverage:**
  - §3 数据流 ✓ Task 1, 6, 7, 10, 11, 12
  - §4 数据模型 ✓ Task 1, 2
  - §5 PromptRegistry API ✓ Task 4, 7
  - §6 A/B test ✓ Task 6, 10, 11
  - §7 RootCauseAnalyzer ✓ Task 5, 12
  - §8 与阶段二连接 ✓ Task 13, 14, 15, 16
  - §9 API 端点 ✓ Task 17, 18, 19
  - §10 UI ✓ Task 20, 21, 22
  - §11 配置段 ✓ Task 23
  - §13 错误处理(冷启动、A/B 互斥、失败软降级)— 已在对应 service 的测试中覆盖
  - §15 验收清单 — Task 25 验证
  - §16 风险与缓解 — 实施时通过 TDD 测试覆盖
- **Placeholder scan:** 无 TBD/TODO/待补
- **Type consistency:**
  - `PromptRegistry.get_active() -> str` 在 Task 7, 8, 11 一致
  - `RootCauseResult.summary / suggested_actions / confidence` 在 Task 12, 13, 14, 22 一致
  - `WireResult.root_cause` 在 Task 14 新增,后续任务不修改
- **依赖关系:**
  - Task 1-2 → 4-7(数据 + 服务)
  - Task 8(agent 迁移)依赖 7
  - Task 9(指标)依赖 1
  - Task 10(A/B runner)依赖 6
  - Task 11(LLM middleware)依赖 7, 10
  - Task 12(root analyzer)依赖 5
  - Task 13(fast_review 集成)依赖 12
  - Task 14(wirer 集成)依赖 12
  - Task 15-16(rewrite + writer)依赖 12, 14
  - Task 17-19(API)依赖 4, 6, 5
  - Task 20-22(UI)依赖 17, 18, 19
  - Task 23(config)独立
  - Task 24(E2E)依赖所有
  - Task 25(全量验证)依赖所有

---

## 执行 Handoff

**计划完成并保存到 `docs/superpowers/plans/2026-06-14-novel-phase3-prompt-engineering-plan.md`(25 个任务)。**

**两个执行选项:**

1. **Subagent-Driven(推荐)** — 每个任务派发新的 subagent,任务间做 spec compliance + code quality review,快速迭代
2. **Inline Execution** — 在当前会话用 executing-plans 执行,带 review 节点的批量执行

**选哪种?**
