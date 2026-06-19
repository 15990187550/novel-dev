from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import JudgeABTest


class JudgeABTestRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        baseline_version: str,
        challenger_version: str,
        config: Optional[dict] = None,
        agent_name: str = "judge_agent",
    ) -> JudgeABTest:
        ab = JudgeABTest(
            agent_name=agent_name,
            baseline_version=baseline_version,
            challenger_version=challenger_version,
            status="running",
            config=config or {},
            started_at=datetime.utcnow(),
        )
        self.session.add(ab)
        await self.session.flush()
        return ab

    async def get(self, ab_id: str) -> Optional[JudgeABTest]:
        return await self.session.get(JudgeABTest, ab_id)

    async def list_by_status(self, status: str) -> list[JudgeABTest]:
        result = await self.session.execute(
            select(JudgeABTest).where(JudgeABTest.status == status)
        )
        return list(result.scalars().all())

    async def complete(self, ab_id: str, winner: str) -> None:
        ab = await self.session.get(JudgeABTest, ab_id)
        if ab is None:
            return
        ab.status = "completed"
        ab.winner = winner
        ab.ended_at = datetime.utcnow()
        await self.session.flush()
