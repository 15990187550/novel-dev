from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import ABTest, PromptVersion
from novel_dev.repositories.ab_decision_repo import ABDecisionRepository
from novel_dev.repositories.prompt_version_repo import PromptVersionRepository
from novel_dev.services.ab_significance import SignificanceTester
from novel_dev.services.ab_weighted_score import WeightedScoreCalculator
from novel_dev.services.ab_decision_recorder import ABDecisionRecorder


@dataclass
class DeciderResult:
    action: str  # "accepted" | "no_action" | "skipped" | "no_improvement" | "error"
    winner: Optional[str] = None
    p_value: Optional[float] = None
    scores: Optional[dict] = None
    reason: Optional[str] = None


class ABAcceptanceDecider:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.weighted_calc = WeightedScoreCalculator()
        self.significance_tester = SignificanceTester()
        self.pv_repo = PromptVersionRepository(session)
        self.decision_repo = ABDecisionRepository(session)
        self.recorder = ABDecisionRecorder(session)

    async def evaluate(
        self, experiment_id: str, sample_scores: dict,
    ) -> DeciderResult:
        ab = await self.session.get(ABTest, experiment_id)
        if not ab or ab.status != "running":
            return DeciderResult(action="no_action", reason="experiment_not_running")

        scores = self.weighted_calc.compute_batch(sample_scores)
        if any(v is None for v in scores.values()):
            await self.recorder.record(
                experiment_id=experiment_id,
                action="evaluate",
                scores=scores,
                meta={"decision": "skipped", "reason": "calculator_returned_none"},
            )
            return DeciderResult(action="skipped", reason="calculator_returned_none")

        versions = [ab.baseline_version, ab.challenger_version]
        scores_by_version_for_test = {
            v: sample_scores.get(v, {}).get("critic_scores", [])
            for v in versions
        }
        significance = self.significance_tester.test(scores_by_version_for_test)

        await self.recorder.record(
            experiment_id=experiment_id,
            action="evaluate",
            scores=scores,
            p_value=significance.p_value,
            effect_size=significance.effect_size,
            meta={
                "decision": "accepted" if significance.is_significant else "no_action",
                "threshold": significance.threshold_used,
                "reason": significance.reason,
            },
        )

        if not significance.is_significant:
            return DeciderResult(
                action="no_action",
                p_value=significance.p_value,
                scores=scores,
                reason=significance.reason,
            )

        winner = max(scores, key=scores.get)
        if winner == ab.baseline_version:
            for pv in await self._get_pvs(ab):
                if pv.version == ab.challenger_version:
                    await self.pv_repo.update_experiment_state(pv.id, "no_improvement")
            await self.recorder.record(
                experiment_id=experiment_id,
                action="evaluate",
                scores=scores,
                meta={"decision": "no_improvement", "winner": winner},
            )
            return DeciderResult(action="no_improvement", winner=winner, scores=scores)

        for pv in await self._get_pvs(ab):
            if pv.version == winner:
                await self.pv_repo.update_experiment_state(
                    pv.id, "auto_accepted", last_score=scores[winner],
                    decision_at=datetime.utcnow(),
                )
                pv.is_active = True
                await self.pv_repo.append_history(pv.id, {
                    "action": "auto_accepted",
                    "experiment_id": ab.id,
                    "weighted_score": scores[winner],
                    "p_value": significance.p_value,
                    "at": datetime.utcnow().isoformat(),
                })
            elif pv.version == ab.baseline_version:
                pv.is_active = False
                await self.pv_repo.update_experiment_state(
                    pv.id, "active-rolled-back",
                    decision_at=datetime.utcnow(),
                )
                await self.pv_repo.append_history(pv.id, {
                    "action": "active-rolled-back",
                    "experiment_id": ab.id,
                    "at": datetime.utcnow().isoformat(),
                })

        ab.status = "completed"
        ab.winner = winner
        ab.ended_at = datetime.utcnow()
        await self.session.flush()

        winner_pv = next(pv for pv in await self._get_pvs(ab) if pv.version == winner)
        await self.recorder.record(
            experiment_id=experiment_id,
            action="accept",
            prompt_version_id=winner_pv.id,
            scores=scores,
            p_value=significance.p_value,
            effect_size=significance.effect_size,
            meta={"winner": winner, "monitoring_window_hours": 24},
        )

        return DeciderResult(action="accepted", winner=winner, p_value=significance.p_value, scores=scores)

    async def _get_pvs(self, ab: ABTest) -> list[PromptVersion]:
        result = await self.session.execute(
            select(PromptVersion).where(PromptVersion.ab_test_id == ab.id)
        )
        return list(result.scalars().all())
