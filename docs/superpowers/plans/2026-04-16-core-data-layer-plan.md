# Core Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the PostgreSQL-backed knowledge base, Python SDK, MCP Server, REST API, and state machine for the novel writing agent.

**Architecture:** SQLAlchemy 2.0 models + Alembic migrations for schema versioning. Repository pattern for data access. FastAPI for REST. MCP Python SDK for tool exposure. NovelDirector manages state in `novel_state` table for checkpoint/resume.

**Tech Stack:** Python 3.11+, PostgreSQL 16 + pgvector, SQLAlchemy 2.0, Alembic, FastAPI, pytest-asyncio, MCP Python SDK

---

## File Structure

```
novel-dev/
├── pyproject.toml
├── alembic.ini
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── src/novel_dev/
│   ├── __init__.py
│   ├── config.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   └── models.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── entity_repo.py
│   │   ├── version_repo.py
│   │   ├── relationship_repo.py
│   │   ├── timeline_repo.py
│   │   ├── spaceline_repo.py
│   │   ├── foreshadowing_repo.py
│   │   ├── chapter_repo.py
│   │   ├── novel_state_repo.py
│   │   └── document_repo.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── entity_service.py
│   │   ├── chapter_service.py
│   │   ├── novel_state_service.py
│   │   └── document_service.py
│   ├── mcp_server/
│   │   ├── __init__.py
│   │   └── server.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── librarian.py
│   │   └── director.py
│   └── storage/
│       ├── __init__.py
│       └── markdown_sync.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_repositories/
    │   ├── __init__.py
    │   ├── test_entity_repo.py
    │   ├── test_version_repo.py
    │   ├── test_timeline_repo.py
    │   ├── test_foreshadowing_repo.py
    │   ├── test_chapter_repo.py
    │   └── test_novel_state_repo.py
    ├── test_services/
    │   ├── __init__.py
    │   ├── test_entity_service.py
    │   └── test_chapter_service.py
    ├── test_api/
    │   ├── __init__.py
    │   └── test_routes.py
    └── test_agents/
        ├── __init__.py
        └── test_librarian.py
```

---

## Task 1: Project Bootstrap

**Files:**
- Create: `pyproject.toml`
- Create: `src/novel_dev/__init__.py`
- Create: `tests/__init__.py`
- Create: `README.md`

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "novel-dev"
version = "0.1.0"
description = "Auto novel writing agent core data layer"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy[asyncio]>=2.0.0",
    "alembic>=1.13.0",
    "asyncpg>=0.29.0",
    "pgvector-sqlalchemy>=0.2.0",
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "mcp>=1.0.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.26.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Create directory structure**

```bash
mkdir -p src/novel_dev/{db,repositories,services,mcp_server,api,agents,storage}
mkdir -p tests/{test_repositories,test_services,test_api,test_agents}
touch src/novel_dev/__init__.py
touch tests/__init__.py
```

- [ ] **Step 3: Install dependencies**

```bash
pip install -e ".[dev]"
```

Expected: packages install successfully, no errors.

- [ ] **Step 4: Verify Python import works**

```bash
python -c "import novel_dev; print('OK')"
```

Expected: prints `OK`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md src/ tests/
git commit -m "chore: bootstrap project structure and dependencies"
```

---

## Task 2: Configuration Module

**Files:**
- Create: `src/novel_dev/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py
import os


def test_database_url_from_env():
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
    from novel_dev.config import Settings
    settings = Settings()
    assert settings.database_url == "postgresql+asyncpg://test:test@localhost/test"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError: cannot import name 'Settings' from 'novel_dev.config'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/novel_dev/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://localhost/novel_dev"
    markdown_output_dir: str = "./novel_output"

    class Config:
        env_prefix = ""
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_config.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/config.py tests/test_config.py
git commit -m "feat: add pydantic settings module"
```

---

## Task 3: Database Engine & Session

**Files:**
- Create: `src/novel_dev/db/__init__.py`
- Create: `src/novel_dev/db/engine.py`
- Test: `tests/test_repositories/__init__.py`
- Test: `tests/test_repositories/test_engine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_repositories/test_engine.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.engine import async_session_maker


@pytest.mark.asyncio
async def test_async_session_can_be_created():
    async with async_session_maker() as session:
        assert isinstance(session, AsyncSession)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_repositories/test_engine.py -v
```

Expected: `ImportError: cannot import name 'async_session_maker' from 'novel_dev.db.engine'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/novel_dev/db/engine.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from novel_dev.config import Settings

settings = Settings()
engine = create_async_engine(settings.database_url, echo=False, future=True)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_repositories/test_engine.py -v
```

Expected: PASS (connection may fail if no DB, but import should work)

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/db/engine.py tests/test_repositories/test_engine.py
git commit -m "feat: add async database engine and session maker"
```

---

## Task 4: SQLAlchemy Models

**Files:**
- Create: `src/novel_dev/db/models.py`
- Test: `tests/test_repositories/test_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_repositories/test_models.py
from sqlalchemy import inspect

from novel_dev.db.models import Entity, EntityVersion, Chapter, NovelState


def test_entity_table_name():
    assert Entity.__tablename__ == "entities"


def test_version_table_name():
    assert EntityVersion.__tablename__ == "entity_versions"


def test_chapter_table_name():
    assert Chapter.__tablename__ == "chapters"


def test_novel_state_table_name():
    assert NovelState.__tablename__ == "novel_state"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_repositories/test_models.py -v
```

Expected: `ImportError: cannot import name 'Entity' from 'novel_dev.db.models'`

- [ ] **Step 3: Write SQLAlchemy models**

