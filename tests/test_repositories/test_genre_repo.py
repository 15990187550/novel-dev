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
async def test_disabled_database_category_override_hides_builtin_by_default(async_session):
    async_session.add(
        NovelCategory(
            slug="xuanhuan",
            name="玄幻停用",
            level=1,
            parent_slug=None,
            description="停用内置玄幻",
            sort_order=10,
            enabled=False,
            source="db",
        )
    )
    await async_session.commit()

    repo = GenreRepository(async_session)
    visible = await repo.list_categories(include_disabled=False)
    all_categories = await repo.list_categories(include_disabled=True)

    assert not any(item.slug == "xuanhuan" for item in visible)
    override = next(item for item in all_categories if item.slug == "xuanhuan")
    assert override.name == "玄幻停用"
    assert override.enabled is False
    assert override.source == "db"


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
