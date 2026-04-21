from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
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