```python
# src/novel_dev/db/models.py
from typing import List, Optional
from datetime import datetime

from sqlalchemy import (
    ForeignKey, Text, Integer, Boolean, JSON, TIMESTAMP, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at_chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    versions: Mapped[List["EntityVersion"]] = relationship(back_populates="entity", order_by="EntityVersion.version")


class EntityVersion(Base):
    __tablename__ = "entity_versions"
    __table_args__ = (UniqueConstraint("entity_id", "version", name="uix_entity_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[dict] = mapped_column(JSON, nullable=False)
    diff_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)

    entity: Mapped["Entity"] = relationship(back_populates="versions")


class EntityRelationship(Base):
    __tablename__ = "entity_relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    target_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    relation_type: Mapped[str] = mapped_column(Text, nullable=False)
    metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at_chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)


class Timeline(Base):
    __tablename__ = "timeline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tick: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    anchor_event_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Spaceline(Base):
    __tablename__ = "spaceline"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("spaceline.id"), nullable=True)
    narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class Foreshadowing(Base):
    __tablename__ = "foreshadowings"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    埋下_chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    埋下_time_tick: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    埋下_location_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    相关人物_ids: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    回收条件: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    回收状态: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    recovered_chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recovered_event_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    回收影响: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class NovelState(Base):
    __tablename__ = "novel_state"

    novel_id: Mapped[str] = mapped_column(Text, primary_key=True)
    current_phase: Mapped[str] = mapped_column(Text, nullable=False)
    current_volume_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_chapter_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checkpoint_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("volume_id", "chapter_number", name="uix_volume_chapter"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    volume_id: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    raw_draft: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    polished_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    score_overall: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score_breakdown: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    review_feedback: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    fast_review_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fast_review_feedback: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class NovelDocument(Base):
    __tablename__ = "novel_documents"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    novel_id: Mapped[str] = mapped_column(Text, nullable=False)
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    vector_embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(1536), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_repositories/test_models.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/db/models.py tests/test_repositories/test_models.py
git commit -m "feat: add sqlalchemy models for all core tables"
```

---

## Task 5: Alembic Setup & Initial Migration

**Files:**
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/20260416_initial_schema.py`

- [ ] **Step 1: Initialize Alembic**

```bash
alembic init migrations
```

- [ ] **Step 2: Modify alembic.ini**

Edit `alembic.ini`:
```ini
[alembic]
script_location = migrations
prepend_sys_path = src

# Template for migration file names
file_template = %%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s

# Use async driver
sqlalchemy.url = postgresql+asyncpg://localhost/novel_dev
```

- [ ] **Step 3: Modify migrations/env.py for async**

Replace `migrations/env.py` with:

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from novel_dev.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Generate initial migration**

Ensure PostgreSQL is running locally with `novel_dev` database created.

```bash
createdb novel_dev 2>/dev/null || true
alembic revision --autogenerate -m "initial_schema"
```

- [ ] **Step 5: Verify migration file was created**

```bash
ls migrations/versions/
```

Expected: a file like `20260416_abcd1234_initial_schema.py`

- [ ] **Step 6: Apply migration**

```bash
alembic upgrade head
```

Expected: success, no errors.

- [ ] **Step 7: Commit**

```bash
git add alembic.ini migrations/
git commit -m "feat: setup alembic and generate initial schema migration"
```

---

## Task 6: Entity Repository

**Files:**
- Create: `src/novel_dev/repositories/entity_repo.py`
- Test: `tests/test_repositories/test_entity_repo.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_repositories/test_entity_repo.py
import pytest

from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.db.models import Entity


@pytest.mark.asyncio
async def test_create_entity(async_session):
    repo = EntityRepository(async_session)
    entity = await repo.create("char_001", "character", "Lin Feng")
    assert entity.id == "char_001"
    assert entity.name == "Lin Feng"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_repositories/test_entity_repo.py -v
```

Expected: ImportError for `EntityRepository`

- [ ] **Step 3: Add conftest.py with async_session fixture**

```python
# tests/conftest.py
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.engine import engine
from novel_dev.db.models import Base


@pytest_asyncio.fixture
async def async_session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        yield session
        await session.rollback()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
```

- [ ] **Step 4: Write EntityRepository**

```python
# src/novel_dev/repositories/entity_repo.py
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import Entity


class EntityRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, entity_id: str, entity_type: str, name: str, created_at_chapter_id: Optional[str] = None) -> Entity:
        entity = Entity(
            id=entity_id,
            type=entity_type,
            name=name,
            created_at_chapter_id=created_at_chapter_id,
        )
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def get_by_id(self, entity_id: str) -> Optional[Entity]:
        result = await self.session.execute(select(Entity).where(Entity.id == entity_id))
        return result.scalar_one_or_none()

    async def update_version(self, entity_id: str, new_version: int) -> None:
        entity = await self.get_by_id(entity_id)
        if entity:
            entity.current_version = new_version
            await self.session.flush()
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_repositories/test_entity_repo.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/repositories/entity_repo.py tests/conftest.py tests/test_repositories/test_entity_repo.py
git commit -m "feat: add entity repository with create, get, update_version"
```

---

## Task 7: Entity Version Repository

**Files:**
- Create: `src/novel_dev/repositories/version_repo.py`
- Test: `tests/test_repositories/test_version_repo.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_repositories/test_version_repo.py
import pytest

from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.entity_repo import EntityRepository


@pytest.mark.asyncio
async def test_create_version_and_get_latest(async_session):
    entity_repo = EntityRepository(async_session)
    await entity_repo.create("char_002", "character", "Zhang San")

    ver_repo = EntityVersionRepository(async_session)
    await ver_repo.create("char_002", 1, {"realm": "qi_refinement"}, chapter_id="ch_001")
    await ver_repo.create("char_002", 2, {"realm": "foundation_building"}, chapter_id="ch_002")

    latest = await ver_repo.get_latest("char_002")
    assert latest.state["realm"] == "foundation_building"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_repositories/test_version_repo.py -v
```

Expected: ImportError for `EntityVersionRepository`

- [ ] **Step 3: Write EntityVersionRepository**

```python
# src/novel_dev/repositories/version_repo.py
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import EntityVersion


class EntityVersionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        entity_id: str,
        version: int,
        state: dict,
        chapter_id: Optional[str] = None,
        diff_summary: Optional[dict] = None,
    ) -> EntityVersion:
        ver = EntityVersion(
            entity_id=entity_id,
            version=version,
            state=state,
            chapter_id=chapter_id,
            diff_summary=diff_summary,
        )
        self.session.add(ver)
        await self.session.flush()
        return ver

    async def get_latest(self, entity_id: str) -> Optional[EntityVersion]:
        result = await self.session.execute(
            select(EntityVersion)
            .where(EntityVersion.entity_id == entity_id)
            .order_by(EntityVersion.version.desc())
        )
        return result.scalars().first()

    async def get_at_chapter(self, entity_id: str, chapter_id: str) -> Optional[EntityVersion]:
        result = await self.session.execute(
            select(EntityVersion)
            .where(
                EntityVersion.entity_id == entity_id,
                EntityVersion.chapter_id <= chapter_id,
            )
            .order_by(EntityVersion.version.desc())
        )
        return result.scalars().first()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_repositories/test_version_repo.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/repositories/version_repo.py tests/test_repositories/test_version_repo.py
