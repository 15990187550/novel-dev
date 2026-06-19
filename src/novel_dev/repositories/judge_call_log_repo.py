from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import JudgeCallLog


class JudgeCallLogRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log(
        self,
        decision_id: Optional[str],
        experiment_id: Optional[str],
        prompt_version_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        cost_usd: float,
    ) -> JudgeCallLog:
        entry = JudgeCallLog(
            decision_id=decision_id,
            experiment_id=experiment_id,
            prompt_version_id=prompt_version_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            called_at=datetime.utcnow(),
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def sum_cost_for_experiment(self, experiment_id: str) -> float:
        result = await self.session.execute(
            select(func.coalesce(func.sum(JudgeCallLog.cost_usd), 0.0))
            .where(JudgeCallLog.experiment_id == experiment_id)
        )
        return float(result.scalar() or 0.0)

    async def count_calls_for_experiment(
        self, experiment_id: str, since: Optional[datetime] = None,
    ) -> int:
        stmt = select(func.count(JudgeCallLog.id)).where(
            JudgeCallLog.experiment_id == experiment_id
        )
        if since is not None:
            stmt = stmt.where(JudgeCallLog.called_at >= since)
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0)