from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import ABDecision


class ABDecisionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, experiment_id: str, action: str,
        prompt_version_id: Optional[str] = None,
        decision_at: Optional[datetime] = None,
        p_value: Optional[float] = None,
        scores: Optional[dict] = None,
        effect_size: Optional[float] = None,
        meta: Optional[dict] = None,
    ) -> ABDecision:
        d = ABDecision(
            experiment_id=experiment_id,
            prompt_version_id=prompt_version_id,
            action=action,
            decision_at=decision_at or datetime.utcnow(),
            p_value=p_value,
            scores=scores or {},
            effect_size=effect_size,
            meta=meta or {},
        )
        self.session.add(d)
        await self.session.flush()
        return d

    async def list_by_experiment(self, experiment_id: str) -> list[ABDecision]:
        result = await self.session.execute(
            select(ABDecision)
            .where(ABDecision.experiment_id == experiment_id)
            .order_by(ABDecision.decision_at.asc())
        )
        return list(result.scalars().all())

    async def list_recent(self, window_minutes: int = 60) -> list[ABDecision]:
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        result = await self.session.execute(
            select(ABDecision)
            .where(ABDecision.decision_at >= cutoff)
            .order_by(ABDecision.decision_at.desc())
        )
        return list(result.scalars().all())

    async def latest_for_experiment(self, experiment_id: str) -> Optional[ABDecision]:
        result = await self.session.execute(
            select(ABDecision)
            .where(ABDecision.experiment_id == experiment_id)
            .order_by(ABDecision.decision_at.desc())
            .limit(1)
        )
        return result.scalars().first()