git commit -m "feat: add entity version repository with latest and chapter snapshot queries"
```

---

## Task 8: Timeline & Spaceline Repositories

**Files:**
- Create: `src/novel_dev/repositories/timeline_repo.py`
- Create: `src/novel_dev/repositories/spaceline_repo.py`
- Test: `tests/test_repositories/test_timeline_repo.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_repositories/test_timeline_repo.py
import pytest

from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository


@pytest.mark.asyncio
async def test_timeline_crud(async_session):
    repo = TimelineRepository(async_session)
    entry = await repo.create(tick=1, narrative="Year 384", anchor_chapter_id="ch_001")
    assert entry.tick == 1
    latest = await repo.get_current_tick()
    assert latest == 1


@pytest.mark.asyncio
async def test_spaceline_chain(async_session):
    repo = SpacelineRepository(async_session)
    await repo.create("continent_1", "Tianxuan", parent_id=None)
    await repo.create("region_1", "East Wasteland", parent_id="continent_1")
    chain = await repo.get_chain("region_1")
    assert [node.id for node in chain] == ["continent_1", "region_1"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_repositories/test_timeline_repo.py -v
```

Expected: ImportError for TimelineRepository

- [ ] **Step 3: Write TimelineRepository**

```python
# src/novel_dev/repositories/timeline_repo.py
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import Timeline


class TimelineRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, tick: int, narrative: str, anchor_chapter_id: Optional[str] = None, anchor_event_id: Optional[str] = None) -> Timeline:
        entry = Timeline(
            tick=tick,
            narrative=narrative,
            anchor_chapter_id=anchor_chapter_id,
            anchor_event_id=anchor_event_id,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def get_current_tick(self) -> Optional[int]:
        result = await self.session.execute(select(Timeline.tick).order_by(Timeline.tick.desc()))
        row = result.scalar_one_or_none()
        return row

    async def get_adjacent(self, tick: int):
        prev_result = await self.session.execute(
            select(Timeline).where(Timeline.tick < tick).order_by(Timeline.tick.desc())
        )
        next_result = await self.session.execute(
            select(Timeline).where(Timeline.tick > tick).order_by(Timeline.tick.asc())
        )
        return prev_result.scalars().first(), next_result.scalars().first()
```

- [ ] **Step 4: Write SpacelineRepository**

```python
# src/novel_dev/repositories/spaceline_repo.py
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import Spaceline


class SpacelineRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, location_id: str, name: str, parent_id: Optional[str] = None, narrative: Optional[str] = None, metadata: Optional[dict] = None) -> Spaceline:
        loc = Spaceline(
            id=location_id,
            name=name,
            parent_id=parent_id,
            narrative=narrative,
            metadata=metadata,
        )
        self.session.add(loc)
        await self.session.flush()
        return loc

    async def get_chain(self, location_id: str) -> List[Spaceline]:
        chain = []
        current_id = location_id
        while current_id:
            result = await self.session.execute(select(Spaceline).where(Spaceline.id == current_id))
            node = result.scalar_one_or_none()
            if not node:
                break
            chain.append(node)
            current_id = node.parent_id
        chain.reverse()
        return chain
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_repositories/test_timeline_repo.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/repositories/timeline_repo.py src/novel_dev/repositories/spaceline_repo.py tests/test_repositories/test_timeline_repo.py
git commit -m "feat: add timeline and spaceline repositories"
```

---

## Task 9: Foreshadowing & Relationship Repositories

**Files:**
- Create: `src/novel_dev/repositories/foreshadowing_repo.py`
- Create: `src/novel_dev/repositories/relationship_repo.py`
- Test: `tests/test_repositories/test_foreshadowing_repo.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_repositories/test_foreshadowing_repo.py
import pytest

from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.relationship_repo import RelationshipRepository


@pytest.mark.asyncio
async def test_foreshadowing_lifecycle(async_session):
    repo = ForeshadowingRepository(async_session)
    fs = await repo.create(
        fs_id="fs_001",
        content="A jade pendant",
       埋下_chapter_id="ch_001",
        回收条件={"必要条件": ["筑基期"], "预计回收卷": "vol_2"},
    )
    assert fs.回收状态 == "pending"
    await repo.mark_recovered("fs_001", "ch_010", "evt_010")
    recovered = await repo.get_by_id("fs_001")
    assert recovered.回收状态 == "recovered"


@pytest.mark.asyncio
async def test_relationship_crud(async_session):
    from novel_dev.repositories.entity_repo import EntityRepository
    e_repo = EntityRepository(async_session)
    await e_repo.create("m_1", "character", "Master")
    await e_repo.create("d_1", "character", "Disciple")

    r_repo = RelationshipRepository(async_session)
    rel = await r_repo.create("m_1", "d_1", "master_of", chapter_id="ch_001")
    assert rel.relation_type == "master_of"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_repositories/test_foreshadowing_repo.py -v
```

Expected: ImportError for ForeshadowingRepository

- [ ] **Step 3: Write ForeshadowingRepository**

```python
# src/novel_dev/repositories/foreshadowing_repo.py
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import Foreshadowing


class ForeshadowingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        fs_id: str,
        content: str,
       埋下_chapter_id: Optional[str] = None,
       埋下_time_tick: Optional[int] = None,
       埋下_location_id: Optional[str] = None,
        相关人物_ids: Optional[List[str]] = None,
        回收条件: Optional[dict] = None,
        回收影响: Optional[dict] = None,
    ) -> Foreshadowing:
        fs = Foreshadowing(
            id=fs_id,
            content=content,
           埋下_chapter_id=埋下_chapter_id,
           埋下_time_tick=埋下_time_tick,
           埋下_location_id=埋下_location_id,
            相关人物_ids=相关人物_ids,
            回收条件=回收条件,
            回收影响=回收影响,
        )
        self.session.add(fs)
        await self.session.flush()
        return fs

    async def get_by_id(self, fs_id: str) -> Optional[Foreshadowing]:
        result = await self.session.execute(select(Foreshadowing).where(Foreshadowing.id == fs_id))
        return result.scalar_one_or_none()

    async def list_active(self) -> List[Foreshadowing]:
        result = await self.session.execute(
            select(Foreshadowing).where(Foreshadowing.回收状态 == "pending")
        )
        return result.scalars().all()

    async def mark_recovered(self, fs_id: str, chapter_id: str, event_id: Optional[str] = None) -> None:
        fs = await self.get_by_id(fs_id)
        if fs:
            fs.回收状态 = "recovered"
            fs.recovered_chapter_id = chapter_id
            fs.recovered_event_id = event_id
            await self.session.flush()
```

- [ ] **Step 4: Write RelationshipRepository**

```python
# src/novel_dev/repositories/relationship_repo.py
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import EntityRelationship


class RelationshipRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        metadata: Optional[dict] = None,
        chapter_id: Optional[str] = None,
    ) -> EntityRelationship:
        rel = EntityRelationship(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            metadata=metadata,
            created_at_chapter_id=chapter_id,
        )
        self.session.add(rel)
        await self.session.flush()
        return rel

    async def list_by_source(self, source_id: str) -> list[EntityRelationship]:
        result = await self.session.execute(
            select(EntityRelationship).where(
                EntityRelationship.source_id == source_id,
                EntityRelationship.is_active == True,
            )
        )
        return result.scalars().all()
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_repositories/test_foreshadowing_repo.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/repositories/foreshadowing_repo.py src/novel_dev/repositories/relationship_repo.py tests/test_repositories/test_foreshadowing_repo.py
git commit -m "feat: add foreshadowing and relationship repositories"
```

---

## Task 10: Chapter & Novel State Repositories

**Files:**
- Create: `src/novel_dev/repositories/chapter_repo.py`
- Create: `src/novel_dev/repositories/novel_state_repo.py`
- Test: `tests/test_repositories/test_chapter_repo.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_repositories/test_chapter_repo.py
import pytest

from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository


@pytest.mark.asyncio
async def test_chapter_crud(async_session):
    repo = ChapterRepository(async_session)
    ch = await repo.create("ch_001", "vol_1", 1, title="Prologue")
    assert ch.status == "pending"
    await repo.update_text("ch_001", raw_draft="draft text", polished_text="final text")
    updated = await repo.get_by_id("ch_001")
    assert updated.polished_text == "final text"


@pytest.mark.asyncio
async def test_novel_state_checkpoint(async_session):
    repo = NovelStateRepository(async_session)
    await repo.save_checkpoint(
        "novel_1",
        current_phase="writing_chapter_1_draft",
        checkpoint_data={"retry_count": 0},
        current_volume_id="vol_1",
        current_chapter_id="ch_1",
    )
    state = await repo.get_state("novel_1")
    assert state.current_phase == "writing_chapter_1_draft"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_repositories/test_chapter_repo.py -v
```

Expected: ImportError for ChapterRepository

- [ ] **Step 3: Write ChapterRepository**

```python
# src/novel_dev/repositories/chapter_repo.py
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import Chapter


class ChapterRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, chapter_id: str, volume_id: str, chapter_number: int, title: Optional[str] = None) -> Chapter:
        ch = Chapter(
            id=chapter_id,
            volume_id=volume_id,
            chapter_number=chapter_number,
            title=title,
        )
        self.session.add(ch)
        await self.session.flush()
        return ch

    async def get_by_id(self, chapter_id: str) -> Optional[Chapter]:
        result = await self.session.execute(select(Chapter).where(Chapter.id == chapter_id))
        return result.scalar_one_or_none()

    async def list_by_volume(self, volume_id: str) -> List[Chapter]:
        result = await self.session.execute(
            select(Chapter).where(Chapter.volume_id == volume_id).order_by(Chapter.chapter_number)
        )
        return result.scalars().all()

    async def update_text(self, chapter_id: str, raw_draft: Optional[str] = None, polished_text: Optional[str] = None) -> None:
        ch = await self.get_by_id(chapter_id)
        if ch:
            if raw_draft is not None:
                ch.raw_draft = raw_draft
            if polished_text is not None:
                ch.polished_text = polished_text
            await self.session.flush()

    async def update_scores(self, chapter_id: str, overall: int, breakdown: dict, feedback: dict) -> None:
        ch = await self.get_by_id(chapter_id)
        if ch:
            ch.score_overall = overall
            ch.score_breakdown = breakdown
            ch.review_feedback = feedback
            await self.session.flush()

    async def update_status(self, chapter_id: str, status: str) -> None:
        ch = await self.get_by_id(chapter_id)
        if ch:
            ch.status = status
            await self.session.flush()
```

- [ ] **Step 4: Write NovelStateRepository**

```python
# src/novel_dev/repositories/novel_state_repo.py
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import NovelState


class NovelStateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_state(self, novel_id: str) -> Optional[NovelState]:
        result = await self.session.execute(select(NovelState).where(NovelState.novel_id == novel_id))
        return result.scalar_one_or_none()

    async def save_checkpoint(
        self,
        novel_id: str,
        current_phase: str,
        checkpoint_data: dict,
        current_volume_id: Optional[str] = None,
        current_chapter_id: Optional[str] = None,
    ) -> NovelState:
        state = await self.get_state(novel_id)
        if state is None:
            state = NovelState(
                novel_id=novel_id,
                current_phase=current_phase,
                current_volume_id=current_volume_id,
                current_chapter_id=current_chapter_id,
                checkpoint_data=checkpoint_data,
            )
            self.session.add(state)
        else:
            state.current_phase = current_phase
            state.current_volume_id = current_volume_id
            state.current_chapter_id = current_chapter_id
            state.checkpoint_data = checkpoint_data
        await self.session.flush()
        return state
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_repositories/test_chapter_repo.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/repositories/chapter_repo.py src/novel_dev/repositories/novel_state_repo.py tests/test_repositories/test_chapter_repo.py
git commit -m "feat: add chapter and novel state repositories"
```

---

## Task 11: Document Repository

**Files:**
- Create: `src/novel_dev/repositories/document_repo.py`
- Test: `tests/test_repositories/test_document_repo.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_repositories/test_document_repo.py
import pytest

