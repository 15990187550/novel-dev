from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import PromptVersion


class PromptVersionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        agent_name: str,
        version: str,
        content: str,
        is_active: bool = False,
        created_by: str = "user",
        parent_version: Optional[str] = None,
        ab_test_id: Optional[str] = None,
    ) -> PromptVersion:
        pv = PromptVersion(
            agent_name=agent_name,
            version=version,
            content=content,
            is_active=is_active,
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

    async def get_by_version(
        self, agent_name: str, version: str
    ) -> Optional[PromptVersion]:
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
        """原子切换：旧 active 关 + 新 active 开（同事务）"""
        target = await self.get_by_version(agent_name, version)
        if not target:
            raise ValueError(
                f"Version {version} not found for agent {agent_name}"
            )
        result = await self.session.execute(
            select(PromptVersion).where(
                PromptVersion.agent_name == agent_name,
                PromptVersion.is_active == True,  # noqa: E712
            )
        )
        for old in result.scalars().all():
            old.is_active = False
        target.is_active = True
        await self.session.flush()

    async def delete(self, agent_name: str, version: str) -> None:
        target = await self.get_by_version(agent_name, version)
        if not target:
            return
        if target.is_active:
            raise ValueError(
                f"Cannot delete active version {version} for agent {agent_name}"
            )
        await self.session.delete(target)
        await self.session.flush()

    async def increment_sample_count(
        self, agent_name: str, version: str
    ) -> None:
        target = await self.get_by_version(agent_name, version)
        if target:
            target.sample_count += 1
            await self.session.flush()
