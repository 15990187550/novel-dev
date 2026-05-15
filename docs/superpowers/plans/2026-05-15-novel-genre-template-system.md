# Novel Genre Template System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add required first-level and second-level novel categories, resolve genre templates from built-in defaults plus database overrides, and apply those templates to prompts and quality checks.

**Architecture:** Genre data has three layers: immutable built-in defaults, optional database overrides, and per-novel selected genre metadata stored in `NovelState.checkpoint_data`. A centralized `GenreTemplateService` resolves `global -> primary -> secondary` templates and returns prompt blocks plus quality configuration; agents consume resolved blocks without hardcoded category branches.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, Alembic, Pydantic, pytest, Vue 3, Pinia, Element Plus, Vitest.

---

## File Structure

Create:

- `src/novel_dev/genres/__init__.py` exports genre helpers.
- `src/novel_dev/genres/models.py` defines Pydantic models for category and template configuration.
- `src/novel_dev/genres/defaults.py` stores built-in category tree and first-phase template defaults.
- `src/novel_dev/repositories/genre_repo.py` reads category and template overrides.
- `src/novel_dev/services/genre_template_service.py` resolves selected novel genre, merges templates, validates template content, and exposes prompt/quality helpers.
- `migrations/versions/20260515_add_novel_genre_templates.py` creates `novel_categories` and `novel_genre_templates`.
- `tests/test_genres/test_defaults.py` validates built-in defaults and forbidden concrete content.
- `tests/test_services/test_genre_template_service.py` validates merge behavior and fallback behavior.
- `tests/test_repositories/test_genre_repo.py` validates database override reads.
- `tests/test_api/test_novel_categories.py` validates category API and create-novel validation.

Modify:

- `src/novel_dev/db/models.py` adds `NovelCategory` and `NovelGenreTemplate`.
- `src/novel_dev/api/routes.py` adds category API, create-novel genre validation, state serialization fallback, and list serialization.
- `src/novel_dev/web/src/api.js` adds `getNovelCategories()` and upgrades `createNovel(payload)`.
- `src/novel_dev/web/src/components/NovelSelector.vue` adds required category selectors.
- `src/novel_dev/web/src/stores/novel.js` stores/display genre metadata if currently needed by dashboard.
- `src/novel_dev/testing/generation_runner.py` passes category fields when creating novels and records template evidence in reports.
- `src/novel_dev/services/prose_hygiene_service.py` accepts resolved genre quality config for modern/foreign drift policy.
- `src/novel_dev/services/quality_gate_service.py` accepts resolved genre quality config for type-drift blocking behavior.
- `src/novel_dev/agents/brainstorm_agent.py` injects genre prompt blocks into top-level synopsis and batch volume-outline generation.
- `src/novel_dev/agents/setting_workbench_agent.py` injects setting/source/forbidden blocks into setting generation prompts.
- `src/novel_dev/agents/volume_planner.py` injects structure/quality blocks into planning and review prompts.
- `src/novel_dev/agents/writer_agent.py` injects prose/forbidden/quality blocks into beat generation prompts.
- `src/novel_dev/agents/fast_review_agent.py` applies type quality config in final review.
- `tests/test_api/test_create_novel.py`, `tests/test_api/test_novel_list.py`, `tests/test_testing/test_generation_runner.py`, and affected integration tests update create-novel payloads.
- `AGENTS.md` adds the genre-template generalization rule required by the design.

---

### Task 1: Built-In Genre Models And Defaults

**Files:**
- Create: `src/novel_dev/genres/__init__.py`
- Create: `src/novel_dev/genres/models.py`
- Create: `src/novel_dev/genres/defaults.py`
- Create: `tests/test_genres/test_defaults.py`

- [ ] **Step 1: Write tests for built-in category tree and template safety**

Create `tests/test_genres/test_defaults.py`:

```python
import pytest

from novel_dev.genres.defaults import BUILTIN_CATEGORIES, BUILTIN_TEMPLATES, default_genre
from novel_dev.genres.models import validate_template_is_generic


def test_builtin_categories_include_required_core_tree():
    tree = {(item.slug, item.parent_slug): item for item in BUILTIN_CATEGORIES}
    assert ("general", None) in tree
    assert ("uncategorized", "general") in tree
    assert ("xuanhuan", None) in tree
    assert ("zhutian", "xuanhuan") in tree
    assert ("dushi", None) in tree
    assert ("workplace_business", "dushi") in tree


def test_default_genre_is_general_uncategorized():
    genre = default_genre()
    assert genre.primary_slug == "general"
    assert genre.primary_name == "通用"
    assert genre.secondary_slug == "uncategorized"
    assert genre.secondary_name == "未分类"


def test_builtin_templates_have_global_and_genre_layers():
    keys = {(tpl.scope, tpl.category_slug, tpl.agent_name, tpl.task_name) for tpl in BUILTIN_TEMPLATES}
    assert ("global", None, "*", "*") in keys
    assert ("primary", "xuanhuan", "*", "*") in keys
    assert ("secondary", "zhutian", "*", "*") in keys
    assert ("secondary", "workplace_business", "*", "*") in keys


@pytest.mark.parametrize("template", BUILTIN_TEMPLATES)
def test_builtin_templates_do_not_contain_concrete_story_content(template):
    validate_template_is_generic(template)
```

- [ ] **Step 2: Run tests to verify missing package fails**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_genres/test_defaults.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'novel_dev.genres'`.

- [ ] **Step 3: Add genre Pydantic models and generic-template validator**

Create `src/novel_dev/genres/models.py`:

```python
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


PromptBlockName = Literal[
    "role_rules",
    "source_rules",
    "setting_rules",
    "structure_rules",
    "prose_rules",
    "forbidden_rules",
    "quality_rules",
    "output_rules",
]


class GenreCategory(BaseModel):
    slug: str
    name: str
    level: Literal[1, 2]
    parent_slug: str | None = None
    description: str = ""
    sort_order: int = 0
    enabled: bool = True
    source: Literal["builtin", "db"] = "builtin"

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", normalized):
            raise ValueError("slug must be lowercase snake_case")
        return normalized


class NovelGenre(BaseModel):
    primary_slug: str
    primary_name: str
    secondary_slug: str
    secondary_name: str


class GenreTemplate(BaseModel):
    scope: Literal["global", "primary", "secondary"]
    category_slug: str | None = None
    parent_slug: str | None = None
    agent_name: str = "*"
    task_name: str = "*"
    prompt_blocks: dict[str, list[str]] = Field(default_factory=dict)
    quality_config: dict[str, Any] = Field(default_factory=dict)
    merge_policy: dict[str, Literal["append", "replace"]] = Field(default_factory=dict)
    enabled: bool = True
    version: int = 1
    source: Literal["builtin", "db"] = "builtin"


class ResolvedGenreTemplate(BaseModel):
    genre: NovelGenre
    prompt_blocks: dict[str, list[str]] = Field(default_factory=dict)
    quality_config: dict[str, Any] = Field(default_factory=dict)
    matched_templates: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def render_prompt_block(self, *names: str) -> str:
        lines: list[str] = []
        for name in names:
            values = self.prompt_blocks.get(name, [])
            if values:
                title = name.replace("_", " ")
                lines.append(f"### Genre {title}")
                lines.extend(f"- {item}" for item in values if item.strip())
        return "\n".join(lines).strip()


FORBIDDEN_TEMPLATE_FRAGMENTS = (
    "陆照",
    "李大牛",
    "王明月",
    "青云宗",
    "玄火盟",
    "血海殿",
    "瓦片",
    "凝气草",
    "职场霸凌还不用负法律责任",
    "搁前世",
    "藏书阁",
)


def validate_template_is_generic(template: GenreTemplate) -> None:
    payload = template.model_dump_json(ensure_ascii=False)
    found = [fragment for fragment in FORBIDDEN_TEMPLATE_FRAGMENTS if fragment in payload]
    if found:
        raise ValueError(f"genre template contains concrete story fragments: {found}")
```

- [ ] **Step 4: Add built-in categories and initial templates**

Create `src/novel_dev/genres/defaults.py`:

```python
from __future__ import annotations

from novel_dev.genres.models import GenreCategory, GenreTemplate, NovelGenre


