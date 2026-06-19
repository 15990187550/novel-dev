from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import ABTest, PromptVersion
from novel_dev.repositories.ab_decision_repo import ABDecisionRepository
from novel_dev.repositories.prompt_version_repo import PromptVersionRepository
from novel_dev.services.ab_weighted_score import WeightedScoreCalculator
from novel_dev.services.ab_decision_recorder import ABDecisionRecorder

logger = logging.getLogger(__name__)


class ABAcceptanceSweeper:
    def __init__(self, session: AsyncSession, weighted_calc: Optional[WeightedScoreCalculator] = None):
        self.session = session
        self.weighted_calc = weighted_calc or WeightedScoreCalculator()
        self.pv_repo = PromptVersionRepository(session)
        self.decision_repo = ABDecisionRepository(session)
        self.recorder = ABDecisionRecorder(session)

    async def tick(self) -> list[dict]:
        ab_tests = await self._list_running_and_monitoring()
        decisions = []
        for ab in ab_tests:
            try:
                result = await self._evaluate_one(ab)
                if result:
                    decisions.append(result)
            except Exception as exc:
                logger.exception(
                    "ab_sweeper_experiment_failed",
                    extra={"experiment_id": ab.id, "error": str(exc)},
                )
        return decisions

    async def _list_running_and_monitoring(self) -> list[ABTest]:
        result = await self.session.execute(
            select(ABTest).where(ABTest.status.in_(["running", "completed"]))
        )
        return list(result.scalars().all())

    async def _evaluate_one(self, ab: ABTest) -> Optional[dict]:
        cfg = ab.config or {}
        if ab.status == "running":
            return await self._maybe_early_stop_or_timeout(ab, cfg)
        if ab.status == "completed":
            return await self._maybe_rollback(ab, cfg)
        return None

    async def _maybe_early_stop_or_timeout(self, ab: ABTest, cfg: dict) -> Optional[dict]:
        timeout_days = cfg.get("timeout_days", 7)
        if (datetime.utcnow() - ab.started_at) > timedelta(days=timeout_days):
            ab.status = "timeout"
            ab.ended_at = datetime.utcnow()
            await self.session.flush()
            await self._mark_challenger_state(ab, "no_improvement")
            await self.recorder.record(
                experiment_id=ab.id, action="timeout",
                meta={"days_elapsed": (datetime.utcnow() - ab.started_at).days},
            )
            return {"action": "timeout", "experiment_id": ab.id}

        consecutive_loss = cfg.get("early_stop_consecutive_loss", 3)
        min_loss_lift = cfg.get("early_stop_min_lift", -0.10)
        if self._consecutive_loss_count(ab.id) >= consecutive_loss:
            scores = await self._compute_recent_scores(ab)
            if scores is None:
                return None
            baseline_score = scores.get(ab.baseline_version)
            challenger_score = scores.get(ab.challenger_version)
            if baseline_score and challenger_score:
                lift = (challenger_score - baseline_score) / baseline_score
                if lift <= min_loss_lift:
                    ab.status = "early_stopped"
                    ab.ended_at = datetime.utcnow()
                    await self.session.flush()
                    await self._mark_challenger_state(ab, "early_stopped")
                    await self.recorder.record(
                        experiment_id=ab.id, action="early_stop",
                        scores=scores,
                        meta={"consecutive_loss": consecutive_loss, "lift": lift},
                    )
                    return {"action": "early_stop", "experiment_id": ab.id}
        return None

    async def _maybe_rollback(self, ab: ABTest, cfg: dict) -> Optional[dict]:
        monitoring_hours = cfg.get("monitoring_hours", 24)
        drop_threshold = cfg.get("rollback_drop_threshold", 0.05)
        if not ab.ended_at:
            return None
        elapsed = datetime.utcnow() - ab.ended_at
        if elapsed > timedelta(hours=monitoring_hours):
            return None
        scores = await self._compute_recent_scores(ab)
        if scores is None or not ab.winner:
            return None
        winner_score = scores.get(ab.winner)
        if winner_score is None:
            return None
        baseline_score_at_accept = await self._baseline_score_at_accept(ab)
        if not baseline_score_at_accept:
            return None
        drop = (baseline_score_at_accept - winner_score) / baseline_score_at_accept
        if drop < drop_threshold:
            return None

        prev_stable = await self.pv_repo.get_previous_stable(ab.agent_name, exclude_version=ab.winner)
        if not prev_stable:
            await self._mark_challenger_state(ab, "rolled_back")
            await self.recorder.record(
                experiment_id=ab.id, action="rollback_no_target",
                scores=scores,
                meta={"drop": drop, "reason": "no_previous_stable"},
            )
            return {"action": "rollback_no_target", "experiment_id": ab.id}

        for pv in await self._get_pvs(ab):
            if pv.version == ab.winner:
                pv.is_active = False
                await self.pv_repo.update_experiment_state(pv.id, "rolled_back")
            elif pv.version == prev_stable.version:
                pv.is_active = True
                await self.pv_repo.update_experiment_state(pv.id, "active-rolled-back")

        ab.status = "rolled_back"
        await self.session.flush()
        await self.recorder.record(
            experiment_id=ab.id, action="rolled_back",
            scores=scores,
            meta={"drop": drop, "restored_to": prev_stable.version},
        )
        return {"action": "rolled_back", "experiment_id": ab.id}

    async def _compute_recent_scores(self, ab: ABTest) -> Optional[dict]:
        try:
            samples = await self._gather_recent_samples(ab)
            return self.weighted_calc.compute_batch(samples)
        except Exception:
            return None

    async def _gather_recent_samples(self, ab: ABTest) -> dict:
        """Gather recent samples for each version in the experiment.

        Uses PromptVersion.last_score as a proxy for the version's current score.
        In production this should pull from chapter_quality_repo for the
        last monitoring_hours window.
        """
        samples = {
            ab.baseline_version: {"critic_scores": [], "hook_achieved": [], "thrill_verified": []},
            ab.challenger_version: {"critic_scores": [], "hook_achieved": [], "thrill_verified": []},
        }
        result = await self.session.execute(
            select(PromptVersion).where(PromptVersion.ab_test_id == ab.id)
        )
        for pv in result.scalars().all():
            entry = samples.get(pv.version)
            if entry is None:
                continue
            if pv.last_score is not None:
                entry["critic_scores"] = [pv.last_score]
                entry["hook_achieved"] = [True]
                entry["thrill_verified"] = [True]
        return samples

    def _consecutive_loss_count(self, experiment_id: str) -> int:
        """Return how many consecutive times the challenger lost to baseline.

        Stub: queries ab_decisions table for recent evaluate records and counts
        consecutive rows where challenger_score < baseline_score. Returns 0 as
        safe default. Production should use Redis counters or a materialized view.
        """
        return 0

    async def _baseline_score_at_accept(self, ab: ABTest) -> Optional[float]:
        latest = await self.decision_repo.latest_for_experiment(ab.id)
        if not latest:
            return None
        scores = latest.scores or {}
        return scores.get(ab.winner)

    async def _mark_challenger_state(self, ab: ABTest, state: str) -> None:
        for pv in await self._get_pvs(ab):
            if pv.version == ab.challenger_version:
                await self.pv_repo.update_experiment_state(pv.id, state)

    async def _get_pvs(self, ab: ABTest) -> list[PromptVersion]:
        result = await self.session.execute(
            select(PromptVersion).where(PromptVersion.ab_test_id == ab.id)
        )
        return list(result.scalars().all())
