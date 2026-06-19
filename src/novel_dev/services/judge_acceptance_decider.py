from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.db.models import JudgeABTest, JudgePromptVersion
from novel_dev.repositories.judge_prompt_version_repo import JudgePromptVersionRepository
from novel_dev.repositories.judge_ab_test_repo import JudgeABTestRepository
from novel_dev.services.judge_meta_evaluator import JudgeMetaEvaluator


@dataclass
class JudgeDeciderResult:
    action: str  # "accept" | "continue_monitoring" | "early_stop" | "no_action"
    winner: Optional[str] = None
    reason: Optional[str] = None
    sample_size: int = 0
    agreement_rate: Optional[float] = None


ACCEPT_THRESHOLD = 0.80
EARLY_STOP_THRESHOLD = 0.55


class JudgeAcceptanceDecider:
    def __init__(self, session: AsyncSession, config: JudgeConfig):
        self.session = session
        self.config = config
        self.pv_repo = JudgePromptVersionRepository(session)
        self.ab_repo = JudgeABTestRepository(session)
        self.meta_evaluator = JudgeMetaEvaluator(session, config)

    async def evaluate(self, experiment_id: str) -> JudgeDeciderResult:
        ab = await self.session.get(JudgeABTest, experiment_id)
        if not ab or ab.status != "running":
            return JudgeDeciderResult(action="no_action", reason="experiment_not_running")

        # 查 challenger pv(有 ab_test_id 指向当前 experiment)
        pv_result = await self.session.execute(
            select(JudgePromptVersion).where(JudgePromptVersion.ab_test_id == experiment_id)
        )
        challenger_pv = pv_result.scalars().first()
        if challenger_pv is None:
            return JudgeDeciderResult(action="no_action", reason="no_challenger_pv")

        meta = await self.meta_evaluator.evaluate(challenger_pv.id)

        if meta.insufficient_data:
            return JudgeDeciderResult(
                action="continue_monitoring",
                reason="insufficient_data",
                sample_size=meta.sample_size,
                agreement_rate=None,
            )

        if meta.agreement_rate >= ACCEPT_THRESHOLD:
            # 接受 challenger
            await self.pv_repo.set_active(challenger_pv.id)
            await self.pv_repo.append_history(challenger_pv.id, {
                "action": "judge_auto_accepted",
                "agreement_rate": meta.agreement_rate,
                "sample_size": meta.sample_size,
                "at": datetime.utcnow().isoformat(),
            })
            # Deactivate baseline
            bp_result = await self.session.execute(
                select(JudgePromptVersion).where(
                    JudgePromptVersion.version == ab.baseline_version,
                    JudgePromptVersion.agent_name == ab.agent_name,
                )
            )
            baseline_pv = bp_result.scalars().first()
            if baseline_pv is not None:
                baseline_pv.is_active = False
                await self.pv_repo.append_history(baseline_pv.id, {
                    "action": "judge_active_replaced",
                    "agreement_rate": meta.agreement_rate,
                    "at": datetime.utcnow().isoformat(),
                })
            await self.session.flush()

            await self.ab_repo.complete(experiment_id, winner=ab.challenger_version)
            return JudgeDeciderResult(
                action="accept",
                winner=ab.challenger_version,
                sample_size=meta.sample_size,
                agreement_rate=meta.agreement_rate,
            )

        if meta.agreement_rate <= EARLY_STOP_THRESHOLD:
            # 早停,标记 challenger 为 early_stopped
            challenger_pv.experiment_state = "early_stopped"
            await self.session.flush()
            await self.ab_repo.complete(experiment_id, winner=ab.baseline_version)
            return JudgeDeciderResult(
                action="early_stop",
                winner=ab.baseline_version,
                reason="low_calibration",
                sample_size=meta.sample_size,
                agreement_rate=meta.agreement_rate,
            )

        return JudgeDeciderResult(
            action="continue_monitoring",
            sample_size=meta.sample_size,
            agreement_rate=meta.agreement_rate,
        )
