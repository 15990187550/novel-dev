from __future__ import annotations
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.db.models import JudgeABTest
from novel_dev.services.judge_acceptance_decider import JudgeAcceptanceDecider

logger = logging.getLogger(__name__)


class JudgeAcceptanceSweeper:
    def __init__(self, session: AsyncSession, config: JudgeConfig, decider: Optional[JudgeAcceptanceDecider] = None):
        self.session = session
        self.config = config
        self.decider = decider or JudgeAcceptanceDecider(session, config)

    async def tick(self) -> list[dict]:
        """每 5 分钟(或按调度)扫一次所有 running / completed 的 judge_ab_tests。"""
        result = await self.session.execute(
            select(JudgeABTest).where(JudgeABTest.status.in_(["running", "completed"]))
        )
        experiments = list(result.scalars().all())
        decisions = []
        for ab in experiments:
            try:
                dr = await self.decider.evaluate(ab.id)
                if dr.action != "no_action":
                    decisions.append({
                        "action": dr.action,
                        "experiment_id": ab.id,
                        "winner": dr.winner,
                        "reason": dr.reason,
                        "agreement_rate": dr.agreement_rate,
                    })
            except Exception as exc:
                logger.exception(
                    "judge_sweeper_experiment_failed",
                    extra={"experiment_id": ab.id, "error": str(exc)},
                )
        return decisions