BUILTIN_CATEGORIES: tuple[GenreCategory, ...] = (
    GenreCategory(slug="general", name="通用", level=1, sort_order=0, description="通用正式创作模板"),
    GenreCategory(slug="uncategorized", name="未分类", level=2, parent_slug="general", sort_order=0, description="历史兼容分类"),
    GenreCategory(slug="xuanhuan", name="玄幻", level=1, sort_order=10, description="以超凡规则、力量体系和世界秩序为核心的长篇类型"),
    GenreCategory(slug="oriental_fantasy", name="东方玄幻", level=2, parent_slug="xuanhuan", sort_order=11),
    GenreCategory(slug="otherworld_continent", name="异世大陆", level=2, parent_slug="xuanhuan", sort_order=12),
    GenreCategory(slug="zhutian", name="诸天文", level=2, parent_slug="xuanhuan", sort_order=13),
    GenreCategory(slug="system_flow", name="系统流", level=2, parent_slug="xuanhuan", sort_order=14),
    GenreCategory(slug="xianxia", name="仙侠", level=1, sort_order=20),
    GenreCategory(slug="classical_xianxia", name="古典仙侠", level=2, parent_slug="xianxia", sort_order=21),
    GenreCategory(slug="cultivation_civilization", name="修真文明", level=2, parent_slug="xianxia", sort_order=22),
    GenreCategory(slug="mortal_flow", name="凡人流", level=2, parent_slug="xianxia", sort_order=23),
    GenreCategory(slug="prehistoric_myth", name="洪荒流", level=2, parent_slug="xianxia", sort_order=24),
    GenreCategory(slug="dushi", name="都市", level=1, sort_order=30),
    GenreCategory(slug="urban_life", name="都市生活", level=2, parent_slug="dushi", sort_order=31),
    GenreCategory(slug="urban_power", name="都市异能", level=2, parent_slug="dushi", sort_order=32),
    GenreCategory(slug="workplace_business", name="职场商战", level=2, parent_slug="dushi", sort_order=33),
    GenreCategory(slug="urban_cultivation", name="都市修真", level=2, parent_slug="dushi", sort_order=34),
    GenreCategory(slug="kehuan", name="科幻", level=1, sort_order=40),
    GenreCategory(slug="future_world", name="未来世界", level=2, parent_slug="kehuan", sort_order=41),
    GenreCategory(slug="interstellar", name="星际文明", level=2, parent_slug="kehuan", sort_order=42),
    GenreCategory(slug="apocalypse", name="末世危机", level=2, parent_slug="kehuan", sort_order=43),
    GenreCategory(slug="cyberpunk", name="赛博朋克", level=2, parent_slug="kehuan", sort_order=44),
    GenreCategory(slug="xuanyi", name="悬疑", level=1, sort_order=50),
    GenreCategory(slug="detective", name="推理探案", level=2, parent_slug="xuanyi", sort_order=51),
    GenreCategory(slug="folk_suspense", name="民俗悬疑", level=2, parent_slug="xuanyi", sort_order=52),
    GenreCategory(slug="infinite_flow", name="无限流", level=2, parent_slug="xuanyi", sort_order=53),
    GenreCategory(slug="psychological_suspense", name="心理悬疑", level=2, parent_slug="xuanyi", sort_order=54),
    GenreCategory(slug="lishi", name="历史", level=1, sort_order=60),
    GenreCategory(slug="alternate_history", name="架空历史", level=2, parent_slug="lishi", sort_order=61),
    GenreCategory(slug="time_travel_history", name="穿越历史", level=2, parent_slug="lishi", sort_order=62),
    GenreCategory(slug="political_war", name="权谋争霸", level=2, parent_slug="lishi", sort_order=63),
    GenreCategory(slug="historical_military", name="历史军事", level=2, parent_slug="lishi", sort_order=64),
    GenreCategory(slug="qihuan", name="奇幻", level=1, sort_order=70),
    GenreCategory(slug="western_fantasy", name="西方奇幻", level=2, parent_slug="qihuan", sort_order=71),
    GenreCategory(slug="epic_fantasy", name="史诗奇幻", level=2, parent_slug="qihuan", sort_order=72),
    GenreCategory(slug="magic_academy", name="魔法学院", level=2, parent_slug="qihuan", sort_order=73),
    GenreCategory(slug="otherworld_adventure", name="异界冒险", level=2, parent_slug="qihuan", sort_order=74),
)


BUILTIN_TEMPLATES: tuple[GenreTemplate, ...] = (
    GenreTemplate(
        scope="global",
        prompt_blocks={
            "source_rules": ["正式工作流必须以导入资料、用户设定和已确认工作台内容为事实来源；缺失信息标记为待确认，不编造具体事实。"],
            "quality_rules": ["生成前先检查类型约束、设定一致性、可读性、剧情连贯性和章节承诺是否同时成立。"],
            "forbidden_rules": ["不得把模板文字当成剧情正文；不得引入模板中没有授权的具体角色、地点、组织或事件。"],
        },
        quality_config={
            "modern_terms_policy": "contextual",
            "foreign_terms_policy": "contextual",
            "blocking_rules": {"source_conflict": True, "type_drift": True},
            "dimension_weights": {"setting_consistency": 1.0, "plot_cohesion": 1.0, "readability": 1.0},
        },
    ),
    GenreTemplate(
        scope="primary",
        category_slug="xuanhuan",
        prompt_blocks={
            "setting_rules": ["明确力量体系、世界秩序、资源稀缺性、势力边界和超凡规则的代价。"],
            "structure_rules": ["阶段推进应体现规则认知、能力代价、外部压迫和角色选择的递进。"],
            "forbidden_rules": ["未获资料授权时，不使用现代职场吐槽、互联网黑话或现实法律梗破坏类型沉浸。"],
        },
        quality_config={
            "modern_terms_policy": "block",
            "required_setting_dimensions": ["power_system", "social_order", "resource_rules"],
            "dimension_weights": {"setting_consistency": 1.2, "plot_cohesion": 1.1},
        },
    ),
    GenreTemplate(
        scope="secondary",
        category_slug="zhutian",
        parent_slug="xuanhuan",
        prompt_blocks={
            "setting_rules": ["跨世界内容必须区分来源规则、可接触边界、信息隔离和力量映射，不混淆不同规则域。"],
            "quality_rules": ["检查人物、势力、能力和道具是否绑定正确来源域；跨域调用必须有已铺垫入口。"],
        },
        quality_config={
            "required_setting_dimensions": ["domain_boundaries", "power_mapping"],
            "blocking_rules": {"source_domain_conflict": True},
        },
    ),
    GenreTemplate(
        scope="secondary",
        category_slug="workplace_business",
        parent_slug="dushi",
        prompt_blocks={
            "setting_rules": ["现实组织、合同、资金、法律、职位关系和商业因果应保持可信。"],
            "prose_rules": ["表达可使用现代生活和商业语汇，但人物行为仍需服务剧情推进和关系变化。"],
            "forbidden_rules": ["除非导入资料明确授权，不把宗门、境界突破、灵气复苏作为默认解决方案。"],
        },
        quality_config={
            "modern_terms_policy": "allow",
            "required_setting_dimensions": ["career_status", "business_stakes", "real_world_constraints"],
            "forbidden_drift_patterns": ["未授权宗门体系", "未授权境界突破"],
        },
    ),
    GenreTemplate(
        scope="secondary",
        category_slug="detective",
        parent_slug="xuanyi",
        prompt_blocks={
            "structure_rules": ["线索、疑点、误导和信息披露要公平递进，关键解答必须能回看前文找到依据。"],
            "quality_rules": ["检查案件线索链、嫌疑变化、动机可信度和解答边界。"],
        },
        quality_config={
            "required_setting_dimensions": ["clue_chain", "suspect_map", "disclosure_boundary"],
            "blocking_rules": {"unforeshadowed_solution": True},
        },
    ),
)


def default_genre() -> NovelGenre:
    return NovelGenre(
        primary_slug="general",
        primary_name="通用",
        secondary_slug="uncategorized",
        secondary_name="未分类",
    )
```

Create `src/novel_dev/genres/__init__.py`:

```python
from novel_dev.genres.defaults import BUILTIN_CATEGORIES, BUILTIN_TEMPLATES, default_genre
from novel_dev.genres.models import GenreCategory, GenreTemplate, NovelGenre, ResolvedGenreTemplate

__all__ = [
    "BUILTIN_CATEGORIES",
    "BUILTIN_TEMPLATES",
    "GenreCategory",
    "GenreTemplate",
    "NovelGenre",
    "ResolvedGenreTemplate",
    "default_genre",
]
```

- [ ] **Step 5: Run tests to verify defaults pass**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_genres/test_defaults.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add src/novel_dev/genres tests/test_genres/test_defaults.py
git commit -m "feat: add built-in novel genre defaults"
```

---

### Task 2: Database Models, Migration, And Repository

**Files:**
- Modify: `src/novel_dev/db/models.py`
- Create: `migrations/versions/20260515_add_novel_genre_templates.py`
- Create: `src/novel_dev/repositories/genre_repo.py`
- Create: `tests/test_repositories/test_genre_repo.py`

- [ ] **Step 1: Write repository tests for database category and template rows**

Create `tests/test_repositories/test_genre_repo.py`:

```python
import pytest

from novel_dev.db.models import NovelCategory, NovelGenreTemplate
from novel_dev.repositories.genre_repo import GenreRepository


@pytest.mark.asyncio
async def test_list_categories_merges_database_rows(async_session):
    async_session.add(
        NovelCategory(
            slug="custom_primary",
            name="自定义一级",
            level=1,
            parent_slug=None,
            description="测试一级分类",
            sort_order=900,
            enabled=True,
            source="db",
        )
    )
    await async_session.commit()

    repo = GenreRepository(async_session)
    categories = await repo.list_categories(include_disabled=False)

    assert any(item.slug == "xuanhuan" and item.source == "builtin" for item in categories)
    assert any(item.slug == "custom_primary" and item.source == "db" for item in categories)


@pytest.mark.asyncio
async def test_get_template_overrides_returns_enabled_rows(async_session):
    async_session.add_all(
        [
            NovelGenreTemplate(
                scope="primary",
                category_slug="xuanhuan",
                parent_slug=None,
                agent_name="WriterAgent",
                task_name="generate_beat",
                prompt_blocks={"prose_rules": ["数据库覆盖规则"]},
                quality_config={"modern_terms_policy": "block"},
                merge_policy={},
                enabled=True,
                version=2,
                source="db",
            ),
            NovelGenreTemplate(
                scope="primary",
                category_slug="xuanhuan",
                parent_slug=None,
                agent_name="WriterAgent",
                task_name="generate_beat",
                prompt_blocks={"prose_rules": ["禁用规则"]},
                quality_config={},
                merge_policy={},
                enabled=False,
                version=1,
                source="db",
            ),
        ]
    )
    await async_session.commit()

    repo = GenreRepository(async_session)
    rows = await repo.list_template_overrides()

    assert len(rows) == 1
    assert rows[0].prompt_blocks == {"prose_rules": ["数据库覆盖规则"]}
```

