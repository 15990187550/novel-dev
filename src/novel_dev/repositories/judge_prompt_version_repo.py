from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import JudgePromptVersion


class JudgePromptVersionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active(self) -> Optional[JudgePromptVersion]:
        result = await self.session.execute(
            select(JudgePromptVersion)
            .where(JudgePromptVersion.is_active.is_(True))
            .order_by(JudgePromptVersion.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_by_id(self, pv_id: str) -> Optional[JudgePromptVersion]:
        return await self.session.get(JudgePromptVersion, pv_id)

    async def get_active_at(self, at: datetime) -> Optional[JudgePromptVersion]:
        """返回 ≤ at 时间点上 is_active=True 的最新版本,用于事后回放。"""
        result = await self.session.execute(
            select(JudgePromptVersion)
            .where(
                JudgePromptVersion.is_active.is_(True),
                JudgePromptVersion.created_at <= at,
            )
            .order_by(JudgePromptVersion.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def set_active(self, pv_id: str) -> None:
        """把指定 pv 设为 active,同时把同 agent_name 的其他 active 全部置 False。"""
        target = await self.session.get(JudgePromptVersion, pv_id)
        if target is None:
            return
        # Deactivate all currently active
        result = await self.session.execute(
            select(JudgePromptVersion)
            .where(
                JudgePromptVersion.agent_name == target.agent_name,
                JudgePromptVersion.is_active.is_(True),
                JudgePromptVersion.id != pv_id,
            )
        )
        for pv in result.scalars().all():
            pv.is_active = False
        target.is_active = True
        await self.session.flush()

    async def append_history(self, pv_id: str, entry: dict) -> None:
        """追加一条 experiment_history 记录(原子操作)。"""
        pv = await self.session.get(JudgePromptVersion, pv_id)
        if pv is None:
            return
        history = list(pv.experiment_history or [])
        history.append(entry)
        pv.experiment_history = history
        await self.session.flush()

    async def set_ab_test_id(self, pv_id: str, ab_test_id: str) -> None:
        pv = await self.session.get(JudgePromptVersion, pv_id)
        if pv is None:
            return
        pv.ab_test_id = ab_test_id
        await self.session.flush()