from novel_dev.repositories.document_repo import DocumentRepository


@pytest.mark.asyncio
async def test_document_crud(async_session):
    repo = DocumentRepository(async_session)
    doc = await repo.create(
        doc_id="doc_001",
        novel_id="novel_1",
        doc_type="worldview",
        title="World Setting",
        content="In a land of cultivation...",
    )
    assert doc.doc_type == "worldview"
    fetched = await repo.get_by_type("novel_1", "worldview")
    assert fetched[0].title == "World Setting"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_repositories/test_document_repo.py -v
```

Expected: ImportError for DocumentRepository

- [ ] **Step 3: Write DocumentRepository**

```python
# src/novel_dev/repositories/document_repo.py
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novel_dev.db.models import NovelDocument


class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        doc_id: str,
        novel_id: str,
        doc_type: str,
        title: str,
        content: str,
        vector_embedding: Optional[List[float]] = None,
    ) -> NovelDocument:
        doc = NovelDocument(
            id=doc_id,
            novel_id=novel_id,
            doc_type=doc_type,
            title=title,
            content=content,
            vector_embedding=vector_embedding,
        )
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def get_by_id(self, doc_id: str) -> Optional[NovelDocument]:
        result = await self.session.execute(select(NovelDocument).where(NovelDocument.id == doc_id))
        return result.scalar_one_or_none()

    async def get_by_type(self, novel_id: str, doc_type: str) -> List[NovelDocument]:
        result = await self.session.execute(
            select(NovelDocument)
            .where(NovelDocument.novel_id == novel_id, NovelDocument.doc_type == doc_type)
            .order_by(NovelDocument.updated_at.desc())
        )
        return result.scalars().all()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_repositories/test_document_repo.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/repositories/document_repo.py tests/test_repositories/test_document_repo.py
git commit -m "feat: add document repository"
```

---

## Task 12: Entity Service (Versioned CRUD)

**Files:**
- Create: `src/novel_dev/services/entity_service.py`
- Test: `tests/test_services/test_entity_service.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_services/test_entity_service.py
import pytest

from novel_dev.services.entity_service import EntityService


@pytest.mark.asyncio
async def test_create_entity_and_update_state(async_session):
    svc = EntityService(async_session)
    entity = await svc.create_entity("char_003", "character", "Wang Wu", chapter_id="ch_001")
    assert entity.current_version == 1

    updated = await svc.update_state("char_003", {"realm": "golden_core"}, chapter_id="ch_002")
    assert updated.version == 2
    assert updated.state["realm"] == "golden_core"

    latest = await svc.get_latest_state("char_003")
    assert latest["realm"] == "golden_core"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_services/test_entity_service.py -v
```

Expected: ImportError for EntityService

- [ ] **Step 3: Write EntityService**

```python
# src/novel_dev/services/entity_service.py
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository


class EntityService:
    def __init__(self, session: AsyncSession):
        self.entity_repo = EntityRepository(session)
        self.version_repo = EntityVersionRepository(session)

    async def create_entity(self, entity_id: str, entity_type: str, name: str, chapter_id: Optional[str] = None) -> ...:
        entity = await self.entity_repo.create(entity_id, entity_type, name, chapter_id)
        await self.version_repo.create(entity_id, 1, {"name": name}, chapter_id=chapter_id, diff_summary={"created": True})
        await self.entity_repo.update_version(entity_id, 1)
        return entity

    async def update_state(self, entity_id: str, new_state: dict, chapter_id: Optional[str] = None, diff_summary: Optional[dict] = None):
        latest = await self.version_repo.get_latest(entity_id)
        new_version = (latest.version + 1) if latest else 1
        ver = await self.version_repo.create(entity_id, new_version, new_state, chapter_id=chapter_id, diff_summary=diff_summary)
        await self.entity_repo.update_version(entity_id, new_version)
        return ver

    async def get_latest_state(self, entity_id: str) -> Optional[dict]:
        latest = await self.version_repo.get_latest(entity_id)
        return latest.state if latest else None
```

Note: The return type `...` in `create_entity` should be `Entity` (import from `novel_dev.db.models`). Fix it in the implementation.

```python
# src/novel_dev/services/entity_service.py
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import Entity
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository


class EntityService:
    def __init__(self, session: AsyncSession):
        self.entity_repo = EntityRepository(session)
        self.version_repo = EntityVersionRepository(session)

    async def create_entity(self, entity_id: str, entity_type: str, name: str, chapter_id: Optional[str] = None) -> Entity:
        entity = await self.entity_repo.create(entity_id, entity_type, name, chapter_id)
        await self.version_repo.create(entity_id, 1, {"name": name}, chapter_id=chapter_id, diff_summary={"created": True})
        await self.entity_repo.update_version(entity_id, 1)
        return entity

    async def update_state(self, entity_id: str, new_state: dict, chapter_id: Optional[str] = None, diff_summary: Optional[dict] = None):
        latest = await self.version_repo.get_latest(entity_id)
        new_version = (latest.version + 1) if latest else 1
        ver = await self.version_repo.create(entity_id, new_version, new_state, chapter_id=chapter_id, diff_summary=diff_summary)
        await self.entity_repo.update_version(entity_id, new_version)
        return ver

    async def get_latest_state(self, entity_id: str) -> Optional[dict]:
        latest = await self.version_repo.get_latest(entity_id)
        return latest.state if latest else None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_services/test_entity_service.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/entity_service.py tests/test_services/test_entity_service.py
git commit -m "feat: add entity service with automatic version chaining"
```

---

## Task 13: Markdown Sync Storage

**Files:**
- Create: `src/novel_dev/storage/markdown_sync.py`
- Test: `tests/test_storage/__init__.py`
- Test: `tests/test_storage/test_markdown_sync.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_storage/test_markdown_sync.py
import os
import pytest

