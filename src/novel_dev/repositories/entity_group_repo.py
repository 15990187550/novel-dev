from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import EntityGroup


class EntityGroupRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(
        self,
        novel_id: str,
        category: str,
        group_name: str,
        group_slug: str,
        source: str = "system",
        sort_order: int = 0,
    ) -> EntityGroup:
        bind = self.session.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name in {"postgresql", "sqlite"}:
            insert_factory = postgresql_insert if dialect_name == "postgresql" else sqlite_insert
            statement = insert_factory(EntityGroup).values(
                id=f"group-{uuid4().hex}",
                novel_id=novel_id,
                category=category,
                group_name=group_name,
                group_slug=group_slug,
                source=source,
                sort_order=sort_order,
                is_active=True,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[
                    EntityGroup.novel_id,
                    EntityGroup.category,
                    EntityGroup.group_slug,
                ],
                set_={
                    "group_name": statement.excluded.group_name,
                    "source": statement.excluded.source,
                    "sort_order": statement.excluded.sort_order,
                    "is_active": True,
                },
            ).returning(EntityGroup.id)
            result = await self.session.execute(statement)
            group_id = result.scalar_one()
            group_result = await self.session.execute(
                select(EntityGroup).where(EntityGroup.id == group_id)
                .execution_options(populate_existing=True)
            )
            return group_result.scalar_one()

        result = await self.session.execute(
            select(EntityGroup).where(
                EntityGroup.novel_id == novel_id,
                EntityGroup.category == category,
                EntityGroup.group_slug == group_slug,
            )
        )
        group = result.scalar_one_or_none()
        if group is not None:
            group.group_name = group_name
            group.source = source
            group.sort_order = sort_order
            await self.session.flush()
            return group

        group = EntityGroup(
            id=f"group-{uuid4().hex}",
            novel_id=novel_id,
            category=category,
            group_name=group_name,
            group_slug=group_slug,
            source=source,
            sort_order=sort_order,
        )
        self.session.add(group)
        await self.session.flush()
        return group
