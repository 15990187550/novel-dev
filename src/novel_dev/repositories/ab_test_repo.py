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