- [ ] **Step 2: Run repository tests to verify missing classes fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_genre_repo.py -q
```

Expected: FAIL with import errors for `NovelCategory`, `NovelGenreTemplate`, or `GenreRepository`.

- [ ] **Step 3: Add SQLAlchemy models**

Append these model classes after `NovelState` in `src/novel_dev/db/models.py`:

```python
class NovelCategory(Base):
    __tablename__ = "novel_categories"
    __table_args__ = (
        UniqueConstraint("slug", name="uix_novel_categories_slug"),
        Index("ix_novel_categories_parent", "parent_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_slug: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="db")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)


class NovelGenreTemplate(Base):
    __tablename__ = "novel_genre_templates"
    __table_args__ = (
        Index("ix_novel_genre_templates_lookup", "scope", "category_slug", "agent_name", "task_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    category_slug: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_slug: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False, default="*")
    task_name: Mapped[str] = mapped_column(Text, nullable=False, default="*")
    prompt_blocks: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    quality_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    merge_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="db")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
```

- [ ] **Step 4: Add Alembic migration**

Create `migrations/versions/20260515_add_novel_genre_templates.py`:

```python
"""add novel genre templates

Revision ID: 20260515_add_novel_genre_templates
Revises: 20260510_add_world_state_reviews
Create Date: 2026-05-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260515_add_novel_genre_templates"
down_revision = "20260510_add_world_state_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "novel_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("parent_slug", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source", sa.Text(), nullable=False, server_default="db"),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uix_novel_categories_slug"),
    )
    op.create_index("ix_novel_categories_parent", "novel_categories", ["parent_slug"])

    op.create_table(
        "novel_genre_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("category_slug", sa.Text(), nullable=True),
        sa.Column("parent_slug", sa.Text(), nullable=True),
        sa.Column("agent_name", sa.Text(), nullable=False, server_default="*"),
        sa.Column("task_name", sa.Text(), nullable=False, server_default="*"),
        sa.Column("prompt_blocks", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("quality_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("merge_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source", sa.Text(), nullable=False, server_default="db"),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_novel_genre_templates_lookup",
        "novel_genre_templates",
        ["scope", "category_slug", "agent_name", "task_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_novel_genre_templates_lookup", table_name="novel_genre_templates")
    op.drop_table("novel_genre_templates")
    op.drop_index("ix_novel_categories_parent", table_name="novel_categories")
    op.drop_table("novel_categories")
```

- [ ] **Step 5: Add repository**

Create `src/novel_dev/repositories/genre_repo.py`:

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import NovelCategory, NovelGenreTemplate
from novel_dev.genres.defaults import BUILTIN_CATEGORIES
from novel_dev.genres.models import GenreCategory, GenreTemplate


class GenreRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_categories(self, include_disabled: bool = False) -> list[GenreCategory]:
        result = await self.session.execute(select(NovelCategory).order_by(NovelCategory.sort_order, NovelCategory.name))
        db_rows = result.scalars().all()
        by_slug = {item.slug: item for item in BUILTIN_CATEGORIES}
        for row in db_rows:
            category = GenreCategory(
                slug=row.slug,
                name=row.name,
                level=1 if row.level == 1 else 2,
                parent_slug=row.parent_slug,
                description=row.description or "",
                sort_order=row.sort_order or 0,
                enabled=bool(row.enabled),
                source="db",
            )
            by_slug[category.slug] = category
        categories = list(by_slug.values())
        if not include_disabled:
            categories = [item for item in categories if item.enabled]
        return sorted(categories, key=lambda item: (item.sort_order, item.name))

    async def list_template_overrides(self) -> list[GenreTemplate]:
        result = await self.session.execute(
            select(NovelGenreTemplate)
            .where(NovelGenreTemplate.enabled.is_(True))
            .order_by(NovelGenreTemplate.scope, NovelGenreTemplate.category_slug, NovelGenreTemplate.agent_name, NovelGenreTemplate.task_name, NovelGenreTemplate.version)
        )
        templates: list[GenreTemplate] = []
        for row in result.scalars().all():
            templates.append(
                GenreTemplate(
                    scope=row.scope,
                    category_slug=row.category_slug,
                    parent_slug=row.parent_slug,
                    agent_name=row.agent_name or "*",
                    task_name=row.task_name or "*",
                    prompt_blocks=row.prompt_blocks or {},
                    quality_config=row.quality_config or {},
                    merge_policy=row.merge_policy or {},
                    enabled=bool(row.enabled),
                    version=row.version or 1,
                    source="db",
                )
            )
        return templates
```

- [ ] **Step 6: Run repository tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_repositories/test_genre_repo.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add src/novel_dev/db/models.py src/novel_dev/repositories/genre_repo.py migrations/versions/20260515_add_novel_genre_templates.py tests/test_repositories/test_genre_repo.py
git commit -m "feat: persist novel genre template overrides"
```

---

### Task 3: Genre Template Resolution Service

**Files:**
- Create: `src/novel_dev/services/genre_template_service.py`
- Create: `tests/test_services/test_genre_template_service.py`

- [ ] **Step 1: Write merge and fallback tests**

Create `tests/test_services/test_genre_template_service.py`:

```python
import pytest

from novel_dev.db.models import NovelGenreTemplate, NovelState
from novel_dev.services.genre_template_service import GenreTemplateService


@pytest.mark.asyncio
async def test_resolve_merges_global_primary_secondary_for_novel(async_session):
    async_session.add(
        NovelState(
            novel_id="n_genre",
            current_phase="brainstorming",
            checkpoint_data={
                "genre": {
                    "primary_slug": "xuanhuan",
                    "primary_name": "玄幻",
                    "secondary_slug": "zhutian",
                    "secondary_name": "诸天文",
                }
            },
        )
    )
    await async_session.commit()

    template = await GenreTemplateService(async_session).resolve("n_genre", "WriterAgent", "generate_beat")

    assert template.genre.primary_slug == "xuanhuan"
    assert any("力量体系" in item for item in template.prompt_blocks["setting_rules"])
    assert any("跨世界" in item for item in template.prompt_blocks["setting_rules"])
    assert template.quality_config["modern_terms_policy"] == "block"
    assert template.quality_config["blocking_rules"]["source_domain_conflict"] is True


@pytest.mark.asyncio
async def test_resolve_uses_database_override_after_builtin_layers(async_session):
    async_session.add_all(
        [
            NovelState(
                novel_id="n_override",
                current_phase="brainstorming",
                checkpoint_data={
                    "genre": {
                        "primary_slug": "xuanhuan",
                        "primary_name": "玄幻",
                        "secondary_slug": "zhutian",
                        "secondary_name": "诸天文",
                    }
                },
            ),
            NovelGenreTemplate(
                scope="secondary",
                category_slug="zhutian",
                parent_slug="xuanhuan",
                agent_name="WriterAgent",
                task_name="generate_beat",
                prompt_blocks={"prose_rules": ["数据库二级正文规则"]},
                quality_config={"dimension_weights": {"readability": 1.4}},
                merge_policy={},
                enabled=True,
                version=3,
                source="db",
            ),
        ]
    )
    await async_session.commit()

    template = await GenreTemplateService(async_session).resolve("n_override", "WriterAgent", "generate_beat")

    assert "数据库二级正文规则" in template.prompt_blocks["prose_rules"]
    assert template.quality_config["dimension_weights"]["readability"] == 1.4


@pytest.mark.asyncio
async def test_resolve_historical_novel_without_genre_uses_default(async_session):
    async_session.add(NovelState(novel_id="n_old", current_phase="brainstorming", checkpoint_data={}))
    await async_session.commit()

    template = await GenreTemplateService(async_session).resolve("n_old", "WriterAgent", "generate_beat")

    assert template.genre.primary_slug == "general"
    assert template.genre.secondary_slug == "uncategorized"
    assert "source_conflict" in template.quality_config["blocking_rules"]


def test_merge_replace_policy_replaces_block():
    service = GenreTemplateService(None)
    merged = service.merge_templates_for_test(
        [
            {"prompt_blocks": {"prose_rules": ["旧规则"]}, "merge_policy": {}},
            {"prompt_blocks": {"prose_rules": ["新规则"]}, "merge_policy": {"prose_rules": "replace"}},
        ]
    )
    assert merged.prompt_blocks["prose_rules"] == ["新规则"]
```

- [ ] **Step 2: Run tests to verify service is missing**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_genre_template_service.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `novel_dev.services.genre_template_service`.

- [ ] **Step 3: Implement service**

Create `src/novel_dev/services/genre_template_service.py`:

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.genres.defaults import BUILTIN_TEMPLATES, default_genre
from novel_dev.genres.models import GenreTemplate, NovelGenre, ResolvedGenreTemplate, validate_template_is_generic
from novel_dev.repositories.genre_repo import GenreRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository


class GenreTemplateService:
    def __init__(self, session: AsyncSession | None):
        self.session = session

    async def resolve(self, novel_id: str, agent_name: str, task_name: str = "*") -> ResolvedGenreTemplate:
        genre = await self.resolve_novel_genre(novel_id)
        templates = list(BUILTIN_TEMPLATES)
        if self.session is not None:
            templates.extend(await GenreRepository(self.session).list_template_overrides())
        matched = self._select_templates(templates, genre, agent_name, task_name)
        warnings: list[str] = []
        if not any(item.scope == "primary" and item.category_slug == genre.primary_slug for item in matched):
            warnings.append(f"genre_template_missing:primary:{genre.primary_slug}")
        if not any(item.scope == "secondary" and item.category_slug == genre.secondary_slug for item in matched):
            warnings.append(f"genre_template_missing:secondary:{genre.secondary_slug}")
        resolved = self._merge_templates(genre, matched)
        resolved.warnings.extend(warnings)
        return resolved

    async def resolve_novel_genre(self, novel_id: str) -> NovelGenre:
        if self.session is None:
            return default_genre()
        state = await NovelStateRepository(self.session).get_state(novel_id)
        checkpoint = state.checkpoint_data if state is not None else {}
        raw = (checkpoint or {}).get("genre") or {}
        if not raw:
            return default_genre()
        return NovelGenre(
            primary_slug=str(raw.get("primary_slug") or "general"),
            primary_name=str(raw.get("primary_name") or "通用"),
            secondary_slug=str(raw.get("secondary_slug") or "uncategorized"),
            secondary_name=str(raw.get("secondary_name") or "未分类"),
        )

    def _select_templates(
        self,
        templates: list[GenreTemplate],
        genre: NovelGenre,
        agent_name: str,
        task_name: str,
    ) -> list[GenreTemplate]:
        selected: list[GenreTemplate] = []
        layer_keys = [
            ("global", None),
            ("primary", genre.primary_slug),
            ("secondary", genre.secondary_slug),
        ]
        specificity = [
            ("*", "*"),
            (agent_name, "*"),
            ("*", task_name),
            (agent_name, task_name),
        ]
        for scope, category_slug in layer_keys:
            for agent_key, task_key in specificity:
                for template in templates:
                    if not template.enabled:
                        continue
                    validate_template_is_generic(template)
                    if template.scope != scope:
                        continue
                    if template.category_slug != category_slug:
                        continue
                    if template.agent_name != agent_key or template.task_name != task_key:
                        continue
                    selected.append(template)
        return selected

    def _merge_templates(self, genre: NovelGenre, templates: list[GenreTemplate]) -> ResolvedGenreTemplate:
        prompt_blocks: dict[str, list[str]] = {}
        quality_config: dict[str, Any] = {}
        matched_templates: list[str] = []
        for template in templates:
            matched_templates.append(f"{template.source}:{template.scope}:{template.category_slug or 'global'}:{template.agent_name}:{template.task_name}:v{template.version}")
            for name, values in template.prompt_blocks.items():
                if template.merge_policy.get(name) == "replace":
                    prompt_blocks[name] = []
                existing = prompt_blocks.setdefault(name, [])
                for value in values:
                    if value not in existing:
                        existing.append(value)
            quality_config = self._deep_merge(quality_config, template.quality_config)
        return ResolvedGenreTemplate(
            genre=genre,
            prompt_blocks=prompt_blocks,
            quality_config=quality_config,
            matched_templates=matched_templates,
        )

    def _deep_merge(self, base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(base)
        for key, value in (incoming or {}).items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = self._deep_merge(result[key], value)
            elif isinstance(value, list) and isinstance(result.get(key), list):
                merged = list(result[key])
                for item in value:
                    if item not in merged:
                        merged.append(item)
                result[key] = merged
            else:
                result[key] = deepcopy(value)
        return result

    def merge_templates_for_test(self, raw_templates: list[dict[str, Any]]) -> ResolvedGenreTemplate:
        templates = [GenreTemplate(scope="global", **raw) for raw in raw_templates]
        return self._merge_templates(default_genre(), templates)
```

- [ ] **Step 4: Run service tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_genre_template_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add src/novel_dev/services/genre_template_service.py tests/test_services/test_genre_template_service.py
git commit -m "feat: resolve novel genre templates"
```

---

### Task 4: Category API And Create-Novel Validation

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Create: `tests/test_api/test_novel_categories.py`
- Modify: `tests/test_api/test_create_novel.py`
- Modify: `tests/test_api/test_novel_list.py`
- Modify affected tests that call `POST /api/novels` with only `title`.

- [ ] **Step 1: Add API tests**

Create `tests/test_api/test_novel_categories.py`:

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.db.models import NovelState


app = FastAPI()
app.include_router(router)


def genre_payload(title="分类小说", primary="xuanhuan", secondary="zhutian"):
    return {
        "title": title,
        "primary_category_slug": primary,
        "secondary_category_slug": secondary,
    }


@pytest.mark.asyncio
async def test_list_novel_categories(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/novel-categories")
            assert resp.status_code == 200
            data = resp.json()
            xuanhuan = next(item for item in data if item["slug"] == "xuanhuan")
            assert xuanhuan["name"] == "玄幻"
            assert any(child["slug"] == "zhutian" for child in xuanhuan["children"])
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_novel_requires_matching_primary_and_secondary(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            missing = await client.post("/api/novels", json={"title": "缺分类"})
            assert missing.status_code == 422

            mismatch = await client.post("/api/novels", json=genre_payload(primary="xuanhuan", secondary="workplace_business"))
            assert mismatch.status_code == 422

            ok = await client.post("/api/novels", json=genre_payload())
            assert ok.status_code == 201
            data = ok.json()
            assert data["genre"]["primary_slug"] == "xuanhuan"
            assert data["genre"]["secondary_slug"] == "zhutian"
            assert data["checkpoint_data"]["genre"]["primary_name"] == "玄幻"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_state_for_historical_novel_returns_default_genre(async_session):
    async_session.add(NovelState(novel_id="n_legacy_genre", current_phase="brainstorming", checkpoint_data={"novel_title": "旧书"}))
    await async_session.commit()

    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/novels/n_legacy_genre/state")
            assert resp.status_code == 200
            assert resp.json()["genre"] == {
                "primary_slug": "general",
                "primary_name": "通用",
                "secondary_slug": "uncategorized",
                "secondary_name": "未分类",
            }
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run API tests to verify current API fails**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_novel_categories.py -q
```

Expected: FAIL with `404` for `/api/novel-categories` or `422` mismatch assertions failing.

- [ ] **Step 3: Update request model and helpers in routes**

Modify `src/novel_dev/api/routes.py` near `CreateNovelRequest`:

```python
class CreateNovelRequest(BaseModel):
    title: str
    primary_category_slug: str
    secondary_category_slug: str
```

Add helpers near `_get_novel_display_title`:

```python
from novel_dev.genres.defaults import default_genre
from novel_dev.repositories.genre_repo import GenreRepository


def _serialize_genre(genre) -> dict[str, str]:
    return {
        "primary_slug": genre.primary_slug,
        "primary_name": genre.primary_name,
        "secondary_slug": genre.secondary_slug,
        "secondary_name": genre.secondary_name,
    }


def _get_checkpoint_genre(checkpoint_data: dict[str, Any]) -> dict[str, str]:
    raw = (checkpoint_data or {}).get("genre") or {}
    if not raw:
        return _serialize_genre(default_genre())
    return {
        "primary_slug": str(raw.get("primary_slug") or "general"),
        "primary_name": str(raw.get("primary_name") or "通用"),
        "secondary_slug": str(raw.get("secondary_slug") or "uncategorized"),
        "secondary_name": str(raw.get("secondary_name") or "未分类"),
    }


async def _resolve_create_genre(session: AsyncSession, primary_slug: str, secondary_slug: str) -> dict[str, str]:
    categories = await GenreRepository(session).list_categories(include_disabled=False)
    primary = next((item for item in categories if item.slug == primary_slug and item.level == 1), None)
    secondary = next((item for item in categories if item.slug == secondary_slug and item.level == 2), None)
    if primary is None:
        raise HTTPException(status_code=422, detail="一级分类不存在或已停用")
    if secondary is None:
        raise HTTPException(status_code=422, detail="二级分类不存在或已停用")
    if secondary.parent_slug != primary.slug:
        raise HTTPException(status_code=422, detail="二级分类不属于所选一级分类")
    return {
        "primary_slug": primary.slug,
        "primary_name": primary.name,
        "secondary_slug": secondary.slug,
        "secondary_name": secondary.name,
    }
```

- [ ] **Step 4: Add category endpoint**

Add route before `POST /api/novels`:

```python
@router.get("/api/novel-categories")
async def list_novel_categories(session: AsyncSession = Depends(get_session)):
    categories = await GenreRepository(session).list_categories(include_disabled=False)
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    for item in categories:
        if item.level == 2 and item.parent_slug:
            children_by_parent.setdefault(item.parent_slug, []).append(
                {
                    "slug": item.slug,
                    "name": item.name,
                    "description": item.description,
                    "sort_order": item.sort_order,
                }
            )
    payload = []
    for item in categories:
        if item.level != 1:
            continue
        payload.append(
            {
                "slug": item.slug,
                "name": item.name,
                "description": item.description,
                "sort_order": item.sort_order,
                "children": children_by_parent.get(item.slug, []),
            }
        )
    return payload
```

- [ ] **Step 5: Update create-novel checkpoint and response**

In `create_novel`, after title validation:

```python
    genre = await _resolve_create_genre(
        session,
        req.primary_category_slug.strip(),
        req.secondary_category_slug.strip(),
    )
```

Add `genre` to `checkpoint_data`:

```python
        "genre": genre,
```

Add `genre` to response:

```python
        "genre": _get_checkpoint_genre(state.checkpoint_data or {}),
```

Also add the same `genre` field to `get_novel_state`, `list_novels`, and `update_novel` responses. Use `_get_checkpoint_genre(checkpoint_data)`.

- [ ] **Step 6: Update existing create-novel tests**

In `tests/test_api/test_create_novel.py`, add:

```python
def create_payload(title="测试小说", primary="xuanhuan", secondary="zhutian"):
    return {
        "title": title,
        "primary_category_slug": primary,
        "secondary_category_slug": secondary,
    }
```

Change calls like:

```python
resp = await client.post("/api/novels", json={"title": "测试小说"})
```

to:

```python
resp = await client.post("/api/novels", json=create_payload("测试小说"))
```

Keep the empty-title test as:

```python
resp = await client.post("/api/novels", json=create_payload("  "))
```

Add assertions:

```python
assert data["genre"]["primary_slug"] == "xuanhuan"
assert data["genre"]["secondary_slug"] == "zhutian"
```

- [ ] **Step 7: Run create/list API tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api/test_novel_categories.py tests/test_api/test_create_novel.py tests/test_api/test_novel_list.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

Run:

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_novel_categories.py tests/test_api/test_create_novel.py tests/test_api/test_novel_list.py
git commit -m "feat: require genre when creating novels"
```

---

### Task 5: Frontend Create-Novel Category Selection

**Files:**
- Modify: `src/novel_dev/web/src/api.js`
- Modify: `src/novel_dev/web/src/components/NovelSelector.vue`
- Modify/Create: `src/novel_dev/web/src/components/NovelSelector.test.js`
- Modify: `src/novel_dev/web/src/api.test.js`

- [ ] **Step 1: Write frontend API tests**

In `src/novel_dev/web/src/api.test.js`, add or update tests:

```javascript
import { describe, expect, it, vi } from 'vitest'
import { createNovel, getNovelCategories } from './api.js'

describe('genre APIs', () => {
  it('fetches novel categories', async () => {
    const spy = vi.spyOn(globalThis, 'fetch')
    expect(typeof getNovelCategories).toBe('function')
    spy.mockRestore()
  })

  it('createNovel accepts a payload with required genre slugs', () => {
    const payload = {
      title: '分类小说',
      primary_category_slug: 'xuanhuan',
      secondary_category_slug: 'zhutian',
    }
    expect(() => createNovel(payload)).not.toThrow()
  })
})
```

Use the current `api.test.js` axios mock style. The assertion must verify that `api.post('/novels', payload)` receives the full object above, not only the title string.

- [ ] **Step 2: Update API client**

Modify `src/novel_dev/web/src/api.js`:

```javascript
export const listNovels = () => api.get('/novels').then(r => r.data)
export const getNovelCategories = () => api.get('/novel-categories').then(r => r.data)
export const createNovel = (payload) => api.post('/novels', payload).then(r => r.data)
```

- [ ] **Step 3: Update NovelSelector UI**

Modify `src/novel_dev/web/src/components/NovelSelector.vue`.

Template inside `<el-form>`:

```vue
<el-form :model="createForm" label-position="top" @submit.prevent="doCreate">
  <el-form-item label="标题">
    <el-input v-model="createForm.title" placeholder="请输入小说标题" @keyup.enter="doCreate" />
  </el-form-item>
  <el-form-item label="一级分类">
    <el-select v-model="createForm.primary_category_slug" placeholder="请选择一级分类" style="width: 100%">
      <el-option
        v-for="item in categoryOptions"
        :key="item.slug"
        :label="item.name"
        :value="item.slug"
      />
    </el-select>
  </el-form-item>
  <el-form-item label="二级分类">
    <el-select
      v-model="createForm.secondary_category_slug"
      placeholder="请选择二级分类"
      style="width: 100%"
      :disabled="!createForm.primary_category_slug"
    >
      <el-option
        v-for="item in secondaryCategoryOptions"
        :key="item.slug"
        :label="item.name"
        :value="item.slug"
      />
    </el-select>
  </el-form-item>
</el-form>
```

Footer button disabled expression:

```vue
:disabled="!canCreate"
```

Script imports:

```javascript
import { computed, ref, watch } from 'vue'
import { listNovels, createNovel, getNovelCategories } from '@/api.js'
```

State:

```javascript
const categoryOptions = ref([])
const createForm = ref({
  title: '',
  primary_category_slug: '',
  secondary_category_slug: '',
})

const secondaryCategoryOptions = computed(() => {
  const primary = categoryOptions.value.find(item => item.slug === createForm.value.primary_category_slug)
  return primary?.children || []
})

const canCreate = computed(() => (
  createForm.value.title.trim() &&
  createForm.value.primary_category_slug &&
  createForm.value.secondary_category_slug
))
```

Fetch categories:

```javascript
async function fetchCategories() {
  try {
    categoryOptions.value = await getNovelCategories()
  } catch {
    categoryOptions.value = []
  }
}
```

Update `doCreate`:

```javascript
async function doCreate() {
  if (!canCreate.value) return
  creating.value = true
  try {
    const res = await createNovel({
      title: createForm.value.title.trim(),
      primary_category_slug: createForm.value.primary_category_slug,
      secondary_category_slug: createForm.value.secondary_category_slug,
    })
    ElMessage.success('小说创建成功')
    showCreateDialog.value = false
    createForm.value = { title: '', primary_category_slug: '', secondary_category_slug: '' }
    await fetchNovels()
    if (res.novel_id) {
      store.loadNovel(res.novel_id)
    }
  } catch (e) {
    // api interceptor already shows error
  } finally {
    creating.value = false
  }
}
```

Add watcher:

```javascript
watch(() => createForm.value.primary_category_slug, () => {
  createForm.value.secondary_category_slug = ''
})
```

Call:

```javascript
fetchNovels()
fetchCategories()
```

- [ ] **Step 4: Run frontend tests**

Run:

```bash
cd src/novel_dev/web
npm test -- --run src/api.test.js src/components/NovelSelector.test.js
```

Expected: PASS.

Create `src/novel_dev/web/src/components/NovelSelector.test.js` before running the command:

```javascript
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import NovelSelector from './NovelSelector.vue'

vi.mock('@/api.js', () => ({
  listNovels: vi.fn().mockResolvedValue({ items: [] }),
  getNovelCategories: vi.fn().mockResolvedValue([
    { slug: 'xuanhuan', name: '玄幻', children: [{ slug: 'zhutian', name: '诸天文' }] },
  ]),
  createNovel: vi.fn().mockResolvedValue({ novel_id: 'novel-test', title: '测试小说' }),
}))

vi.mock('@/stores/novel.js', () => ({
  useNovelStore: () => ({ novelId: '', novelTitle: '', loadNovel: vi.fn() }),
}))

describe('NovelSelector genre creation', () => {
  it('requires title and both category levels before creation', async () => {
    const wrapper = mount(NovelSelector, {
      global: {
        stubs: {
          ElSelectV2: true,
          ElDialog: { template: '<div><slot /><slot name="footer" /></div>' },
          ElForm: { template: '<form><slot /></form>' },
          ElFormItem: { template: '<div><slot /></div>' },
          ElInput: { template: '<input />' },
          ElSelect: { template: '<select><slot /></select>' },
          ElOption: true,
          ElButton: { props: ['disabled'], template: '<button :disabled="disabled"><slot /></button>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.vm.canCreate).toBeFalsy()
    wrapper.vm.createForm.title = '测试小说'
    wrapper.vm.createForm.primary_category_slug = 'xuanhuan'
    wrapper.vm.createForm.secondary_category_slug = 'zhutian'
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.canCreate).toBeTruthy()
  })
})
```

- [ ] **Step 5: Commit Task 5**

Run:

```bash
git add src/novel_dev/web/src/api.js src/novel_dev/web/src/api.test.js src/novel_dev/web/src/components/NovelSelector.vue src/novel_dev/web/src/components/NovelSelector.test.js
git commit -m "feat: select genre when creating novels"
```

---

### Task 6: Quality Configuration Integration

**Files:**
- Modify: `src/novel_dev/services/prose_hygiene_service.py`
- Modify: `src/novel_dev/services/quality_gate_service.py`
- Create/Modify: `tests/test_services/test_prose_hygiene_service.py`
- Create/Modify: `tests/test_services/test_quality_gate_service.py`

- [ ] **Step 1: Add prose hygiene tests for genre quality config**

Append to `tests/test_services/test_prose_hygiene_service.py`:

```python
from novel_dev.services.prose_hygiene_service import ProseHygieneService


def test_modern_terms_block_when_genre_policy_blocks_even_with_ambiguous_context():
    issues = ProseHygieneService.find_issues(
        "他忍不住吐槽这套 KPI 和互联网黑话。",
        context={"genre_quality_config": {"modern_terms_policy": "block"}},
    )
    assert any(issue.code == "modern_drift" for issue in issues)


def test_modern_terms_allow_when_genre_policy_allows():
    issues = ProseHygieneService.find_issues(
        "合同、融资和公司会议让他意识到局势正在变化。",
        context={"genre_quality_config": {"modern_terms_policy": "allow"}},
    )
    assert not any(issue.code == "modern_drift" for issue in issues)
```

- [ ] **Step 2: Update ProseHygieneService policy handling**

In `src/novel_dev/services/prose_hygiene_service.py`, add helper:

```python
    @classmethod
    def _genre_quality_config(cls, context: object | None = None) -> dict:
        if isinstance(context, dict):
            value = context.get("genre_quality_config") or {}
            return value if isinstance(value, dict) else {}
        value = getattr(context, "genre_quality_config", None)
        return value if isinstance(value, dict) else {}
```

In the modern-drift authorization check, read policy first:

```python
        policy = cls._genre_quality_config(context).get("modern_terms_policy")
        if policy == "allow":
            return True
        if policy == "block":
            return False
```

Keep existing contextual behavior when policy is missing or `contextual`.

- [ ] **Step 3: Add quality gate tests for type drift**

In `tests/test_services/test_quality_gate_service.py`, add:

```python
from novel_dev.services.quality_gate_service import QualityGateService


def test_quality_gate_builds_genre_type_drift_items():
    items = QualityGateService.genre_type_drift_items(
        "董事会刚结束，他突然回宗门突破境界。",
        {
            "blocking_rules": {"type_drift": True},
            "forbidden_drift_patterns": ["宗门", "境界突破"],
        },
    )
    assert items == [
        "type_drift: 命中类型漂移规则：宗门",
        "type_drift: 命中类型漂移规则：境界突破",
    ]
```

- [ ] **Step 4: Implement quality gate type-drift check**

In `src/novel_dev/services/quality_gate_service.py`, add a helper:

```python
    @classmethod
    def genre_type_drift_items(cls, text: str, quality_config: dict | None = None) -> list[str]:
        config = quality_config or {}
        if not (config.get("blocking_rules") or {}).get("type_drift"):
            return []
        items = []
        for pattern in config.get("forbidden_drift_patterns") or []:
            if pattern and pattern in text:
                items.append(f"type_drift: 命中类型漂移规则：{pattern}")
        return items
```

Task 8 threads `quality_config` and chapter text through `FastReviewAgent` and calls this helper there.

- [ ] **Step 5: Run quality tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_services/test_prose_hygiene_service.py tests/test_services/test_quality_gate_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

Run:

```bash
git add src/novel_dev/services/prose_hygiene_service.py src/novel_dev/services/quality_gate_service.py tests/test_services/test_prose_hygiene_service.py tests/test_services/test_quality_gate_service.py
git commit -m "feat: apply genre quality configuration"
```

---

### Task 7: Prompt Injection In Brainstorm And Writer

**Files:**
- Modify: `src/novel_dev/agents/brainstorm_agent.py`
- Modify: `src/novel_dev/agents/writer_agent.py`
- Modify: `tests/test_agents/test_writer_agent_chapters.py`
- Create/Modify: `tests/test_agents/test_brainstorm_agent.py`

- [ ] **Step 1: Add Writer prompt test**

In `tests/test_agents/test_writer_agent_chapters.py`, add:

```python
@pytest.mark.asyncio
async def test_writer_prompt_includes_resolved_genre_rules(async_session, mocker):
    from novel_dev.db.models import NovelState
    from novel_dev.agents.writer_agent import WriterAgent
    from novel_dev.schemas.context import BeatPlan, ChapterContext, ChapterPlan, LocationContext

    async_session.add(
        NovelState(
            novel_id="n_writer_genre",
            current_phase="drafting",
            checkpoint_data={
                "genre": {
                    "primary_slug": "xuanhuan",
                    "primary_name": "玄幻",
                    "secondary_slug": "zhutian",
                    "secondary_name": "诸天文",
                }
            },
        )
    )
    await async_session.commit()

    captured = {}

    async def fake_generate(*args, **kwargs):
        captured["system"] = args[0][0].content
        return type("Resp", (), {"text": "他按住呼吸，沿着既定规则推进。"})

    mock_client = mocker.Mock()
    mock_client.acomplete.side_effect = fake_generate
    mocker.patch("novel_dev.llm.llm_factory.get", return_value=mock_client)
    mocker.patch("novel_dev.llm.llm_factory._resolve_config", return_value={})

    agent = WriterAgent(async_session)
    beat = BeatPlan(summary="主角在规则压力下做出选择。", target_mood="紧张", target_word_count=300)
    context = ChapterContext(
        chapter_plan=ChapterPlan(
            chapter_number=1,
            title="第一章",
            target_word_count=800,
            beats=[beat],
        ),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="测试场景"),
        timeline_events=[],
        pending_foreshadowings=[],
        story_contract={},
    )
    await agent._generate_beat(beat, context, [], "", 0, 1, True, novel_id="n_writer_genre")

    assert "力量体系" in captured["system"]
    assert "跨世界" in captured["system"]
    assert "互联网黑话" in captured["system"]
```

- [ ] **Step 2: Add Brainstorm prompt test**

In `tests/test_agents/test_brainstorm_agent.py`, add:

```python
@pytest.mark.asyncio
async def test_brainstorm_prompt_includes_genre_structure_rules(async_session, mocker):
    from novel_dev.agents.brainstorm_agent import BrainstormAgent
    from novel_dev.db.models import NovelDocument, NovelState

    async_session.add_all(
        [
            NovelState(
                novel_id="n_brain_genre",
                current_phase="brainstorming",
                checkpoint_data={
                    "genre": {
                        "primary_slug": "xuanyi",
                        "primary_name": "悬疑",
                        "secondary_slug": "detective",
                        "secondary_name": "推理探案",
                    }
                },
            ),
            NovelDocument(
                id="doc_brain_genre",
                novel_id="n_brain_genre",
                doc_type="setting",
                title="设定资料",
                content="主角调查一桩旧案。",
                version=1,
            ),
        ]
    )
    await async_session.commit()

    captured = {}

    async def fake_call(agent_name, task_name, prompt, model, **kwargs):
        captured["prompt"] = prompt
        return model(
            title="测试",
            logline="调查者追查旧案但遭遇阻力并承担代价。",
            core_conflict="调查者与隐藏真相者的对抗",
            themes=["真相"],
            character_arcs=[],
            milestones=[],
            estimated_volumes=1,
            estimated_total_chapters=10,
            estimated_total_words=30000,
            volume_outlines=[],
            entity_highlights={},
            relationship_highlights=[],
        )

    mocker.patch("novel_dev.agents.brainstorm_agent.call_and_parse_model", side_effect=fake_call)

    await BrainstormAgent(async_session).generate_synopsis("n_brain_genre")

    assert "线索" in captured["prompt"]
    assert "信息披露" in captured["prompt"]
```

- [ ] **Step 3: Inject genre blocks in BrainstormAgent**

In `src/novel_dev/agents/brainstorm_agent.py`, import:

```python
from novel_dev.services.genre_template_service import GenreTemplateService
```

Before building top-level synopsis prompt:

```python
        genre_template = await GenreTemplateService(self.session).resolve(
            novel_id,
            "BrainstormAgent",
            "generate_synopsis_top_level",
        )
        genre_block = genre_template.render_prompt_block(
            "source_rules",
            "setting_rules",
            "structure_rules",
            "quality_rules",
            "forbidden_rules",
        )
```

Add to prompt before source text:

```python
            f"## 类型模板约束\n{genre_block or '使用通用类型约束。'}\n\n"
```

Repeat the same pattern for batch volume-outline generation with task name `generate_volume_outlines_batch`.

- [ ] **Step 4: Inject genre blocks in WriterAgent**

In `src/novel_dev/agents/writer_agent.py`, import:

```python
from novel_dev.services.genre_template_service import GenreTemplateService
```

In the async method that calls `_build_system_prompt`, resolve template:

```python
        genre_template = None
        if novel_id:
            genre_template = await GenreTemplateService(self.session).resolve(
                novel_id,
                "WriterAgent",
                "generate_beat",
            )
        system_prompt = self._build_system_prompt(context, is_last, genre_template)
```

Change signature:

```python
    def _build_system_prompt(self, context: ChapterContext, is_last: bool, genre_template=None) -> str:
```

Add block before prose hygiene:

```python
        genre_block = ""
        if genre_template is not None:
            genre_block = genre_template.render_prompt_block("prose_rules", "forbidden_rules", "quality_rules")
        parts = [
            "你是一位追求沉浸感与可读性的中文小说家。按以下约束生成正文。只返回正文，不添加解释。",
            self._build_style_guide_block(context),
            self._build_writing_rules_block(is_last),
            genre_block,
            ProseHygieneService.prompt_rules(context),
        ]
```

Pass `genre_template.quality_config` separately to `_enforce_prose_hygiene` and `_self_check_beat` in follow-up edits inside this task; do not assign dynamic attributes to `ChapterContext`.

- [ ] **Step 5: Run agent prompt tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_writer_agent_chapters.py tests/test_agents/test_brainstorm_agent.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 7**

Run:

```bash
git add src/novel_dev/agents/brainstorm_agent.py src/novel_dev/agents/writer_agent.py tests/test_agents/test_writer_agent_chapters.py tests/test_agents/test_brainstorm_agent.py
git commit -m "feat: inject genre rules into generation prompts"
```

---

### Task 8: Prompt And Quality Integration In Planning, Settings, And Fast Review

**Files:**
- Modify: `src/novel_dev/agents/setting_workbench_agent.py`
- Modify: `src/novel_dev/agents/volume_planner.py`
- Modify: `src/novel_dev/agents/fast_review_agent.py`
- Modify: `tests/test_agents/test_setting_workbench_agent.py`
- Modify: `tests/test_agents/test_volume_planner.py`
- Modify: `tests/test_agents/test_fast_review_agent.py`

- [ ] **Step 1: Add tests for setting, volume, and fast-review genre behavior**

Add focused tests:

```python
@pytest.mark.asyncio
async def test_setting_generation_prompt_includes_genre_setting_rules(async_session):
    from novel_dev.agents.setting_workbench_agent import SettingWorkbenchAgent
    prompt = SettingWorkbenchAgent.build_generation_prompt(
        initial_idea="只使用导入资料生成设定。",
        conversation_summary="",
        target_categories=["世界观"],
        source_context="资料片段",
        genre_prompt_block="明确力量体系、世界秩序、资源稀缺性。",
    )
    assert "力量体系" in prompt
    assert "资源稀缺性" in prompt
```

```python
@pytest.mark.asyncio
async def test_volume_planner_prompt_includes_genre_structure_rules(async_session, mocker):
    from novel_dev.agents.volume_planner import VolumePlannerAgent
    from novel_dev.db.models import NovelState

    async_session.add(
        NovelState(
            novel_id="n_volume_genre",
            current_phase="volume_planning",
            checkpoint_data={
                "genre": {
                    "primary_slug": "xuanhuan",
                    "primary_name": "玄幻",
                    "secondary_slug": "zhutian",
                    "secondary_name": "诸天文",
                },
                "synopsis_data": {
                    "title": "测试",
                    "logline": "主角追求目标但遭遇阻力。",
                    "core_conflict": "主角与规则压力的冲突",
                    "themes": ["成长"],
                    "character_arcs": [],
                    "milestones": [],
                    "estimated_volumes": 1,
                    "estimated_total_chapters": 3,
                    "estimated_total_words": 9000,
                    "volume_outlines": [],
                },
            },
        )
    )
    await async_session.commit()

    captured = {}

    async def fake_call(agent_name, task_name, prompt, model, **kwargs):
        captured["prompt"] = prompt
        raise RuntimeError("stop after prompt capture")

    mocker.patch("novel_dev.agents.volume_planner.call_and_parse_model", side_effect=fake_call)

    with pytest.raises(RuntimeError, match="stop after prompt capture"):
        await VolumePlannerAgent(async_session).generate_volume_plan("n_volume_genre")

    assert "跨世界" in captured["prompt"]
    assert "力量映射" in captured["prompt"]
```

```python
def test_fast_review_uses_genre_quality_config_for_type_drift():
    from novel_dev.agents.fast_review_agent import _build_genre_quality_issues
    issues = _build_genre_quality_issues(
        "董事会刚结束，他突然回宗门突破境界。",
        genre_quality_config={
            "blocking_rules": {"type_drift": True},
            "forbidden_drift_patterns": ["宗门", "境界突破"],
        },
    )
    assert any(issue.code == "type_drift" for issue in issues)
```

- [ ] **Step 2: Update SettingWorkbenchAgent prompt builder**

In `src/novel_dev/agents/setting_workbench_agent.py`, change static builder signatures to accept optional `genre_prompt_block: str = ""`. Insert:

```python
        if genre_prompt_block:
            sections.append("## 类型模板约束\n" + genre_prompt_block)
```

In service code that calls `SettingWorkbenchAgent.build_generation_prompt`, resolve:

```python
genre_template = await GenreTemplateService(self.session).resolve(novel_id, "SettingWorkbenchAgent", "generate_settings")
genre_prompt_block = genre_template.render_prompt_block("source_rules", "setting_rules", "quality_rules", "forbidden_rules")
```

Pass `genre_prompt_block=genre_prompt_block`.

- [ ] **Step 3: Update VolumePlannerAgent**

In `src/novel_dev/agents/volume_planner.py`, import `GenreTemplateService`. Before main planning prompt:

```python
genre_template = await GenreTemplateService(self.session).resolve(
    novel_id,
    "VolumePlannerAgent",
    "generate_volume_plan",
)
genre_block = genre_template.render_prompt_block("structure_rules", "setting_rules", "quality_rules", "forbidden_rules")
```

Add to planning prompt before schema/output rules:

```python
f"## 类型模板约束\n{genre_block or '使用通用类型约束。'}\n\n"
```

Use task names `review_volume_plan` and `revise_volume_plan` in review/revision prompt paths.

- [ ] **Step 4: Update FastReviewAgent**

In `src/novel_dev/agents/fast_review_agent.py`, resolve at the start of final review:

```python
genre_template = await GenreTemplateService(self.session).resolve(
    novel_id,
    "FastReviewAgent",
    "fast_review",
)
genre_block = genre_template.render_prompt_block("quality_rules", "forbidden_rules")
```

Add `genre_block` to the LLM review prompt. Pass `genre_template.quality_config` to local quality checks and `QualityGateService`.

Add local pure helper:

```python
def _build_genre_quality_issues(text: str, genre_quality_config: dict | None = None) -> list[QualityIssue]:
    issues = []
    for item in QualityGateService.genre_type_drift_items(text, genre_quality_config):
        issues.append(
            QualityIssue(
                code="type_drift",
                category="style",
                severity="block",
                scope="chapter",
                repairability="guided",
                evidence=[item],
                suggestion="按所选小说分类移除未授权类型漂移内容。",
                source="fast_review",
            )
        )
    return issues
```

Merge returned issues into existing fast-review issue collection before the final gate.

- [ ] **Step 5: Run focused agent tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_agents/test_setting_workbench_agent.py tests/test_agents/test_volume_planner.py tests/test_agents/test_fast_review_agent.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 8**

Run:

```bash
git add src/novel_dev/agents/setting_workbench_agent.py src/novel_dev/agents/volume_planner.py src/novel_dev/agents/fast_review_agent.py tests/test_agents/test_setting_workbench_agent.py tests/test_agents/test_volume_planner.py tests/test_agents/test_fast_review_agent.py
git commit -m "feat: apply genre templates to planning and review"
```

---

### Task 9: Test Runner, Reports, And Existing Test Payloads

**Files:**
- Modify: `src/novel_dev/testing/generation_runner.py`
- Modify: `tests/test_testing/test_generation_runner.py`
- Modify: `tests/generation/test_minimal_generation_flow.py`
- Modify: `tests/test_integration_end_to_end.py`
- Modify additional tests found by `rg -n 'post\\(\"/api/novels\"|POST\", \"http://testserver/api/novels\"' tests src/novel_dev/testing`

- [ ] **Step 1: Add generation runner tests**

In `tests/test_testing/test_generation_runner.py`, add:

```python
def test_create_novel_payload_includes_default_genre_for_longform_runner():
    from novel_dev.testing.generation_runner import _build_create_novel_payload

    payload = _build_create_novel_payload("正式小说", acceptance_scope="real-longform-volume1")

    assert payload["title"] == "正式小说"
    assert payload["primary_category_slug"] == "xuanhuan"
    assert payload["secondary_category_slug"] == "zhutian"


def test_report_summary_includes_genre_resolution():
    from novel_dev.testing.generation_runner import _summarize_genre_report

    summary = _summarize_genre_report(
        {
            "genre": {"primary_name": "玄幻", "secondary_name": "诸天文"},
            "checkpoint_data": {
                "genre_template": {
                    "matched_templates": ["builtin:global:global:*:*:v1"],
                    "warnings": [],
                }
            },
        }
    )

    assert summary["genre"] == "玄幻 / 诸天文"
    assert summary["template_layers"] == 1
```

- [ ] **Step 2: Implement payload helper and report summary**

In `src/novel_dev/testing/generation_runner.py`, add:

```python
def _build_create_novel_payload(title: str, acceptance_scope: str = "") -> dict[str, str]:
    if acceptance_scope == "real-longform-volume1":
        return {
            "title": title,
            "primary_category_slug": "xuanhuan",
            "secondary_category_slug": "zhutian",
        }
    return {
        "title": title,
        "primary_category_slug": "general",
        "secondary_category_slug": "uncategorized",
    }


def _summarize_genre_report(state_payload: dict) -> dict:
    genre = state_payload.get("genre") or (state_payload.get("checkpoint_data") or {}).get("genre") or {}
    template = (state_payload.get("checkpoint_data") or {}).get("genre_template") or {}
    primary = genre.get("primary_name") or "通用"
    secondary = genre.get("secondary_name") or "未分类"
    return {
        "genre": f"{primary} / {secondary}",
        "template_layers": len(template.get("matched_templates") or []),
        "template_warnings": template.get("warnings") or [],
    }
```

Replace direct create payload:

```python
{"title": title}
```

with:

```python
_build_create_novel_payload(title, acceptance_scope=self.acceptance_scope)
```

Add the genre summary to final report JSON under key `genre_template_summary`.

- [ ] **Step 3: Update direct create-novel test calls**

Run:

```bash
rg -n 'post\\(\"/api/novels\"|POST\", \"http://testserver/api/novels\"|json=\\{\"title\"' tests src/novel_dev/testing
```

For each direct create-novel call, change payload to include:

```python
{
    "title": "测试标题",
    "primary_category_slug": "general",
    "secondary_category_slug": "uncategorized",
}
```

For formal longform runner tests, use:

```python
{
    "title": "测试标题",
    "primary_category_slug": "xuanhuan",
    "secondary_category_slug": "zhutian",
}
```

- [ ] **Step 4: Run testing suite subset**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_testing/test_generation_runner.py tests/generation/test_minimal_generation_flow.py tests/test_integration_end_to_end.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 9**

Run:

```bash
git add src/novel_dev/testing/generation_runner.py tests/test_testing/test_generation_runner.py tests/generation/test_minimal_generation_flow.py tests/test_integration_end_to_end.py
git commit -m "test: pass genre through generation workflows"
```

---

### Task 10: Generalization Rule, Template Safety Scan, And Full Verification

**Files:**
- Modify: `AGENTS.md`
- Modify/Create: `tests/test_genres/test_template_safety.py`

- [ ] **Step 1: Add AGENTS rule**

In `AGENTS.md`, under the existing formal workflow generalization rules, add:

```markdown
- Novel genre templates are type-level rules only. Production templates must not contain concrete novel characters, places, organizations, plot events, one-off fallback paragraphs, or external-IP facts. Genre prompts may describe generic type expectations such as power-system boundaries, clue fairness, modern vocabulary policy, or cross-domain consistency, but must stay source-driven and reusable across novels in the same category.
```

- [ ] **Step 2: Add production safety test**

Create `tests/test_genres/test_template_safety.py`:

```python
import pytest

from novel_dev.genres.defaults import BUILTIN_TEMPLATES
from novel_dev.genres.models import validate_template_is_generic


@pytest.mark.parametrize("template", BUILTIN_TEMPLATES)
def test_production_genre_templates_are_generic(template):
    validate_template_is_generic(template)
```

- [ ] **Step 3: Run safety scan**

Run:

```bash
rg -n "陆照|李大牛|王明月|青云宗|玄火盟|血海殿|瓦片|凝气草|职场霸凌还不用负法律责任|搁前世|藏书阁" src/novel_dev/genres src/novel_dev/agents src/novel_dev/services src/novel_dev/testing/generation_runner.py AGENTS.md
```

Expected: no matches. If matches appear in tests only, keep them outside production paths and do not scan `tests/` with this command.

- [ ] **Step 4: Run backend focused suite**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_genres tests/test_services/test_genre_template_service.py tests/test_services/test_prose_hygiene_service.py tests/test_services/test_quality_gate_service.py tests/test_repositories/test_genre_repo.py tests/test_api/test_novel_categories.py tests/test_api/test_create_novel.py tests/test_agents/test_writer_agent_chapters.py tests/test_agents/test_brainstorm_agent.py tests/test_agents/test_setting_workbench_agent.py tests/test_agents/test_volume_planner.py tests/test_agents/test_fast_review_agent.py tests/test_testing/test_generation_runner.py -q
```

Expected: PASS.

- [ ] **Step 5: Run frontend focused suite**

Run:

```bash
cd src/novel_dev/web
npm test -- --run src/api.test.js src/components/NovelSelector.test.js
```

Expected: PASS.

- [ ] **Step 6: Commit Task 10**

Run:

```bash
git add AGENTS.md tests/test_genres/test_template_safety.py
git commit -m "docs: require generic genre templates"
```

---

## Final Verification

After all tasks are complete, run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_genres tests/test_services/test_genre_template_service.py tests/test_services/test_prose_hygiene_service.py tests/test_services/test_quality_gate_service.py tests/test_repositories/test_genre_repo.py tests/test_api/test_novel_categories.py tests/test_api/test_create_novel.py tests/test_api/test_novel_list.py tests/test_agents/test_writer_agent_chapters.py tests/test_agents/test_brainstorm_agent.py tests/test_agents/test_setting_workbench_agent.py tests/test_agents/test_volume_planner.py tests/test_agents/test_fast_review_agent.py tests/test_testing/test_generation_runner.py -q
```

Then run:

```bash
cd src/novel_dev/web
npm test -- --run src/api.test.js src/components/NovelSelector.test.js
```

Then run the production-template safety scan:

```bash
rg -n "陆照|李大牛|王明月|青云宗|玄火盟|血海殿|瓦片|凝气草|职场霸凌还不用负法律责任|搁前世|藏书阁" src/novel_dev/genres src/novel_dev/agents src/novel_dev/services src/novel_dev/testing/generation_runner.py AGENTS.md
```

Expected final result:

- Backend focused suite passes.
- Frontend focused suite passes.
- Safety scan has no matches.
- New novels require `primary_category_slug` and `secondary_category_slug`.
- Historical novels without `genre` load as `通用 / 未分类`.
- Formal test runner creates real longform novels as `玄幻 / 诸天文`.
- Agent prompts include resolved genre rules without hardcoded per-agent category branches.
- Quality checks use resolved `quality_config` for modern-term and type-drift behavior.

## Self-Review

Spec coverage:

- Required primary and secondary category selection: Tasks 4 and 5.
- Built-in defaults with database overrides: Tasks 1, 2, and 3.
- Three-layer template merge: Task 3.
- Prompt injection into key agents: Tasks 7 and 8.
- Quality-gate and validation parameters: Tasks 6 and 8.
- Historical compatibility: Tasks 3 and 4.
- Test runner and reports: Task 9.
- Generic formal workflow rule in `AGENTS.md`: Task 10.

Type consistency:

- Category request fields use `primary_category_slug` and `secondary_category_slug` in API, frontend, and test runner.
- Stored checkpoint metadata uses `genre.primary_slug`, `genre.primary_name`, `genre.secondary_slug`, and `genre.secondary_name`.
- Template service returns `ResolvedGenreTemplate` with `prompt_blocks`, `quality_config`, `matched_templates`, and `warnings`.
- Agent task names are stable strings used only for template lookup; missing task-specific templates fall back to wildcard templates.