from novel_dev.storage.markdown_sync import MarkdownSync


@pytest.mark.asyncio
async def test_write_and_read_chapter():
    sync = MarkdownSync(base_dir="/tmp/test_novel_output")
    await sync.write_chapter("novel_1", "vol_1", "ch_1", "Chapter 1 text")
    content = await sync.read_chapter("novel_1", "vol_1", "ch_1")
    assert content == "Chapter 1 text"
    # cleanup
    import shutil
    shutil.rmtree("/tmp/test_novel_output", ignore_errors=True)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_storage/test_markdown_sync.py -v
```

Expected: ImportError for MarkdownSync

- [ ] **Step 3: Write MarkdownSync**

```python
# src/novel_dev/storage/markdown_sync.py
import os
import aiofiles


class MarkdownSync:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    def _chapter_path(self, novel_id: str, volume_id: str, chapter_id: str) -> str:
        dir_path = os.path.join(self.base_dir, novel_id, volume_id)
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, f"{chapter_id}.md")

    async def write_chapter(self, novel_id: str, volume_id: str, chapter_id: str, content: str) -> str:
        path = self._chapter_path(novel_id, volume_id, chapter_id)
        async with aiofiles.open(path, mode="w", encoding="utf-8") as f:
            await f.write(content)
        return path

    async def read_chapter(self, novel_id: str, volume_id: str, chapter_id: str) -> str:
        path = self._chapter_path(novel_id, volume_id, chapter_id)
        async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
            return await f.read()
```

Wait, `aiofiles` is not in the dependencies. Let me add it to `pyproject.toml` or use standard `asyncio.to_thread` with synchronous `open()`. Using `asyncio.to_thread` is better to avoid a new dependency.

```python
# src/novel_dev/storage/markdown_sync.py
import os
import asyncio


