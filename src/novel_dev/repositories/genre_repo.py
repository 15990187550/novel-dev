from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import NovelCategory, NovelGenreTemplate
from novel_dev.genres import BUILTIN_CATEGORIES, GenreCategory, GenreTemplate


class GenreRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_categories(self, include_disabled: bool = False) -> list[GenreCategory]:
        result = await self.session.execute(select(NovelCategory))

        categories_by_slug = {category.slug: category for category in BUILTIN_CATEGORIES}
        for row in result.scalars().all():
            categories_by_slug[row.slug] = GenreCategory(
                slug=row.slug,
                name=row.name,
                level=row.level,
                parent_slug=row.parent_slug,
                description=row.description or "",
                sort_order=row.sort_order,
                enabled=row.enabled,
                source="db",
            )

        categories = list(categories_by_slug.values())
        if not include_disabled:
            categories = [category for category in categories if category.enabled]
        return sorted(categories, key=lambda category: (category.sort_order, category.name))

    async def list_template_overrides(self) -> list[GenreTemplate]:
        result = await self.session.execute(
            select(NovelGenreTemplate)
            .where(NovelGenreTemplate.enabled.is_(True))
            .order_by(
                NovelGenreTemplate.scope,
                NovelGenreTemplate.category_slug,
                NovelGenreTemplate.agent_name,
                NovelGenreTemplate.task_name,
                NovelGenreTemplate.version,
            )
        )
        return [
            GenreTemplate(
                scope=row.scope,
                category_slug=row.category_slug,
                parent_slug=row.parent_slug,
                agent_name=row.agent_name,
                task_name=row.task_name,
                prompt_blocks=dict(row.prompt_blocks or {}),
                quality_config=dict(row.quality_config or {}),
                merge_policy=dict(row.merge_policy or {}),
                enabled=row.enabled,
                version=row.version,
                source="db",
            )
            for row in result.scalars().all()
        ]