class MarkdownSync:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    def _chapter_path(self, novel_id: str, volume_id: str, chapter_id: str) -> str:
        dir_path = os.path.join(self.base_dir, novel_id, volume_id)
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, f"{chapter_id}.md")

    async def write_chapter(self, novel_id: str, volume_id: str, chapter_id: str, content: str) -> str:
        path = self._chapter_path(novel_id, volume_id, chapter_id)
        await asyncio.to_thread(self._sync_write, path, content)
        return path

    def _sync_write(self, path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    async def read_chapter(self, novel_id: str, volume_id: str, chapter_id: str) -> str:
        path = self._chapter_path(novel_id, volume_id, chapter_id)
        return await asyncio.to_thread(self._sync_read, path)

    def _sync_read(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_storage/test_markdown_sync.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/storage/markdown_sync.py tests/test_storage/
git commit -m "feat: add markdown sync for chapter file output"
```

---

## Task 14: Chapter Service

**Files:**
- Create: `src/novel_dev/services/chapter_service.py`
- Test: `tests/test_services/test_chapter_service.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_services/test_chapter_service.py
import pytest

from novel_dev.services.chapter_service import ChapterService


@pytest.mark.asyncio
async def test_create_and_complete_chapter(async_session):
    svc = ChapterService(async_session, "/tmp/test_output")
    ch = await svc.create("ch_1", "vol_1", 1, "Prologue")
    assert ch.status == "pending"

    await svc.complete_chapter("novel_1", "ch_1", "vol_1", "draft", "polished")
    updated = await svc.get("ch_1")
    assert updated.status == "completed"
    assert updated.polished_text == "polished"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_services/test_chapter_service.py -v
```

Expected: ImportError for ChapterService

- [ ] **Step 3: Write ChapterService**

```python
# src/novel_dev/services/chapter_service.py
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.storage.markdown_sync import MarkdownSync


class ChapterService:
    def __init__(self, session: AsyncSession, markdown_base_dir: str):
        self.repo = ChapterRepository(session)
        self.sync = MarkdownSync(markdown_base_dir)

    async def create(self, chapter_id: str, volume_id: str, chapter_number: int, title: Optional[str] = None):
        return await self.repo.create(chapter_id, volume_id, chapter_number, title)

    async def get(self, chapter_id: str):
        return await self.repo.get_by_id(chapter_id)

    async def complete_chapter(self, novel_id: str, chapter_id: str, volume_id: str, raw_draft: str, polished_text: str) -> None:
        await self.repo.update_text(chapter_id, raw_draft=raw_draft, polished_text=polished_text)
        await self.repo.update_status(chapter_id, "completed")
        await self.sync.write_chapter(novel_id, volume_id, chapter_id, polished_text)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_services/test_chapter_service.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/services/chapter_service.py tests/test_services/test_chapter_service.py
git commit -m "feat: add chapter service with markdown sync"
```

---

## Task 15: FastAPI REST Routes

**Files:**
- Create: `src/novel_dev/api/routes.py`
- Test: `tests/test_api/test_routes.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_api/test_routes.py
import pytest
from httpx import AsyncClient
from fastapi import FastAPI

from novel_dev.api.routes import router

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_get_novel_state_not_found():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/novels/novel_x/state")
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api/test_routes.py -v
```

Expected: `ImportError: cannot import name 'router' from 'novel_dev.api.routes'`

- [ ] **Step 3: Write routes module**

```python
# src/novel_dev/api/routes.py
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.engine import async_session_maker
from novel_dev.services.entity_service import EntityService
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.storage.markdown_sync import MarkdownSync
from novel_dev.config import Settings

router = APIRouter()
settings = Settings()


async def get_session():
    async with async_session_maker() as session:
        yield session


@router.get("/api/novels/{novel_id}/state")
async def get_novel_state(novel_id: str, session: AsyncSession = Depends(get_session)):
    repo = NovelStateRepository(session)
    state = await repo.get_state(novel_id)
    if not state:
        raise HTTPException(status_code=404, detail="Novel state not found")
    return {
        "novel_id": state.novel_id,
        "current_phase": state.current_phase,
        "current_volume_id": state.current_volume_id,
        "current_chapter_id": state.current_chapter_id,
        "checkpoint_data": state.checkpoint_data,
        "last_updated": state.last_updated.isoformat(),
    }


@router.get("/api/novels/{novel_id}/entities/{entity_id}")
async def get_entity(novel_id: str, entity_id: str, session: AsyncSession = Depends(get_session)):
    svc = EntityService(session)
    state = await svc.get_latest_state(entity_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return {"entity_id": entity_id, "latest_state": state}


@router.get("/api/novels/{novel_id}/chapters/{chapter_id}")
async def get_chapter(novel_id: str, chapter_id: str, session: AsyncSession = Depends(get_session)):
    repo = ChapterRepository(session)
    ch = await repo.get_by_id(chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {
        "id": ch.id,
        "volume_id": ch.volume_id,
        "chapter_number": ch.chapter_number,
        "title": ch.title,
        "status": ch.status,
        "score_overall": ch.score_overall,
    }


@router.get("/api/novels/{novel_id}/chapters/{chapter_id}/export.md")
async def export_chapter(novel_id: str, chapter_id: str, session: AsyncSession = Depends(get_session)):
    repo = ChapterRepository(session)
    ch = await repo.get_by_id(chapter_id)
    if not ch or not ch.polished_text:
        raise HTTPException(status_code=404, detail="Chapter content not found")
    sync = MarkdownSync(settings.markdown_output_dir)
    path = await sync.write_chapter(novel_id, ch.volume_id, chapter_id, ch.polished_text)
    return {"exported_path": path, "content": ch.polished_text}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_api/test_routes.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_routes.py
git commit -m "feat: add fastapi routes for state, entities, chapters, and export"
```

---

## Task 16: MCP Server

**Files:**
- Create: `src/novel_dev/mcp_server/server.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_mcp_server.py
import pytest

from novel_dev.mcp_server.server import mcp


def test_mcp_server_has_tools():
    tools = [t.name for t in mcp._tools]
    assert "query_entity" in tools
    assert "get_active_foreshadowings" in tools
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_mcp_server.py -v
```

Expected: ImportError or assertion error

- [ ] **Step 3: Write MCP Server**

```python
# src/novel_dev/mcp_server/server.py
from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.engine import async_session_maker
from novel_dev.services.entity_service import EntityService
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.spaceline_repo import SpacelineRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.document_repo import DocumentRepository

mcp = FastMCP("novel_dev")


async def _get_session() -> AsyncSession:
    async with async_session_maker() as session:
        return session


@mcp.tool()
async def query_entity(entity_id: str) -> dict:
    async with async_session_maker() as session:
        svc = EntityService(session)
        state = await svc.get_latest_state(entity_id)
        return {"entity_id": entity_id, "state": state}


@mcp.tool()
async def get_active_foreshadowings() -> list[dict]:
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
async def get_spaceline_chain(location_id: str) -> list[dict]:
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
async def get_novel_documents(novel_id: str, doc_type: str) -> list[dict]:
    async with async_session_maker() as session:
        repo = DocumentRepository(session)
        docs = await repo.get_by_type(novel_id, doc_type)
        return [{"id": d.id, "title": d.title, "content": d.content[:500]} for d in docs]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_mcp_server.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/mcp_server/server.py tests/test_mcp_server.py
git commit -m "feat: add mcp server with core query tools"
```

---

## Task 17: LibrarianAgent Prototype

**Files:**
- Create: `src/novel_dev/agents/librarian.py`
- Test: `tests/test_agents/test_librarian.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_agents/test_librarian.py
import pytest

from novel_dev.agents.librarian import LibrarianAgent


def test_extract_entities():
    agent = LibrarianAgent()
    text = "Lin Feng picked up the Azure Sword at Qingyun Sect."
    result = agent.extract_entities(text)
    assert "Lin Feng" in result["characters"]
    assert "Azure Sword" in result["items"]
    assert "Qingyun Sect" in result["locations"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agents/test_librarian.py -v
```

Expected: ImportError for LibrarianAgent

- [ ] **Step 3: Write LibrarianAgent (prototype rule-based extractor)**

```python
# src/novel_dev/agents/librarian.py
import re
from typing import Dict, List


class LibrarianAgent:
    """Prototype rule-based extractor for entities, timeline, and foreshadowings."""

    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        # Naive heuristics for prototype; production will use LLM extraction
        # Capitalized consecutive words assumed as proper nouns
        candidates = re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+', text)
        # Simple classification heuristics for Chinese/English mixed
        characters = []
        items = []
        locations = []
        concepts = []

        for cand in candidates:
            lower = cand.lower()
            if any(x in lower for x in ["sect", "mountain", "city", "valley", "peak"]):
                locations.append(cand)
            elif any(x in lower for x in ["sword", "pill", "jade", "ring", "armor"]):
                items.append(cand)
            else:
                characters.append(cand)

        return {
            "characters": list(set(characters)),
            "items": list(set(items)),
            "locations": list(set(locations)),
            "concepts": list(set(concepts)),
        }

    def extract_time_progress(self, text: str) -> Dict:
        # Placeholder heuristic: look for "three days later" patterns
        return {"detected_time_phrases": re.findall(r'\d+\s+days?\s+later', text, re.IGNORECASE)}

    def extract_foreshadowing_clues(self, text: str) -> List[str]:
        # Look for sentences with question marks or mysterious descriptions
        sentences = re.split(r'[.!?。！？]', text)
        clues = [s.strip() for s in sentences if "?" in s or "mysterious" in s.lower()]
        return clues
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_agents/test_librarian.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/librarian.py tests/test_agents/test_librarian.py
git commit -m "feat: add prototype librarian agent with rule-based extraction"
```

---

## Task 18: NovelDirector State Machine Prototype

**Files:**
- Create: `src/novel_dev/agents/director.py`
- Test: `tests/test_agents/test_director.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_agents/test_director.py
import pytest

from novel_dev.agents.director import NovelDirector, Phase


def test_phase_transition():
    director = NovelDirector()
    assert director.can_transition(Phase.CONTEXT_PREPARATION, Phase.DRAFTING)
    assert not director.can_transition(Phase.DRAFTING, Phase.CONTEXT_PREPARATION)


@pytest.mark.asyncio
async def test_save_and_resume(async_session):
    from novel_dev.repositories.novel_state_repo import NovelStateRepository
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_1",
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_plan": "plan"},
        volume_id="vol_1",
        chapter_id="ch_1",
    )
    state = await director.resume("novel_1")
    assert state.current_phase == Phase.DRAFTING.value
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agents/test_director.py -v
```

Expected: ImportError for NovelDirector

- [ ] **Step 3: Write NovelDirector**

```python
# src/novel_dev/agents/director.py
from enum import Enum
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.db.models import NovelState


class Phase(str, Enum):
    VOLUME_PLANNING = "volume_planning"
    CONTEXT_PREPARATION = "context_preparation"
    DRAFTING = "drafting"
    REVIEWING = "reviewing"
    EDITING = "editing"
    FAST_REVIEWING = "fast_reviewing"
    LIBRARIAN = "librarian"
    COMPLETED = "completed"


VALID_TRANSITIONS = {
    Phase.VOLUME_PLANNING: [Phase.CONTEXT_PREPARATION],
    Phase.CONTEXT_PREPARATION: [Phase.DRAFTING],
    Phase.DRAFTING: [Phase.REVIEWING],
    Phase.REVIEWING: [Phase.EDITING, Phase.DRAFTING],
    Phase.EDITING: [Phase.FAST_REVIEWING],
    Phase.FAST_REVIEWING: [Phase.LIBRARIAN, Phase.DRAFTING, Phase.EDITING],
    Phase.LIBRARIAN: [Phase.COMPLETED],
    Phase.COMPLETED: [Phase.CONTEXT_PREPARATION],
}


class NovelDirector:
    def __init__(self, session: Optional[AsyncSession] = None):
        self.session = session
        self.state_repo = NovelStateRepository(session) if session else None

    def can_transition(self, current: Phase, next_phase: Phase) -> bool:
        return next_phase in VALID_TRANSITIONS.get(current, [])

    async def save_checkpoint(
        self,
        novel_id: str,
        phase: Phase,
        checkpoint_data: dict,
        volume_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
    ) -> NovelState:
        if self.state_repo is None:
            raise RuntimeError("NovelDirector requires a session to save checkpoints")
        return await self.state_repo.save_checkpoint(
            novel_id,
            current_phase=phase.value,
            checkpoint_data=checkpoint_data,
            current_volume_id=volume_id,
            current_chapter_id=chapter_id,
        )

    async def resume(self, novel_id: str) -> Optional[NovelState]:
        if self.state_repo is None:
            raise RuntimeError("NovelDirector requires a session to resume")
        return await self.state_repo.get_state(novel_id)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_agents/test_director.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/agents/director.py tests/test_agents/test_director.py
git commit -m "feat: add novel director state machine with checkpoint/resume"
```

---

## Task 19: Integration Test — Full Chapter Flow

**Files:**
- Test: `tests/test_integration_chapter_flow.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration_chapter_flow.py
import pytest

from novel_dev.services.entity_service import EntityService
from novel_dev.services.chapter_service import ChapterService
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.repositories.novel_state_repo import NovelStateRepository


@pytest.mark.asyncio
async def test_full_chapter_flow(async_session):
    # Setup
    entity_svc = EntityService(async_session)
    chapter_svc = ChapterService(async_session, "/tmp/test_integration_output")
    director = NovelDirector(session=async_session)

    # 1. Create a character
    await entity_svc.create_entity("hero", "character", "Lin Feng", chapter_id="ch_1")

    # 2. Director saves checkpoint for drafting
    await director.save_checkpoint(
        "novel_demo",
        phase=Phase.DRAFTING,
        checkpoint_data={"volume_plan": "Hero ascends", "chapter_plan": "Breakthrough"},
        volume_id="vol_1",
        chapter_id="ch_1",
    )

    # 3. Create and complete chapter
    await chapter_svc.create("ch_1", "vol_1", 1, "Breakthrough")
    await chapter_svc.complete_chapter("novel_demo", "ch_1", "vol_1", "draft body", "polished body")

    # 4. Update entity state as if LibrarianAgent found a change
    await entity_svc.update_state("hero", {"name": "Lin Feng", "realm": "foundation_building"}, chapter_id="ch_1")

    # 5. Mark chapter flow complete
    await director.save_checkpoint(
        "novel_demo",
        phase=Phase.COMPLETED,
        checkpoint_data={},
        volume_id="vol_1",
        chapter_id="ch_1",
    )

    # Verify
    state = await director.resume("novel_demo")
    assert state.current_phase == Phase.COMPLETED.value

    hero_state = await entity_svc.get_latest_state("hero")
    assert hero_state["realm"] == "foundation_building"

    ch = await chapter_svc.get("ch_1")
    assert ch.status == "completed"
    assert ch.polished_text == "polished body"
```

- [ ] **Step 2: Run integration test**

```bash
pytest tests/test_integration_chapter_flow.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration_chapter_flow.py
git commit -m "test: add integration test for full chapter flow"
```

---

## Task 20: Run All Tests & Final Cleanup

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 2: Verify no lint/type errors (optional but recommended)**

```bash
python -m compileall src/novel_dev
```

Expected: no syntax errors.

- [ ] **Step 3: Final commit**

```bash
git add .
git commit -m "feat: complete core data layer implementation"
```

---

## Self-Review Checklist

### Spec Coverage

| Spec Requirement | Plan Task |
|---|---|
| PostgreSQL schema with pgvector | Tasks 4, 5 |
| entities + version chain | Tasks 6, 7, 12 |
| timeline + spaceline | Tasks 8 |
| foreshadowings + relationships | Tasks 9 |
| novel_state checkpoint/resume | Tasks 10, 18 |
| chapters table + markdown sync | Tasks 10, 13, 14 |
| novel_documents + vector support | Tasks 4, 11 |
| Python SDK (repositories + services) | Tasks 6-14 |
| MCP Server tools | Task 16 |
| REST API (FastAPI) | Task 15 |
| LibrarianAgent prototype | Task 17 |
| NovelDirector state machine | Task 18 |
| Integration test | Task 19 |

### Placeholder Scan
- No "TBD", "TODO", "implement later" found.
- All steps include exact file paths, code blocks, and commands.

### Type Consistency
- `EntityService.create_entity` returns `Entity` (correctly imported in Task 12).
- `NovelDirector` uses `Phase` enum consistently.
- Repository names and method signatures match across tasks.
